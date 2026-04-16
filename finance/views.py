from django.shortcuts import redirect, render
from .forms import  TransactionPIN, PINForm
from .accesstoken import get_access_token_value
import base64
import requests
from finance.models import Transaction, Wallet, InvestmentTracking, CompanyAccount
import json
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from decimal import Decimal, ROUND_DOWN, InvalidOperation
from user.models import TransactionPIN
from decimal import Decimal
from django.contrib import messages
import uuid
import json
from django.db import transaction
from django.db.models import Sum
from django.contrib.sites.shortcuts import get_current_site
from user.utils import process_maturity, get_wallet_balance
from .stkpush import stk_push
from user.decorators import profile_required
from finance.models import LedgerEntry
from django.db import transaction as db_transaction

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction as db_transaction
from django.utils import timezone
import json

from finance.models import Transaction, CompanyAccount



PUBLIC_URL = "https://faidii.com"




@login_required
def set_pin(request):
    try:
        pin_obj = TransactionPIN.objects.get(user=request.user)
    except TransactionPIN.DoesNotExist:
        pin_obj = None

    if request.method == "POST":
        form = PINForm(request.POST, instance=pin_obj)
        if form.is_valid():
            form.save(user=request.user)
            return redirect('user:dashboard')
    else:  
        form = PINForm(instance=pin_obj)

    return render(request, 'user/set_pin.html', {'form': form})


MIN_DEPOSIT = 1  # Minimum deposit amount in KSh

@login_required
def deposit(request):
    wallet, _ = Wallet.objects.get_or_create(user=request.user)

    if request.method == "POST":
        phone = request.POST.get("phone")
        amount = request.POST.get("amount")
        method = request.POST.get("method")

        # -----------------------------
        # VALIDATE AMOUNT
        # -----------------------------
        try:
            amount = Decimal(amount)
        except:
            return render(request, "finance/deposit.html", {
                "balance": get_wallet_balance(),
                "message": {"title": "Error", "body": "Invalid amount"}
            })

        if amount < MIN_DEPOSIT:
            return render(request, "finance/deposit.html", {
                "balance": get_wallet_balance(request.user),
                "message": {"title": "Error", "body": f"Minimum deposit is KES {MIN_DEPOSIT}"}
            })

        # -----------------------------
        # VALIDATE METHOD
        # -----------------------------
        if method != "mpesa":
            return render(request, "finance/deposit.html", {
                "balance": get_wallet_balance(),
                "message": {"title": "Error", "body": "Only MPESA allowed"}
            })

        # -----------------------------
        # SEND STK PUSH FIRST 🔥
        # -----------------------------
        response = stk_push(request)
        res = json.loads(response.content)
        print("STK RESPONSE:", res)

        # -----------------------------
        # HANDLE FAILED STK
        # -----------------------------
        if not res or res.get("ResponseCode") != "0":
            return render(request, "finance/deposit.html", {
                "balance": get_wallet_balance(),
                "message": {"title": "Error", "body": "STK Push failed"}
            })

        # -----------------------------
        # NOW GET CHECKOUT ID ✅
        # -----------------------------
        checkout_id = res.get("CheckoutRequestID")

        # -----------------------------
        # CREATE TRANSACTION NOW ✅
        # -----------------------------
        tx = Transaction.objects.create(
            user=request.user,
            amount=amount,
            checkout_id=checkout_id,
            phone_number=request.user.phone,
            tx_type="deposit",
            status="pending"
        )

        # -----------------------------
        # UI ONLY (PENDING DISPLAY)
        # -----------------------------
        wallet.pending_deposit = amount
        wallet.save()

        # -----------------------------
        # REFERRAL BONUS HANDLING
        # -----------------------------
        # Check if this is the user's first deposit
        first_deposit = Transaction.objects.filter(
            user=request.user,
            tx_type__iexact="deposit",
            status__iexact="completed"
        ).exclude(id=tx.id).exists()

        if not first_deposit and request.user.referred_by:
            bonus_amount = (amount * Decimal("0.10")).quantize(Decimal("0.01"))
            from finance.models import CompanyAccount
            CompanyAccount.post_referral_bonus(
                referrer=request.user.referred_by,
                amount=bonus_amount,
                referred_user=request.user
            )

        # OPTIONAL SESSION STORAGE
        request.session["checkout_id"] = checkout_id

        return redirect("finance:transactions")

    return render(request, "finance/deposit.html", {
        "balance": get_wallet_balance(request.user)
    })


