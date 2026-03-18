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


from decimal import Decimal
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.utils import timezone
from .models import Wallet, Transaction
from .accesstoken import get_access_token_value
import base64
import requests

MIN_DEPOSIT = 100  # Minimum deposit amount in KSh

@login_required
def deposit(request):
    wallet, _ = Wallet.objects.get_or_create(user=request.user)
    message = None

    if request.method == "POST":
        phone = request.POST.get("phone")
        amount = request.POST.get("amount")
        method = request.POST.get("method")

        # Validate amount
        try:
            amount = Decimal(amount)
        except (ValueError, TypeError, InvalidOperation):
            message = {"title": "Error", "body": "Invalid amount entered."}
            return render(request, "finance/deposit.html", {"balance": wallet.balance, "message": message})

        if amount < MIN_DEPOSIT:
            message = {"title": "Error", "body": f"Minimum deposit is KSh {MIN_DEPOSIT}."}
            return render(request, "finance/deposit.html", {"balance": wallet.balance, "message": message})

        # Only M-Pesa deposits supported
        if method != "mpesa":
            message = {"title": "Error", "body": "Only M-Pesa deposits are supported."}
            return render(request, "finance/deposit.html", {"balance": wallet.balance, "message": message})

        # Get access token
        access_token = get_access_token_value()
        if not access_token:
            message = {"title": "Error", "body": "Could not get access token."}
            return render(request, "finance/deposit.html", {"balance": wallet.balance, "message": message})

        # M-Pesa STK Push setup
        business_shortcode = "174379"
        passkey = "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919"
        callback_url = f"{PUBLIC_URL}/finance/callback/"
        timestamp = timezone.now().strftime("%Y%m%d%H%M%S")
        password_str = business_shortcode + passkey + timestamp
        password = base64.b64encode(password_str.encode()).decode("utf-8")

        payload = {
            "BusinessShortCode": business_shortcode,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": float(amount),  # STK Push expects float/int
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
                # Create transaction in DB
                Transaction.objects.create(
                    user=request.user,
                    amount=amount,
                    checkout_id=checkout_id,
                    tx_type="Deposit",
                    status="pending",
                )
                # Save checkout info in session (optional)
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

        print("STK Callback received:", json.dumps(data))

        # Lookup transaction
        try:
            tx = Transaction.objects.get(checkout_id=checkout_id)
        except Transaction.DoesNotExist:
            print(f"No transaction found for CheckoutRequestID: {checkout_id}")
            return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})

        if result_code == 0:
            tx.status = "completed"

            # Update user's wallet
            wallet, _ = Wallet.objects.get_or_create(user=tx.user)
            wallet.balance = Decimal(wallet.balance) + Decimal(tx.amount)
            wallet.save()

            # Update liquidity account
            liquidity_account, _ = CompanyAccount.objects.get_or_create(
                account_type="liquidity",
                defaults={'name': 'Reserve', 'balance': 0}
            )
            liquidity_account.balance = Decimal(liquidity_account.balance) + Decimal(tx.amount)
            liquidity_account.save()

            print(f"Wallet updated: {tx.user.username} new balance: {wallet.balance}")
            print(f"Liquidity account updated: new balance: {liquidity_account.balance}")

            # 🔥 REFERRAL BONUS LOGIC
            user = tx.user
            # Check if this is the FIRST successful deposit
            previous_deposits = Transaction.objects.filter(
                user=user,
                tx_type="Deposit",
                status="completed"
            ).exclude(id=tx.id)

            is_first = not previous_deposits.exists()

            if is_first and user.referred_by:
                bonus = Decimal(tx.amount) * Decimal("0.10")  # 10% of deposit
                ref_wallet, _ = Wallet.objects.get_or_create(user=user.referred_by)
                ref_wallet.balance = Decimal(ref_wallet.balance) + bonus
                ref_wallet.save()
                print(f"Referral bonus of {bonus} credited to {user.referred_by.username}")

        else:
            tx.status = "failed"

        tx.result_desc = result_desc
        tx.completed_at = timezone.now()
        tx.save()

        return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})

    except Exception as e:
        print("Error in MPESA callback:", str(e))
        return JsonResponse({"ResultCode": 1, "ResultDesc": str(e)}, status=500)



