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
from django.http import HttpResponse
from django.db import transaction
from django.db.models import Sum
from finance.b2c_utils import send_b2c_payment
from django.contrib.sites.shortcuts import get_current_site
from user.utils import process_maturity



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


MIN_DEPOSIT = 100  # Minimum deposit amount in KSh

@login_required
def deposit(request):
    wallet, _ = Wallet.objects.get_or_create(user=request.user)
    message = None

    if request.method == "POST":
        phone = request.POST.get("phone")
        amount = request.POST.get("amount")
        method = request.POST.get("method")

        try:
            amount = Decimal(amount)
        except (ValueError, TypeError, InvalidOperation):
            message = {"title": "Error", "body": "Invalid amount entered."}
            return render(request, "finance/deposit.html", {"balance": wallet.balance, "message": message})

        if amount < MIN_DEPOSIT:
            message = {"title": "Error", "body": f"Minimum deposit is KSh {MIN_DEPOSIT}."}
            return render(request, "finance/deposit.html", {"balance": wallet.balance, "message": message})

        if method != "mpesa":
            message = {"title": "Error", "body": "Only M-Pesa deposits are supported."}
            return render(request, "finance/deposit.html", {"balance": wallet.balance, "message": message})

        access_token = get_access_token_value()
        if not access_token:
            message = {"title": "Error", "body": "Could not get access token."}
            return render(request, "finance/deposit.html", {"balance": wallet.balance, "message": message})

        business_shortcode = "174379"
        passkey = "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919"

        timestamp = timezone.now().strftime("%Y%m%d%H%M%S")
        password_str = business_shortcode + passkey + timestamp
        password = base64.b64encode(password_str.encode()).decode("utf-8")

        callback_url = f"{PUBLIC_URL}/finance/callback/"

        payload = {
            "BusinessShortCode": business_shortcode,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": float(amount),
            "PartyA": phone.replace("+", ""),
            "PartyB": business_shortcode,
            "PhoneNumber": phone.replace("+", ""),
            "CallBackURL": callback_url,
            "AccountReference": "SMMF",
            "TransactionDesc": "Deposit",
        }

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(
                "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest",
                json=payload,
                headers=headers,
                timeout=30,
            )
            res_json = response.json()

            if res_json.get("ResponseCode") == "0":
                checkout_id = res_json.get("CheckoutRequestID")

                Transaction.objects.create(
                    user=request.user,
                    amount=amount,
                    checkout_id=checkout_id,
                    tx_type="deposit",   # ✅ FIXED
                    status="pending",
                )

                request.session["checkout_id"] = checkout_id
                request.session["checkout_start_time"] = timezone.now().timestamp()

                return redirect("finance:transactions")

            else:
                message = {"title": "Error", "body": res_json.get("errorMessage", "Unknown error")}

        except requests.RequestException as e:
            message = {"title": "Error", "body": str(e)}

    return render(request, "finance/deposit.html", {"balance": wallet.balance, "message": message})



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

        try:
            tx = Transaction.objects.get(checkout_id=checkout_id)
        except Transaction.DoesNotExist:
            return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})

        if result_code == 0:
            tx.status = "completed"

            wallet, _ = Wallet.objects.get_or_create(user=tx.user)
            wallet.balance += Decimal(tx.amount)
            wallet.save()

            liquidity_account, _ = CompanyAccount.objects.get_or_create(
                account_type="liquidity",
                defaults={"name": "Reserve", "balance": 0}
            )

            liquidity_account.balance += Decimal(tx.amount)
            liquidity_account.save()

            # ✅ FIXED referral filter (lowercase)
            user = tx.user

            previous_deposits = Transaction.objects.filter(
                user=user,
                tx_type="deposit",
                status="completed"
            ).exclude(id=tx.id)

            is_first = not previous_deposits.exists()

            if is_first and hasattr(user, "referred_by") and user.referred_by:
                bonus = Decimal(tx.amount) * Decimal("0.10")

                ref_wallet, _ = Wallet.objects.get_or_create(user=user.referred_by)
                ref_wallet.balance += bonus
                ref_wallet.save()

        else:
            tx.status = "failed"

        tx.result_desc = result_desc
        tx.completed_at = timezone.now()
        tx.save()

        return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})

    except Exception as e:
        return JsonResponse({"ResultCode": 1, "ResultDesc": str(e)}, status=500)