# -------------------------
# MPESA CALLBACK
# -------------------------



@csrf_exempt
def mpesa_callback(request):
    if request.method != "POST":
        return JsonResponse({"ResultCode": 1, "ResultDesc": "Invalid method"}, status=400)

    try:
        data = json.loads(request.body.decode("utf-8"))
        print("🔥 CALLBACK RECEIVED:", data)

        callback = data.get("Body", {}).get("stkCallback", {})
        checkout_id = callback.get("CheckoutRequestID")
        result_code = callback.get("ResultCode")
        result_desc = callback.get("ResultDesc")

        if not checkout_id:
            print("❌ Missing CheckoutRequestID")
            return JsonResponse({"ResultCode": 0, "ResultDesc": "No checkout id"})

        with db_transaction.atomic():
            try:
                tx = Transaction.objects.select_for_update().get(checkout_id=checkout_id)
            except Transaction.DoesNotExist:
                print("❌ Transaction not found:", checkout_id)
                return JsonResponse({"ResultCode": 0, "ResultDesc": "Transaction not found"})

            # 🔒 Prevent double processing
            if tx.status == "completed":
                print("⚠ Already processed:", checkout_id)
                return JsonResponse({"ResultCode": 0, "ResultDesc": "Already processed"})

            # =========================
            # SUCCESS PAYMENT
            # =========================
            if result_code == 0:
                metadata = callback.get("CallbackMetadata", {}).get("Item", [])

                mpesa_receipt = None
                phone = None

                for item in metadata:
                    name = item.get("Name")
                    if name == "MpesaReceiptNumber":
                        mpesa_receipt = item.get("Value")
                    elif name == "PhoneNumber":
                        phone = item.get("Value")

                # Update transaction
                tx.status = "completed"
                tx.mpesa_code = mpesa_receipt
                tx.phone_number = phone
                tx.result_desc = result_desc
                tx.completed_at = timezone.now()
                tx.save()

                # 💰 POST TO LEDGER (ONLY ONCE)
                CompanyAccount.post_transaction(tx)

                print("✅ PAYMENT COMPLETED:", checkout_id)

            # =========================
            # FAILED PAYMENT
            # =========================
            else:
                tx.status = "failed"
                tx.result_desc = result_desc
                tx.completed_at = timezone.now()
                tx.save(update_fields=["status", "result_desc", "completed_at"])

                print("❌ PAYMENT FAILED:", checkout_id)

        return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})

    except Exception as e:
        print("🔥 CALLBACK ERROR:", str(e))
        return JsonResponse({"ResultCode": 1, "ResultDesc": str(e)}, status=500)



    