@login_required
def invest(request):
    # Check if user has a transaction PIN
    if not hasattr(request.user, 'transaction_pin'):
        messages.info(request, "You must set a transaction PIN before investing.")
        return redirect("user:profile")  # redirect to profile to set PIN

    wallet = Wallet.objects.get(user=request.user)
    pool_account = CompanyAccount.objects.get(account_type="investment_pool")
    error = None

    if request.method == "POST":
        amount = request.POST.get("amount")
        pin = request.POST.get("pin", "").strip()

        # Validate amount
        try:
            amount = Decimal(amount)
            if amount <= 0:
                raise ValueError
        except (TypeError, ValueError):
            error = "Invalid amount entered."
            return render(request, "finance/invest_form.html", {"wallet": wallet, "error": error})

        # Get transaction PIN object
        pin_obj = getattr(request.user, "transaction_pin", None)
        if not pin_obj:
            error = "Please set a transaction PIN first."
        elif not pin_obj.check_pin(pin):
            error = "Invalid transaction PIN!"
        elif wallet.balance < amount:
            error = "Insufficient wallet balance."

        if error:
            return render(request, "finance/invest_form.html", {"wallet": wallet, "error": error})

        # Deduct wallet balance
        wallet.balance -= amount
        wallet.save()

        # Investment pool balance (tracks virtual funds only)
        pool_account.balance = Decimal(pool_account.balance) + amount
        pool_account.save()

        # Track investment
        InvestmentTracking.objects.create(
            user=request.user,
            amount=amount,
            interest_rate=0.005
        )

        # Log transaction
        Transaction.objects.create(
            user=request.user,
            amount=amount,
            tx_type="invest",
            status="completed",
            checkout_id=str(uuid.uuid4()),
            timestamp=timezone.now()
        )

        messages.success(request, f"Invested KES {amount} successfully!")
        return redirect("finance:invest_tracking")

    return render(request, "finance/invest_form.html", {"wallet": wallet, "error": error})



from decimal import Decimal
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone
from .models import Wallet, InvestmentTracking

@login_required
def invest_tracking(request):
    wallet, _ = Wallet.objects.get_or_create(user=request.user)

    # Get all investments, newest first
    investments = InvestmentTracking.objects.filter(user=request.user).order_by('-invested_at')

    now = timezone.now()

    for inv in investments:
        # Profit and total
        inv.profit = Decimal(inv.calculate_profit())
        inv.total = Decimal(inv.total_return())

        # Determine matured: after 24 hours from invested_at
        elapsed_hours = (now - inv.invested_at).total_seconds() / 3600
        inv.is_matured_flag = elapsed_hours >= 24

        # Determine status string
        if inv.is_redeemed:
            inv.status = "Redeemed"
        elif inv.is_matured_flag:
            inv.status = "Matured"
        else:
            inv.status = "Active"

        # Interest display: for UI
        inv.interest_display = round(inv.interest_rate * 100, 2)  # e.g., 0.005 -> 0.50%

    # Current investment = sum of active amounts
    current_investment = sum(inv.amount for inv in investments if not inv.is_redeemed)

    # Total profit of matured but not redeemed investments
    total_profit = sum(inv.profit for inv in investments if inv.is_matured_flag and not inv.is_redeemed)

    context = {
        "wallet": wallet,
        "investments": investments,
        "current_investment": Decimal(current_investment),
        "total_profit": total_profit,
    }

    return render(request, "finance/invest_tracking.html", context)


@login_required
def redeem_matured_investments(request):
    wallet, _ = Wallet.objects.get_or_create(user=request.user)
    pool_account = CompanyAccount.objects.get(account_type="investment_pool")

    # Get investments that are not yet redeemed
    investments = InvestmentTracking.objects.filter(
        user=request.user,
        is_redeemed=False
    )

    redeemed = []
    skipped = []

    # Wrap in atomic transaction for safety
    with transaction.atomic():
        for inv in investments:
            # Check if investment has matured (24 hours)
            if (timezone.now() - inv.invested_at).total_seconds() >= 24*3600:
                # Calculate profit and total
                inv.profit = inv.amount * inv.interest_rate
                inv.total = inv.amount + inv.profit

                # Update wallet
                wallet.balance += inv.total

                # Deduct principal from pool account
                pool_account.balance -= inv.amount

                # Mark as redeemed
                inv.is_redeemed = True
                inv.save()

                redeemed.append(inv)
            else:
                skipped.append(inv)

        # Save balances
        wallet.save()
        pool_account.save()

    # Messages for user
    if redeemed:
        messages.success(
            request,
            f"{len(redeemed)} investment(s) redeemed successfully."
        )
    else:
        messages.info(request, "No matured investments yet.")

    if skipped:
        messages.warning(
            request,
            f"{len(skipped)} investment(s) not yet matured."
        )

    return redirect('finance:invest_tracking')

