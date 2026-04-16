import datetime
from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, authenticate
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count
from finance.models import Transaction, Wallet
import plotly.graph_objects as go
from plotly.offline import plot
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View
from .forms import CustomUserCreationForm
from .forms import  ChangePINForm, SetNewPINForm, ForgotPINForm, TransactionPIN, VerifyOTPForm
from .models import TransactionPIN
from django.contrib import messages
import random
from .models import CustomUser
import time
from django.contrib.auth.hashers import make_password
import datetime
from decimal import Decimal
from django.shortcuts import render
from django.utils import timezone
from .utils import send_otp_email
from user.utils import get_wallet_balance
from django.utils import timezone
from .models import PasswordResetOTP
from django.db.models import Sum, Case, When, F, DecimalField
from finance.models import LedgerEntry

def register(request):

    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)

        # 🔥 Get ref from POST (NOT GET)
        ref_code = request.POST.get('ref')

        if form.is_valid():
            user = form.save(commit=False)

            if ref_code:
                try:
                    referrer = CustomUser.objects.get(referral_code=ref_code)
                    if referrer != user:
                        user.referred_by = referrer
                except CustomUser.DoesNotExist:
                    pass

            user.save()
            login(request, user)
            messages.success(request, f"Welcome, {user.username}! Your account was created.")
            return redirect('user:dashboard')

    else:
        form = CustomUserCreationForm()
        ref_code = request.GET.get('ref', '')  # only for first load

    return render(request, 'user/register.html', {
        'form': form,
        'ref_code_from_link': ref_code
    })


def login_view(request):
    error_message = None
    next_url = request.GET.get('next', '')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()
        next_url = request.POST.get('next') or next_url

        print(f"Trying login: {username!r} / {password!r}")  # Debug

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            print(f"Login successful: {user.username}")  # Debug
            return redirect(next_url or reverse('user:dashboard'))
        else:
            print("Login failed!")  # Debug
            error_message = 'Invalid credentials!'

    return render(request, 'user/login.html', {'error': error_message, 'next': next_url})

def logout_view(request):
    if request.method == 'POST':
        logout(request)
        return redirect('user:login')
    else:
        return redirect('home')
    
    import random
from django.core.mail import send_mail

def forgot_password(request):
    message = None

    if request.method == "POST":
        email = request.POST.get("email", "").strip()

        try:
            user = CustomUser.objects.get(email=email)
        except CustomUser.DoesNotExist:
            message = "Email not found. Please use your registered email."
            return render(request, "user/forgot_password.html", {"message": message})

        # Generate OTP
        otp = str(random.randint(100000, 999999))

        PasswordResetOTP.objects.create(user=user, otp=otp)

        # Send email
        send_mail(
            "Password Reset OTP",
            f"Your OTP code is: {otp}",
            "noreply@yourapp.com",
            [email],
            fail_silently=False,
        )

        request.session["reset_user_id"] = user.id
        return redirect("user:verify_otp")

    return render(request, "user/forgot_password.html", {"message": message})


def verify_otp(request):
    user_id = request.session.get("reset_user_id")

    if not user_id:
        return redirect("user:forgot_password")

    user = CustomUser.objects.get(id=user_id)

    if request.method == "POST":
        otp_input = request.POST.get("otp")

        otp_obj = PasswordResetOTP.objects.filter(
            user=user,
            otp=otp_input,
            is_used=False
        ).order_by('-created_at').first()

        if otp_obj and otp_obj.is_valid():
            otp_obj.is_used = True
            otp_obj.save()

            request.session["otp_verified"] = True
            return redirect("user:reset_password")

        return render(request, "user/verify_otp.html", {
            "error": "Invalid or expired OTP"
        })

    return render(request, "user/verify_otp.html")


from django.contrib.auth.hashers import make_password

def reset_password(request):
    if not request.session.get("otp_verified"):
        return redirect("user:forgot_password")

    user_id = request.session.get("reset_user_id")
    user = CustomUser.objects.get(id=user_id)

    if request.method == "POST":
        password1 = request.POST.get("password1")
        password2 = request.POST.get("password2")

        if password1 != password2:
            return render(request, "user/reset_password.html", {
                "error": "Passwords do not match"
            })

        user.password = make_password(password1)
        user.save()

        # cleanup session
        request.session.flush()

        return redirect("user:login")

    return render(request, "user/reset_password.html")