@profile_required
@login_required
def invest(request):
    wallet, _ = Wallet.objects.get_or_create(user=request.user)
    

    pin_obj = getattr(request.user, "transaction_pin", None)
    if not pin_obj:
        messages.error(request, "Set PIN first")
        return redirect("user:profile")

    if request.method == "POST":

        amount = Decimal(request.POST.get("amount"))
        pin = request.POST.get("pin", "").strip()

        # 🔴 ADD THIS HERE (BEFORE ANY DATABASE ACTION)
        checkout_id = request.POST.get("checkout_id") or str(uuid.uuid4())
        if Transaction.objects.filter(
            user=request.user,
            tx_type="invest",
            checkout_id=checkout_id
        ).exists():
            messages.error(request, "Duplicate investment blocked")
            return redirect("finance:invest")

        if amount < 1:
            messages.error(request, "Min KES 100")
            return redirect("finance:invest")

        if amount > get_wallet_balance(request.user):
            messages.error(request, "Insufficient balance")
            return redirect("finance:invest")

        if not pin_obj.check_pin(pin):
            messages.error(request, "Invalid PIN")
            return redirect("finance:invest")


        
        with transaction.atomic():

            reserve = CompanyAccount.objects.select_for_update().get(account_type="reserve")
            pool = CompanyAccount.objects.select_for_update().get(account_type="pool")

            # ✅ WALLET DEBIT (THIS REDUCES BALANCE)
            LedgerEntry.objects.create(
                user=request.user,
                account=reserve,   # 🔥 REQUIRED
                tx_type="invest",
                amount=amount,
                is_credit=False
            )

            # ✅ MOVE TO POOL (SYSTEM SIDE)
            LedgerEntry.objects.create(
                user=None,         # 🔥 IMPORTANT: not user wallet
                account=pool,
                tx_type="invest",
                amount=amount,
                is_credit=True
            )
                    

            # 4. INVESTMENT RECORD
            InvestmentTracking.objects.create(
                user=request.user,
                amount=amount,
                interest_rate=Decimal("0.005")
            )

            # 5. TRANSACTION HISTORY
            Transaction.objects.create(
                user=request.user,
                amount=amount,
                tx_type="invest",
                status="completed",
                checkout_id=checkout_id
            )

        messages.success(request, "Investment successful")
        return redirect("finance:invest_tracking")

    return render(request, "finance/invest_form.html", {
        "wallet": wallet,
        "wallet_balance": get_wallet_balance(request.user)
    })

@login_required
def invest_tracking(request):
    wallet= Wallet.objects.get_or_create(user=request.user)

    investments = InvestmentTracking.objects.filter(user=request.user)
    now = timezone.now()

    for inv in investments:
        elapsed = (now - inv.invested_at).total_seconds()

        # 🔥 AUTO REDEEM SAFELY
        if elapsed >= 24 * 3600 and not inv.is_redeemed:
            process_maturity(request.user, inv)

        # 🔥 CALCULATE (DISPLAY ONLY)
        inv.interest_display = inv.interest_rate * 100
        inv.profit = inv.amount * inv.interest_rate
        inv.total = inv.amount + inv.profit

        # 🔥 STATUS
        if inv.is_redeemed:
            inv.status = "Redeemed"
        elif elapsed >= 24 * 3600:
            inv.status = "Matured"
        else:
            inv.status = "Active"

    # 🔥 ACTIVE ONLY
    current_investment = sum(
        inv.amount for inv in investments if not inv.is_redeemed
    )

    total_profit = sum(
        inv.profit for inv in investments if not inv.is_redeemed
    )

    return render(request, "finance/invest_tracking.html", {
        "wallet_balance": get_wallet_balance(request.user),
        "current_investment": current_investment,
        "investments": investments,   # 🔥 ADD THIS
    })



@login_required
def transactions(request):
    user = request.user
    transactions = Transaction.objects.filter(user=user).order_by('-timestamp')
    return render(request, 'finance/transactions.html', {'transactions': transactions})