@login_required
def invest(request):
    wallet, _ = Wallet.objects.get_or_create(user=request.user)

    pin_obj = getattr(request.user, "transaction_pin", None)

    # 🚨 FIX: No PIN → redirect to profile
    if not pin_obj:
        messages.error(request, "Please set your transaction PIN first.")
        return redirect("user:profile")  # change if your profile url name is different

    if request.method == "POST":
        amount = request.POST.get("amount")
        pin = request.POST.get("pin", "").strip()

        try:
            amount = Decimal(amount)

            if amount < 100:
                messages.error(request, "Minimum investment is KES 100.")
                return redirect("finance:invest")

        except:
            messages.error(request, "Invalid amount entered.")
            return redirect("finance:invest")

        if amount > wallet.balance:
            messages.error(request, f"Insufficient balance. You have {wallet.balance}")
            return redirect("finance:invest")

        # 🔐 PIN check
        if not pin_obj.check_pin(pin):
            messages.error(request, "Invalid PIN")
            return redirect("finance:invest")

        pool_account = CompanyAccount.objects.get(account_type="investment_pool")

        # 💰 move money
        wallet.balance -= amount
        wallet.save()

        pool_account.balance += amount
        pool_account.save()

        # 📊 create investment
        InvestmentTracking.objects.create(
            user=request.user,
            amount=amount,
            interest_rate=Decimal("0.005")
        )

        # 🧾 transaction record
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

MIN_WITHDRAWAL_AMOUNT = Decimal("50.00")  # Minimum withdrawal: 50 KSh

@login_required
def withdraw(request):
    wallet, _ = Wallet.objects.get_or_create(user=request.user)
    liquidity_account = CompanyAccount.objects.get(account_type="liquidity")

    # =========================
    # ENFORCE PHONE NUMBER
    # =========================
    if not getattr(request.user, "phone", None):
        messages.info(request, "Please add your phone number in your profile before withdrawing.")
        return redirect("user:profile")

    # =========================
    # ENFORCE TRANSACTION PIN
    # =========================
    pin_obj = getattr(request.user, "transaction_pin", None)
    if not pin_obj:
        messages.info(request, "You must set a transaction PIN before withdrawing.")
        return redirect("user:profile")

    if request.method == "POST":
        amount = request.POST.get("amount")
        pin = request.POST.get("pin", "").strip()

        # =========================
        # VALIDATE AMOUNT
        # =========================
        try:
            amount = Decimal(amount)
            if amount <= 0:
                messages.error(request, "Amount must be greater than zero.")
                return redirect("finance:withdraw")
        except (TypeError, ValueError, InvalidOperation):
            messages.error(request, "Invalid amount entered.")
            return redirect("finance:withdraw")

        # =========================
        # VALIDATE PIN
        # =========================
        if not pin_obj.check_pin(pin):
            messages.error(request, "Invalid transaction PIN.")
            return redirect("finance:withdraw")

        # =========================
        # BALANCE CHECKS
        # =========================
        if amount > wallet.balance:
            messages.error(request, "Insufficient wallet balance.")
            return redirect("finance:withdraw")

        if amount > liquidity_account.balance:
            messages.error(request, "Company reserve cannot cover this withdrawal.")
            return redirect("finance:withdraw")

        # =========================
        # CREATE PENDING TRANSACTION
        # =========================
        tx = Transaction.objects.create(
            user=request.user,
            amount=amount,
            tx_type="withdraw",
            status="pending",
            checkout_id=str(uuid.uuid4()),
            phone_number=request.user.phone,
            timestamp=timezone.now()
        )

        # =========================
        # CALL M-PESA B2C
        # =========================
        response = send_b2c_payment(
            phone_number=request.user.phone,
            amount=float(amount),
            remarks="Wallet Withdrawal",
            occasion="Withdrawal"
        )

        # =========================
        # SAVE RESPONSE
        # =========================
        tx.result_desc = str(response)
        tx.conversation_id = response.get("conversation_id")
        tx.originator_conversation_id = response.get("originator_conversation_id")

        if response.get("ResponseCode") != "0":
            tx.status = "failed"

        tx.save()

        # =========================
        # USER FEEDBACK
        # =========================
        if response.get("ResponseCode") == "0":
            messages.success(request, f"Withdrawal of KES {amount} is being processed via M-Pesa.")
        else:
            messages.warning(
                request,
                f"Withdrawal failed: {response.get('errorMessage', response)}"
            )

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






