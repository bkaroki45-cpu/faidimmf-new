import datetime
import secrets
from urllib.parse import urlencode
import requests
from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, authenticate
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.contrib.auth.decorators import login_required
from django.db import transaction as db_transaction
from django.db.models import Sum, Count
from finance.models import LedgerEntry, Transaction, Wallet
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
from .utils import mature_due_investments, send_otp_email
from user.utils import get_wallet_balance
from django.utils import timezone
from .models import PasswordResetOTP
from django.conf import settings
from finance.notifications import notify_signup

def _google_redirect_uri(request):
    callback_path = reverse('user:google_callback')
    if settings.PUBLIC_URL:
        return f"{settings.PUBLIC_URL.rstrip('/')}{callback_path}"
    return request.build_absolute_uri(callback_path)


def _unique_google_username(email, full_name):
    base = (email.split('@')[0] or full_name or 'googleuser').lower()
    base = ''.join(char for char in base if char.isalnum() or char in ('_', '-'))[:24] or 'googleuser'
    username = base
    counter = 1

    while CustomUser.objects.filter(username=username).exists():
        suffix = str(counter)
        username = f"{base[:30 - len(suffix)]}{suffix}"
        counter += 1

    return username


def google_login(request):
    if not settings.GOOGLE_OAUTH_CLIENT_ID or not settings.GOOGLE_OAUTH_CLIENT_SECRET:
        messages.error(request, "Google sign in is not configured yet.")
        return redirect('user:login')

    state = secrets.token_urlsafe(32)
    request.session['google_oauth_state'] = state
    request.session['google_oauth_next'] = request.GET.get('next', '')
    request.session['google_oauth_ref'] = request.GET.get('ref', '')

    params = {
        'client_id': settings.GOOGLE_OAUTH_CLIENT_ID,
        'redirect_uri': _google_redirect_uri(request),
        'response_type': 'code',
        'scope': 'openid email profile',
        'state': state,
        'prompt': 'select_account',
    }
    return redirect(f"{settings.GOOGLE_OAUTH_AUTH_URL}?{urlencode(params)}")


def google_callback(request):
    expected_state = request.session.get('google_oauth_state')
    received_state = request.GET.get('state')

    if not expected_state or received_state != expected_state:
        messages.error(request, "Google sign in could not be verified. Please try again.")
        return redirect('user:login')

    if request.GET.get('error'):
        messages.error(request, "Google sign in was cancelled.")
        return redirect('user:login')

    code = request.GET.get('code')
    if not code:
        messages.error(request, "Google did not return a sign in code.")
        return redirect('user:login')

    try:
        token_response = requests.post(
            settings.GOOGLE_OAUTH_TOKEN_URL,
            data={
                'client_id': settings.GOOGLE_OAUTH_CLIENT_ID,
                'client_secret': settings.GOOGLE_OAUTH_CLIENT_SECRET,
                'code': code,
                'grant_type': 'authorization_code',
                'redirect_uri': _google_redirect_uri(request),
            },
            timeout=10,
        )
        token_response.raise_for_status()
        access_token = token_response.json().get('access_token')

        userinfo_response = requests.get(
            settings.GOOGLE_OAUTH_USERINFO_URL,
            headers={'Authorization': f'Bearer {access_token}'},
            timeout=10,
        )
        userinfo_response.raise_for_status()
        google_user = userinfo_response.json()
    except requests.RequestException:
        messages.error(request, "Google sign in is unavailable right now. Please try again.")
        return redirect('user:login')

    email = (google_user.get('email') or '').strip().lower()
    if not email or not google_user.get('email_verified'):
        messages.error(request, "Please use a verified Google email address.")
        return redirect('user:login')

    next_url = request.session.pop('google_oauth_next', '')
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = reverse('user:dashboard')
    ref_code = request.session.pop('google_oauth_ref', '')
    request.session.pop('google_oauth_state', None)

    user = CustomUser.objects.filter(email__iexact=email).first()
    created = False

    if user is None:
        name = google_user.get('name') or email.split('@')[0]
        user = CustomUser(
            username=_unique_google_username(email, name),
            email=email,
            first_name=(google_user.get('given_name') or '')[:150],
            last_name=(google_user.get('family_name') or '')[:150],
        )
        user.set_unusable_password()

        if ref_code:
            referrer = CustomUser.objects.filter(referral_code=ref_code).first()
            if referrer:
                user.referred_by = referrer

        user.save()
        created = True

    login(request, user)

    if created:
        db_transaction.on_commit(lambda user_id=user.id: notify_signup(
            CustomUser.objects.get(id=user_id)
        ))
        messages.success(request, f"Welcome, {user.username}! Your account was created with Google.")
    else:
        messages.success(request, f"Welcome back, {user.username}.")

    return redirect(next_url)

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
            db_transaction.on_commit(lambda user_id=user.id: notify_signup(
                CustomUser.objects.get(id=user_id)
            ))
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

        user = authenticate(request, username=username, password=password)
        if user is not None:
            otp = send_otp_email(user.email)
            request.session['login_2fa_user_id'] = user.id
            request.session['login_2fa_otp'] = otp
            request.session['login_2fa_otp_time'] = time.time()
            request.session['login_2fa_next'] = next_url
            messages.success(request, "Verification code sent to your registered email. Check your Inbox or Spam folder.")
            return redirect('user:login_verify_otp')
        else:
            error_message = 'Invalid credentials!'

    return render(request, 'user/login.html', {'error': error_message, 'next': next_url})