@login_required
def referrals(request):
    user = request.user

    domain = get_current_site(request).domain
    referral_link = f"https://{domain}/register/?ref={user.referral_code}"

    referred_users = user.referrals.all()

    referred_users_data = []
    total_earnings = Decimal("0.00")

    for ref_user in referred_users:

        first_deposit = Transaction.objects.filter(
            user=ref_user,
            tx_type__iexact="deposit",
            status__iexact="completed"
        ).order_by('timestamp').first()

        bonus = Decimal("0.00")

        if first_deposit:
            bonus = (first_deposit.amount * Decimal("0.10")).quantize(
                Decimal("0.01")
            )

        referred_users_data.append({
            "username": ref_user.username,
            "date_joined": ref_user.date_joined,
            "status": ref_user.is_active,
            "first_deposit": first_deposit.amount if first_deposit else None,
            "bonus": bonus
        })

    wallet, _ = Wallet.objects.get_or_create(user=user)

    return render(request, "finance/referrals.html", {
        "referral_link": referral_link,
        "referred_users": referred_users_data,
        "total_earnings": total_earnings
    })


  # your B2C helper function

# finance/views.py
MIN_WITHDRAWAL_AMOUNT = Decimal("1.00")  # Minimum withdrawal allowed


from decimal import Decimal
from django.db import transaction
from django.shortcuts import render, redirect
from django.contrib import messages
from django.utils import timezone
from django.contrib.auth.decorators import login_required

@login_required
def withdraw(request):
    wallet = Wallet.objects.get(user=request.user)

    if request.method == "POST":
        amount = Decimal(request.POST["amount"])
        pin = request.POST["pin"]

        # PIN check
        try:
            pin_obj = TransactionPIN.objects.get(user=request.user)
        except TransactionPIN.DoesNotExist:
            messages.error(request, "No transaction PIN set")
            return redirect("finance:withdraw")

        if not pin_obj.check_pin(pin):
            messages.error(request, "Wrong PIN")
            return redirect("finance:withdraw")

        # balance check (READ ONLY property)
        if get_wallet_balance(request.user) < amount:
            messages.error(request, "Insufficient balance")
            return redirect("finance:withdraw")

        reserve = CompanyAccount.objects.get(account_type="reserve")

        with transaction.atomic():

            # ✅ ONLY ONE ledger entry (withdraw request / liability)
            LedgerEntry.objects.create(
                user=request.user,
                account=reserve,
                phone_number=request.user.phone,
                tx_type="withdraw",
                amount=amount,
                is_credit=False,  # IMPORTANT: withdrawal reduces user equity
                reference=f"WD-{timezone.now().timestamp()}",
                metadata="Pending withdrawal"
            )

                # 2. ✅ CREATE TRANSACTION HISTORY
            Transaction.objects.create(
                user=request.user,
                tx_type="withdraw",
                amount=amount,
                status="pending"
            )

        messages.success(request, "Withdrawal submitted (pending approval)")
        return redirect("finance:transactions")

    return render(request, "finance/withdraw.html", {"wallet": wallet})

# ----------------------- MANUAL WITHDRAWAL COMPLETION -----------------------
@login_required
def mark_withdrawal_completed(request, tx_id):

    entry = LedgerEntry.objects.select_related("account").get(id=tx_id)

    if entry.tx_type != "withdraw":
        return redirect("finance:admin_withdrawals")

    if entry.metadata != "Pending withdrawal":
        messages.error(request, "Already processed")
        return redirect("finance:admin_withdrawals")

    reserve_account = entry.account

    with transaction.atomic():

        # 1. Reduce reserve liability
        LedgerEntry.objects.create(
            user=entry.user,
            account=reserve_account,
            tx_type="withdraw",
            amount=entry.amount,
            is_credit=False,   # clearing liability
            reference=entry.reference,
            metadata="Withdrawal completed (paid via M-Pesa)"
        )

        # 2. Mark original entry
        entry.metadata = "Completed"
        entry.save()

    messages.success(request, "Withdrawal completed")
    return redirect("finance:admin_withdrawals")

# ----------------------- OPTIONAL: ADMIN REJECT -----------------------
def reject_withdrawal(ledger_id):
    ledger = LedgerEntry.objects.get(id=ledger_id)

    wallet = Wallet.objects.get(user=ledger.user)

    # refund
    
    wallet.save()

    ledger.metadata = "Rejected and refunded"
    ledger.save()






