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
from finance.b2c_utils import send_b2c_payment
from django.contrib.sites.shortcuts import get_current_site
from user.utils import process_maturity
from .stkpush import stk_push
from user.decorators import profile_required
from finance.models import LedgerEntry



PUBLIC_URL = "https://ghostlier-cloudily-coleman.ngrok-free.dev"




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


MIN_DEPOSIT = 5  # Minimum deposit amount in KSh

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
                "balance": wallet.balance,
                "message": {"title": "Error", "body": "Invalid amount"}
            })

        if amount < MIN_DEPOSIT:
            return render(request, "finance/deposit.html", {
                "balance": wallet.balance,
                "message": {"title": "Error", "body": f"Minimum deposit is KES {MIN_DEPOSIT}"}
            })

        # -----------------------------
        # VALIDATE METHOD
        # -----------------------------
        if method != "mpesa":
            return render(request, "finance/deposit.html", {
                "balance": wallet.balance,
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
                "balance": wallet.balance,
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
            phone_number=phone,
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
        "balance": wallet.balance
    })


# -------------------------
# MPESA CALLBACK
# -------------------------
from django.db import transaction as db_transaction

@csrf_exempt
def mpesa_callback(request):
    if request.method != "POST":
        return JsonResponse({"ResultCode": 1, "ResultDesc": "Invalid request"}, status=400)

    try:
        data = json.loads(request.body)
        callback_data = data.get("Body", {}).get("stkCallback", {})

        checkout_id = callback_data.get("CheckoutRequestID")
        result_code = callback_data.get("ResultCode")
        result_desc = callback_data.get("ResultDesc")

        print("🔔 CALLBACK RECEIVED - Checkout ID:", checkout_id)

        with db_transaction.atomic():
            try:
                # 🔒 LOCK ROW (IMPORTANT)
                tx = Transaction.objects.select_for_update().get(checkout_id=checkout_id)
            except Transaction.DoesNotExist:
                return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})

            # ✅ SAFE CHECK AFTER LOCK
            if tx.status == "completed":
                print("✅ Already processed:", checkout_id)
                return JsonResponse({"ResultCode": 0, "ResultDesc": "Already processed"})

            if result_code == 0:
                metadata = callback_data.get("CallbackMetadata", {}).get("Item", [])

                mpesa_receipt = None
                mpesa_phone = None

                for item in metadata:
                    if item.get("Name") == "MpesaReceiptNumber":
                        mpesa_receipt = item.get("Value")
                    elif item.get("Name") == "PhoneNumber":
                        mpesa_phone = item.get("Value")

                # ✅ Update transaction FIRST
                tx.mpesa_code = mpesa_receipt
                tx.phone_number = mpesa_phone
                tx.status = "completed"
                tx.result_desc = result_desc
                tx.completed_at = timezone.now()
                tx.save()

                # 🔥 POST TO LEDGER ONCE
                CompanyAccount.post_transaction(tx)

                print("✅ Transaction completed:", checkout_id)

            else:
                tx.status = "failed"
                tx.result_desc = result_desc
                tx.completed_at = timezone.now()
                tx.save(update_fields=["status", "result_desc", "completed_at"])

                print("❌ Transaction failed:", checkout_id)

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

        if amount < 3:
            messages.error(request, "Min KES 100")
            return redirect("finance:invest")

        if amount > wallet.balance:
            messages.error(request, "Insufficient balance")
            return redirect("finance:invest")

        if not pin_obj.check_pin(pin):
            messages.error(request, "Invalid PIN")
            return redirect("finance:invest")

        reserve = CompanyAccount.objects.select_for_update().get(account_type="reserve")
        pool = CompanyAccount.objects.select_for_update().get(account_type="pool")

        with transaction.atomic():

            # 1. wallet deduction
            LedgerEntry.objects.create(
                user=request.user,
                account=reserve,   # Or link to reserve account if you want
                tx_type="invest",
                amount=amount,
                is_credit=False
            )

            # 2. pool analytics only
            pool.invested_today += amount
            pool.save()

            # 4. investment record
            inv = InvestmentTracking.objects.create(
                user=request.user,
                amount=amount,
                interest_rate=Decimal("0.005")
            )

            # 5. USER HISTORY
            Transaction.objects.create(
                user=request.user,
                amount=amount,
                tx_type="invest",
                status="completed",
                checkout_id=str(uuid.uuid4())
            )

        messages.success(request, "Investment successful")
        return redirect("finance:invest_tracking")

    return render(request, "finance/invest_form.html", {"wallet": wallet})