@login_required
def clear_redeemed_session(request):
    if 'redeemed_list' in request.session:
        del request.session['redeemed_list']
    return HttpResponse("OK")


@login_required
def transactions(request):
    user = request.user
    transactions = Transaction.objects.filter(user=user).order_by('-timestamp')
    return render(request, 'finance/transactions.html', {'transactions': transactions})



@login_required
def referrals(request):
    user = request.user

    # Referral link
    referral_link = f"http://127.0.0.1:8000/register/?ref={user.referral_code}"

    # All users referred by this user
    referred_users = user.referrals.all()

    # Calculate referral earnings per referred user
    referred_users_data = []
    total_earnings = Decimal('0.00')  # Use Decimal for money

    for ref_user in referred_users:
        # Referral bonus is 10% of their first deposit
        first_deposit = ref_user.transaction_set.filter(
            tx_type="Deposit",
            status="completed"
        ).first()

        bonus = Decimal('0.00')
        if first_deposit:
            bonus = (first_deposit.amount * Decimal('0.10')).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
            total_earnings += bonus

        referred_users_data.append({
            'username': ref_user.username,
            'date_joined': ref_user.date_joined,
            'status': ref_user.is_active,
            'bonus': bonus
        })

    # Update the logged-in user's wallet with total earnings
    wallet, _ = Wallet.objects.get_or_create(user=user)
    wallet.balance = total_earnings
    wallet.save()

    return render(request, 'finance/referrals.html', {
        'referral_link': referral_link,
        'referred_users': referred_users_data,
        'total_earnings': total_earnings
    })





  # your B2C helper function

MIN_WITHDRAWAL_AMOUNT = Decimal("50.00")  # Minimum withdrawal: 50 KSh

@login_required
def withdraw(request):
    # Ensure user has a transaction PIN
    if not hasattr(request.user, 'transaction_pin'):
        messages.info(request, "You must set a transaction PIN before withdrawing.")
        return redirect("user:profile")

    wallet = Wallet.objects.get(user=request.user)
    liquidity_account = CompanyAccount.objects.get(account_type="liquidity")

    if request.method == "POST":
        amount = request.POST.get("amount")
        pin = request.POST.get("pin", "").strip()
        error = None

        # Validate amount
        try:
            amount = Decimal(amount)
            if amount <= 0:
                error = "Amount must be greater than zero."
            elif amount < MIN_WITHDRAWAL_AMOUNT:
                error = f"Minimum withdrawal is KSh {MIN_WITHDRAWAL_AMOUNT}."
        except (TypeError, ValueError, InvalidOperation):
            error = "Invalid amount entered."

        # Validate transaction PIN
        pin_obj = getattr(request.user, "transaction_pin", None)
        if not pin_obj:
            error = "Please set a transaction PIN first."
        elif not pin:
            error = "Please enter your transaction PIN."
        elif not pin_obj.check_pin(pin):
            error = "Invalid transaction PIN!"
        elif amount > wallet.balance:
            error = "Insufficient wallet balance."
        elif amount > liquidity_account.balance:
            error = "Company reserve cannot cover this withdrawal."

        if error:
            messages.error(request, error)
            return redirect("finance:withdraw")

        # Ensure phone number exists
        if not getattr(request.user, "phone", None):
            messages.error(request, "Please add your phone number in your profile.")
            return redirect("user:profile")

        # Step 1: Create pending transaction
        tx = Transaction.objects.create(
            user=request.user,
            amount=amount,
            tx_type="withdraw",
            status="pending",
            checkout_id=str(uuid.uuid4()),
            phone_number=request.user.phone,
            timestamp=timezone.now()
        )

        # Step 2: Trigger B2C payout
        response = send_b2c_payment(
            phone_number=request.user.phone,
            amount=float(amount),
            remarks="Wallet Withdrawal",
            occasion="Withdrawal"
        )

        # Save response info and M-Pesa conversation IDs
        tx.result_desc = str(response)
        tx.conversation_id = response.get("conversation_id")
        tx.originator_conversation_id = response.get("originator_conversation_id")
        if response.get("ResponseCode") != "0":
            tx.status = "failed"
        tx.save()

        # User feedback
        if response.get("ResponseCode") == "0":
            messages.success(request, f"Withdrawal of KES {amount} is being processed via M-Pesa.")
        else:
            messages.warning(
                request,
                f"Withdrawal of KES {amount} failed to initiate: {response.get('errorMessage', response)}"
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