def login_verify_otp(request):
    user_id = request.session.get('login_2fa_user_id')
    session_otp = request.session.get('login_2fa_otp')
    otp_time = request.session.get('login_2fa_otp_time')

    if not user_id or not session_otp or not otp_time:
        messages.error(request, "Login verification expired. Please log in again.")
        return redirect('user:login')

    try:
        user = CustomUser.objects.get(id=user_id)
    except CustomUser.DoesNotExist:
        messages.error(request, "User account not found. Please log in again.")
        return redirect('user:login')

    if time.time() - otp_time > 300:
        request.session.pop('login_2fa_user_id', None)
        request.session.pop('login_2fa_otp', None)
        request.session.pop('login_2fa_otp_time', None)
        request.session.pop('login_2fa_next', None)
        messages.error(request, "Verification code expired. Please log in again.")
        return redirect('user:login')

    if request.method == 'POST':
        otp_input = request.POST.get('otp', '').strip()

        if otp_input == session_otp:
            next_url = request.session.get('login_2fa_next')

            request.session.pop('login_2fa_user_id', None)
            request.session.pop('login_2fa_otp', None)
            request.session.pop('login_2fa_otp_time', None)
            request.session.pop('login_2fa_next', None)

            login(request, user)
            return redirect(next_url or reverse('user:dashboard'))

        return render(request, 'user/login_verify_otp.html', {
            'error': 'Invalid verification code',
        })

    return render(request, 'user/login_verify_otp.html')

def logout_view(request):
    if request.method == 'POST':
        logout(request)
        return redirect('user:login')
    else:
        return redirect('home')
    
    import random
from django.core.mail import EmailMultiAlternatives

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

        # Send email with clear transactional content and stable headers.
        reset_email = EmailMultiAlternatives(
            subject="Faidii MMF Password Reset Code",
            body=(
                f"Your Faidii MMF password reset code is: {otp}. It will expire in 10 minutes.\n\n"
                "If you did not request this code, you can ignore this email.\n\n"
                "FAIDII Money Market Fund"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[email],
            headers={"List-Unsubscribe": "<mailto:faidimmf@gmail.com?subject=unsubscribe>"},
        )
        reset_email.send(fail_silently=False)

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
    mature_due_investments(user)

    # =========================
    # 💰 REAL BALANCE (FROM LEDGER)
    # =========================
    wallet, _ = Wallet.objects.get_or_create(user=user)
    balance = wallet.balance

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

    start_datetime = timezone.make_aware(
        datetime.datetime.combine(last_7_days[0], datetime.time.min),
        timezone.get_current_timezone()
    )

    prior_credits = LedgerEntry.objects.filter(
        user=user,
        is_credit=True,
        created_at__lt=start_datetime
    ).aggregate(total=Sum('amount'))['total'] or Decimal("0")

    prior_debits = LedgerEntry.objects.filter(
        user=user,
        is_credit=False,
        created_at__lt=start_datetime
    ).aggregate(total=Sum('amount'))['total'] or Decimal("0")

    running = prior_credits - prior_debits
    balance_by_day = []

    for day in last_7_days:
        credits = LedgerEntry.objects.filter(
            user=user,
            is_credit=True,
            created_at__date=day
        ).aggregate(total=Sum('amount'))['total'] or Decimal("0")

        debits = LedgerEntry.objects.filter(
            user=user,
            is_credit=False,
            created_at__date=day
        ).aggregate(total=Sum('amount'))['total'] or Decimal("0")

        running += credits - debits
        balance_by_day.append(running)

    growth_chart = go.Figure()
    growth_chart.add_trace(go.Scatter(
        x=[d.strftime('%d %b') for d in last_7_days],
        y=balance_by_day,
        mode='lines+markers',
        name='Wallet Balance'
    ))

    growth_chart.update_layout(
        title='Account Growth (Last 7 Days)',
        xaxis_title='Date',
        yaxis_title='Wallet Balance (KSh)',
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