@login_required
def invest_tracking(request):
    wallet, _ = Wallet.objects.get_or_create(user=request.user)

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
        "wallet": wallet,
        "investments": investments,
        "current_investment": current_investment,
        "total_profit": total_profit,
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

MIN_WITHDRAWAL_AMOUNT = Decimal("3.00")  # Minimum withdrawal: 50 KSh

@profile_required
@login_required
def withdraw(request):
    wallet, _ = Wallet.objects.get_or_create(user=request.user)
    reserve_account = CompanyAccount.objects.get(account_type="reserve")
    user=request.user
  

    if request.method == "POST":
        amount = Decimal(request.POST.get("amount"))
        pin = request.POST.get("pin")

        if amount > wallet.balance():
            messages.error(request, "Insufficient balance")
            return redirect("finance:withdraw")

        if amount > reserve_account.system_balance:
            messages.error(request, "Insufficient liquidity")
            return redirect("finance:withdraw")

        with transaction.atomic():

            # 1. wallet update
            wallet.balance -= amount
            wallet.save()

            # 2. reserve freeze removed
            reserve_account.system_balance -= amount
            reserve_account.save()



            # 4. transaction record
            tx = Transaction.objects.create(
                user=request.user,
                amount=amount,
                tx_type="withdraw",
                status="processing",
                checkout_id=str(uuid.uuid4())
            )

        messages.success(request, "Withdrawal processing")
        return redirect("finance:transactions")

    return render(request, "finance/withdraw.html", {"wallet": wallet})


# ----------------------- B2C CALLBACK -----------------------
@csrf_exempt
def b2c_result(request):
    """
    Handles B2C responses from M-Pesa.
    Wallet is deducted only on successful withdrawals.
    """
    try:
        data = json.loads(request.body)
        result = data.get("Result", {})
        conversation_id = result.get("ConversationID")
        result_code = result.get("ResultCode")
        result_desc = result.get("ResultDesc")

        # Lookup transaction by conversation_id
        tx = Transaction.objects.filter(conversation_id=conversation_id).first()
        if not tx:
            print(f"No transaction found for ConversationID {conversation_id}")
            return JsonResponse({"Result": "Accepted"})

        # Save result info
        tx.result_desc = result_desc
        tx.completed_at = timezone.now()

        wallet, _ = Wallet.objects.get_or_create(user=tx.user)
        liquidity_account, _ = CompanyAccount.objects.get_or_create(
            account_type="liquidity",
            defaults={'name': 'Reserve', 'balance': 0}
        )

        if result_code == 0:
            # Withdrawal successful
            tx.status = "completed"
            if tx.tx_type == "withdraw":
                wallet.balance -= Decimal(tx.amount)
                wallet.save()
                liquidity_account.withdraw(Decimal(tx.amount))
            print(f"Withdrawal completed for user {tx.user.username}, amount {tx.amount}")
        else:
            # Withdrawal failed
            tx.status = "failed"
            print(f"Withdrawal failed for user {tx.user.username}: {result_desc}")

        tx.save()
        return JsonResponse({"Result": "Accepted"})

    except Exception as e:
        print("B2C callback error:", str(e))
        return JsonResponse({"Result": "Failed", "Error": str(e)}, status=500)


@csrf_exempt
def b2c_timeout(request):
    """
    Handles B2C timeout notifications from M-Pesa.
    """
    try:
        data = json.loads(request.body)
        print("B2C Timeout received:", data)
        return JsonResponse({"Result": "Timeout received"})
    except Exception as e:
        print("B2C Timeout error:", str(e))
        return JsonResponse({"Result": "Failed", "Error": str(e)}, status=500)