@login_required
def dashboard(request):
    user = request.user

    # =========================
    # 💰 REAL BALANCE (FROM LEDGER)
    # =========================
    wallet, _ = Wallet.objects.get_or_create(user=user)
    balance = LedgerEntry.objects.filter(
        user=user
    ).aggregate(
        total=Sum(
            Case(
                When(is_credit=True, then=F("amount")),
                When(is_credit=False, then=-F("amount")),
                output_field=DecimalField()
            )
        )
    )["total"] or Decimal("0")

    # =========================
    # 📌 TRANSACTIONS
    # =========================
    transactions = Transaction.objects.filter(user=user).order_by('-timestamp')[:10]

    # =========================
    # 📊 TOTALS
    # =========================
    total_deposits = Transaction.objects.filter(
        user=user,
        tx_type__iexact="deposit",
        status="completed"
    ).aggregate(total=Sum('amount'))['total'] or Decimal("0")

    total_withdrawals = Transaction.objects.filter(
        user=user,
        tx_type__iexact="withdraw",
        status="completed"
    ).aggregate(total=Sum('amount'))['total'] or Decimal("0")

    total_investments = Transaction.objects.filter(
        user=user,
        tx_type__iexact="invest",
        status="completed"
    ).aggregate(total=Sum('amount'))['total'] or Decimal("0")

    daily_profit = Transaction.objects.filter(
        user=user,
        tx_type__iexact="investment_return",  # ✅ FIXED
        timestamp__date=timezone.localdate(),
        status="completed"
    ).aggregate(total=Sum('amount'))['total'] or Decimal("0")

    # =========================
    # 📈 ACCOUNT GROWTH (LAST 7 DAYS)
    # =========================
    today = timezone.localdate()
    last_7_days = [today - datetime.timedelta(days=i) for i in range(6, -1, -1)]

    balance_by_day = []
    running_balance = Decimal("0")

    for day in last_7_days:
        deposits = Transaction.objects.filter(
            user=user,
            tx_type="deposit",
            status="completed",
            timestamp__date=day
        ).aggregate(total=Sum('amount'))['total'] or Decimal("0")

        withdrawals = Transaction.objects.filter(
            user=user,
            tx_type="withdraw",
            status="completed",
            timestamp__date=day
        ).aggregate(total=Sum('amount'))['total'] or Decimal("0")

        # 💰 wallet growth = deposits - withdrawals ONLY
        daily_net = deposits - withdrawals

        running_balance += daily_net
        balance_by_day.append(running_balance)

    # 🔥 Convert to cumulative balance
    cumulative = []
    running = Decimal("0")

    for value in balance_by_day:
        running += value
        cumulative.append(running)

    growth_chart = go.Figure()
    growth_chart.add_trace(go.Scatter(
        x=[d.strftime('%d %b') for d in last_7_days],
        y=cumulative,
        mode='lines+markers',
        name='Balance'
    ))

    growth_chart.update_layout(
        title='Account Growth (Last 7 Days)',
        xaxis_title='Date',
        yaxis_title='Balance (KSh)',
        template='plotly_dark',
        paper_bgcolor='#0b0f19',
        plot_bgcolor='#0b0f19',
        font=dict(color='white')
    )

    growth_plot = plot(growth_chart, output_type='div', include_plotlyjs=False)

    # =========================
    # 📊 STATUS CHART
    # =========================
    status_counts_qs = Transaction.objects.filter(user=user)\
        .values('status')\
        .annotate(count=Count('id'))

    labels = [i['status'].capitalize() for i in status_counts_qs] if status_counts_qs else ['No Data']
    values = [i['count'] for i in status_counts_qs] if status_counts_qs else [1]

    status_chart = go.Figure(data=[go.Pie(labels=labels, values=values, hole=0.3)])
    status_chart.update_layout(
        title='Transaction Status Overview',
        template='plotly_dark'
    )

    status_plot = plot(status_chart, output_type='div', include_plotlyjs=False)

    # =========================
    # 📦 CONTEXT
    # =========================
    context = {
        'balance': balance,
        'wallet': wallet,
        'transactions': transactions,
        'total_deposits': total_deposits,
        'total_withdrawals': total_withdrawals,
        'total_investments': total_investments,
        'daily_profit': daily_profit,
        'growth_plot': growth_plot,
        'status_plot': status_plot,
    }

    return render(request, 'user/dashboard.html', context)

# user/views.py



# ---------------- PROFILE / SET PIN ----------------


@login_required
def profile(request):
    user = request.user

    pin_obj = TransactionPIN.objects.filter(user=user).first()

    set_form = SetNewPINForm()
    change_form = ChangePINForm()

    if request.method == "POST":

        # --- Update profile info ---
        if "update_profile" in request.POST:
            new_username = request.POST.get("username")
            new_email = request.POST.get("email")
            new_phone = request.POST.get("phone")

            # ❌ REMOVED UNIQUE PHONE CHECK (as requested)

            user.username = new_username
            user.email = new_email
            user.phone = new_phone
            user.save()

            messages.success(request, "Profile updated successfully!")
            return redirect("user:profile")

        # --- Set PIN ---
        elif "set_pin" in request.POST:
            set_form = SetNewPINForm(request.POST)
            if set_form.is_valid():
                pin_value = set_form.cleaned_data["pin"]

                if pin_obj:
                    pin_obj.set_pin(pin_value)
                else:
                    pin_obj = TransactionPIN.objects.create(user=user)
                    pin_obj.set_pin(pin_value)

                messages.success(request, "Transaction PIN set successfully!")
                return redirect("user:profile")
            else:
                messages.error(request, "Error setting PIN. Please check your input.")

        # --- Change PIN ---
        elif "change_pin" in request.POST:
            change_form = ChangePINForm(request.POST)
            if change_form.is_valid():
                current_pin = change_form.cleaned_data["current_pin"]
                new_pin = change_form.cleaned_data["new_pin"]

                if not pin_obj:
                    messages.error(request, "Please set a transaction PIN first.")
                elif not pin_obj.check_pin(current_pin):
                    messages.error(request, "Current PIN is incorrect.")
                else:
                    pin_obj.set_pin(new_pin)
                    messages.success(request, "Transaction PIN changed successfully!")
                    return redirect("user:profile")
            else:
                messages.error(request, "Please fill all fields correctly.")

    context = {
        "user": user,
        "pin_obj": pin_obj,
        "set_form": set_form,
        "change_form": change_form if pin_obj else None,
    }

    return render(request, "user/profile.html", context)
