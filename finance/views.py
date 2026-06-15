from django.shortcuts import redirect, render
from .forms import  TransactionPIN, PINForm
from .accesstoken import get_access_token_value
import base64
import requests
from finance.models import (
    INVESTMENT_DAILY_INTEREST_RATE,
    INVESTMENT_LOCK_DAYS,
    Transaction,
    Wallet,
    InvestmentTracking,
    CompanyAccount,
)
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
from user.utils import mature_due_investments
from .stkpush import stk_push
from user.decorators import profile_required
from finance.models import LedgerEntry



PUBLIC_URL = " https://ghostlier-cloudily-coleman.ngrok-free.dev"




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


MIN_DEPOSIT = Decimal("2500.00")  # Minimum deposit amount in KSh
MIN_INVESTMENT = Decimal("2500.00")  # Minimum investment amount in KSh
MIN_DEPOSIT_LABEL = "KES 2,500"
MIN_INVESTMENT_LABEL = "KES 2,500"

@login_required
def deposit(request):
    mature_due_investments(request.user)
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
                "message": {"title": "Error", "body": f"Minimum deposit is {MIN_DEPOSIT_LABEL}"}
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
    mature_due_investments(request.user)
    wallet, _ = Wallet.objects.get_or_create(user=request.user)

    pin_obj = getattr(request.user, "transaction_pin", None)
    if not pin_obj:
        messages.error(request, "Set PIN first")
        return redirect("user:profile")

    if request.method == "POST":
        try:
            amount = Decimal(request.POST.get("amount"))
        except (InvalidOperation, TypeError, ValueError):
            messages.error(request, "Invalid amount")
            return redirect("finance:invest")
        pin = request.POST.get("pin", "").strip()

        if amount < MIN_INVESTMENT:
            messages.error(request, f"Minimum investment is {MIN_INVESTMENT_LABEL}")
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
                interest_rate=INVESTMENT_DAILY_INTEREST_RATE
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
    mature_due_investments(request.user)
    wallet, _ = Wallet.objects.get_or_create(user=request.user)

    investments = InvestmentTracking.objects.filter(user=request.user)
    now = timezone.now()

    for inv in investments:
        elapsed = (now - inv.invested_at).total_seconds()

        # 🔥 CALCULATE (DISPLAY ONLY)
        inv.interest_display = inv.interest_rate * 100
        inv.profit = inv.calculate_profit()
        inv.weekly_profit = inv.profit * INVESTMENT_LOCK_DAYS
        inv.total = inv.amount + inv.weekly_profit

        # 🔥 STATUS
        if inv.is_redeemed:
            inv.status = "Principal returned"
        elif inv.is_matured():
            inv.status = "Principal due"
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
    mature_due_investments(user)
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
MIN_WITHDRAWAL_AMOUNT = Decimal("50.00")  # Minimum withdrawal allowed
MIN_WITHDRAWAL_LABEL = "KES 50"

@profile_required
@login_required
def withdraw(request):

    mature_due_investments(request.user)
    wallet = Wallet.objects.get(user=request.user)
    if request.method == "POST":

        amount = request.POST.get("amount")
        pin = request.POST.get("pin")

        # -----------------------
        # VALIDATE AMOUNT
        # -----------------------
        try:
            amount = Decimal(amount)
        except:
            messages.error(request, "Invalid amount")
            return redirect("finance:withdraw")

        # -----------------------
        # PIN CHECK
        # -----------------------
        try:
            user_pin = request.user.transaction_pin
        except TransactionPIN.DoesNotExist:
            messages.error(request, "Please set up a transaction PIN first")
            return redirect("finance:withdraw")

        if not user_pin.check_pin(pin):
            messages.error(request, "Incorrect PIN")
            return redirect("finance:withdraw")

        # -----------------------
        # VALIDATION RULES
        # -----------------------
        if amount <= 0:
            messages.error(request, "Invalid amount")
            return redirect("finance:withdraw")

        if amount < MIN_WITHDRAWAL_AMOUNT:
            messages.error(request, f"Minimum withdrawal is {MIN_WITHDRAWAL_LABEL}")
            return redirect("finance:withdraw")

        # IMPORTANT:
        # wallet.balance MUST be computed from ledger (property)
        if amount > wallet.balance:
            messages.error(request, "Insufficient balance")
            return redirect("finance:withdraw")

        # -----------------------
        # LEDGER TRANSACTION (CORE LOGIC)
        # -----------------------
        try:
            with transaction.atomic():

                wallet = Wallet.objects.select_for_update().get(user=request.user)
                reserve_account = CompanyAccount.objects.select_for_update().get(account_type="reserve")

                # FINAL SAFETY CHECK
                if amount > wallet.balance:
                    messages.error(request, "Insufficient balance")
                    return redirect("finance:withdraw")

                # 🔥 LEDGER DEBIT (NO wallet update)
                checkout_id = str(uuid.uuid4())

                tx = Transaction.objects.create(
                    user=request.user,
                    amount=amount,
                    tx_type="withdraw",
                    status="pending",
                    checkout_id=checkout_id,
                    phone_number=getattr(request.user, "phone", None),
                    result_desc=f"Withdrawal request of KES {amount} submitted"
                )

                LedgerEntry.objects.create(
                    user=request.user,
                    account=reserve_account,
                    tx_type="withdraw",
                    amount=amount,
                    is_credit=False,
                    reference=checkout_id,
                    metadata=tx.result_desc,
                )

                messages.success(
                    request,
                    "Withdrawal request submitted successfully. Awaiting admin approval."
                )

                return redirect("finance:transactions")

        except Exception as e:
            print("Withdraw error:", str(e))
            messages.error(request, "Something went wrong. Try again.")
            return redirect("finance:withdraw")

    return render(request, "finance/withdraw.html", {"wallet": wallet})


# ----------------------- MANUAL WITHDRAWAL COMPLETION -----------------------
@login_required
def mark_withdrawal_completed(request, tx_id):
    tx = Transaction.objects.get(id=tx_id, tx_type="withdraw")

    if tx.status != "pending":
        messages.error(request, "Transaction already processed")
        return redirect("finance:admin_withdrawals")

    tx.status = "completed"
    tx.completed_at = timezone.now()
    tx.result_desc = "Paid manually via M-Pesa Till/Paybill"
    tx.save()

    messages.success(request, "Withdrawal marked as completed")
    return redirect("finance:admin_withdrawals")


# ----------------------- OPTIONAL: ADMIN REJECT -----------------------
@login_required
def reject_withdrawal(request, tx_id):
    tx = Transaction.objects.get(id=tx_id, tx_type="withdraw")

    if tx.status != "pending":
        messages.error(request, "Transaction already processed")
        return redirect("finance:admin_withdrawals")

    tx.status = "failed"
    tx.result_desc = "Withdrawal rejected"
    tx.save()

    messages.success(request, "Withdrawal rejected")
    return redirect("finance:admin_withdrawals")