# ---------------- FORGOT PIN / OTP ----------------


OTP_EXPIRATION_SECONDS = 300  # 5 minutes

def forgot_pin_request(request):
    if request.method == "POST":
        form = ForgotPINForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']

            # Check if the email belongs to a registered user
            try:
                user = CustomUser.objects.get(email=email)
            except CustomUser.DoesNotExist:
                messages.error(request, "No user found with this email.")
                return redirect('user:forgot_pin_request')

            # Optional: Ensure the email is the one used by the logged-in user
            if request.user.is_authenticated and user != request.user:
                messages.error(request, "Please enter the email you registered with.")
                return redirect('user:forgot_pin_request')

            # Send OTP via email
            otp = send_otp_email(user.email)

            # Store OTP and timing in session
            request.session['forgot_pin_user'] = user.id
            request.session['forgot_pin_otp'] = otp
            request.session['forgot_pin_otp_time'] = time.time()

            messages.success(request, "OTP sent to your registered email.")
            return redirect('user:forgot_pin_verify')
    else:
        form = ForgotPINForm()
    return render(request, "user/forgot_pin_request.html", {'form': form})


def forgot_pin_verify(request):
    if request.method == "POST":
        form = VerifyOTPForm(request.POST)
        if form.is_valid():
            otp = form.cleaned_data['otp']
            session_otp = request.session.get('forgot_pin_otp')
            otp_time = request.session.get('forgot_pin_otp_time')

            if not session_otp or not otp_time or time.time() - otp_time > OTP_EXPIRATION_SECONDS:
                messages.error(request, "OTP expired. Request a new one.")
                return redirect('user:forgot_pin_request')

            if otp == session_otp:
                request.session['otp_verified'] = True
                messages.success(request, "OTP verified! Set your new PIN now.")
                return redirect('user:set_new_pin')
            else:
                messages.error(request, "Invalid OTP.")
    else:
        form = VerifyOTPForm()
    return render(request, "user/forgot_pin_verify.html", {'form': form})


@login_required
def set_new_pin(request):

    if not request.session.get('otp_verified'):
        messages.error(request, "Unauthorized access.")
        return redirect('user:forgot_pin_request')

    user_id = request.session.get('forgot_pin_user')

    # Ensure session exists
    if not user_id:
        messages.error(request, "Session expired. Start again.")
        return redirect('user:forgot_pin_request')

    # ✅ Always use logged-in user (FIXED)
    user = request.user

    if request.method == "POST":
        # ✅ Use ONE consistent form (FIXED)
        form = SetNewPINForm(request.POST)

        if form.is_valid():
            try:
                pin_obj = user.transaction_pin
            except TransactionPIN.DoesNotExist:
                pin_obj = TransactionPIN(user=user)

            # ✅ Always hash properly
            pin_obj.set_pin(form.cleaned_data['pin'])

            # ✅ Clean ONLY OTP session (NOT flush)
            request.session.pop('forgot_pin_user', None)
            request.session.pop('forgot_pin_otp', None)
            request.session.pop('forgot_pin_otp_time', None)

            messages.success(request, "PIN reset successfully!")
            return redirect('user:profile')  # ✅ FIXED redirect

    else:
        form = SetNewPINForm()

    return render(request, "user/set_new_pin.html", {'form': form})

@login_required
def change_pin(request):
    user = request.user
    try:
        pin_obj = TransactionPIN.objects.get(user=user)
    except TransactionPIN.DoesNotExist:
        messages.error(request, "No PIN set yet. Please set a PIN first.")
        return redirect('user:profile')

    if request.method == 'POST':
        form = ChangePINForm(request.POST)
        if form.is_valid():
            current_pin = form.cleaned_data['current_pin']
            new_pin = form.cleaned_data['new_pin']

            if not pin_obj.check_pin(current_pin):
                messages.error(request, "Current PIN is incorrect.")
            else:
                pin_obj.set_pin(new_pin)
                messages.success(request, "PIN changed successfully!")
                return redirect('user:profile')
    else:
        form = ChangePINForm()

    return render(request, 'user/change_pin.html', {'form': form})