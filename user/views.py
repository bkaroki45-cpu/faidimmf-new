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




def register(request):
    ref_code = request.GET.get('ref')  # from referral link

    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        entered_ref = request.POST.get('referral_code')  # manual input

        if form.is_valid():
            user = form.save()

            # Use entered referral OR URL referral
            code = entered_ref or ref_code

            if code:
                try:
                    referrer = CustomUser.objects.get(referral_code=code)

                    # prevent self-referral (extra safety)
                    if referrer != user:
                        user.referred_by = referrer
                        user.save()

                except CustomUser.DoesNotExist:
                    messages.warning(request, "Invalid referral code (ignored).")

            login(request, user)
            messages.success(request, f"Welcome, {user.username}! Your account was created.")
            return redirect('user:dashboard')

        else:
            messages.error(request, "Please correct the errors below.")

    else:
        form = CustomUserCreationForm()

    return render(request, 'user/register.html', {
        'form': form,
        'ref_code': ref_code  # send to template
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





@login_required
def dashboard(request):
    user = request.user
    wallet, _ = Wallet.objects.get_or_create(user=user)
    balance = wallet.balance

    # --- Last 10 transactions ---
    transactions = Transaction.objects.filter(user=user).order_by('-timestamp')[:10]

    # --- Aggregates ---
    total_deposits = Transaction.objects.filter(
        user=user, tx_type='Deposit', status='completed'
    ).aggregate(Sum('amount'))['amount__sum'] or 0

    total_withdrawals = Transaction.objects.filter(
        user=user, tx_type='withdraw', status='completed'
    ).aggregate(Sum('amount'))['amount__sum'] or 0

    daily_profit = Transaction.objects.filter(
        user=user, tx_type='profit', timestamp__date=timezone.localdate()
    ).aggregate(Sum('amount'))['amount__sum'] or 0

    # --- LIVE CHART: Account Growth (Last 7 Days) ---
    today = timezone.localdate()
    last_7_days = [today - datetime.timedelta(days=i) for i in range(6, -1, -1)]

    all_transactions_exist = Transaction.objects.filter(user=user).exists()
    balance_by_day = []

    if all_transactions_exist:
        # Start from current wallet balance
        running_balance = Decimal(balance)

        # Work backwards to compute daily balance
        for day in reversed(last_7_days):
            deposits = Transaction.objects.filter(
                user=user, tx_type='Deposit', status='completed', timestamp__date=day
            ).aggregate(Sum('amount'))['amount__sum'] or 0

            withdrawals = Transaction.objects.filter(
                user=user, tx_type='withdraw', status='completed', timestamp__date=day
            ).aggregate(Sum('amount'))['amount__sum'] or 0

            profit = Transaction.objects.filter(
                user=user, tx_type='profit', timestamp__date=day
            ).aggregate(Sum('amount'))['amount__sum'] or 0

            running_balance -= Decimal(deposits) - Decimal(withdrawals) + Decimal(profit)
            balance_by_day.append(running_balance)

        balance_by_day = list(reversed(balance_by_day))
        chart_name = 'Balance'
        line_color = 'green'

    else:
        # No transactions ever → placeholder line
        balance_by_day = [0.01 for _ in last_7_days]  # tiny value to force rendering
        chart_name = 'No activity yet'
        line_color = 'gray'

    growth_chart = go.Figure()
    growth_chart.add_trace(go.Scatter(
        x=[day.strftime('%d %b') for day in last_7_days],
        y=balance_by_day,
        mode='lines+markers',
        name=chart_name,
        line=dict(color=line_color, width=3)
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

    # --- LIVE CHART: Transaction Status Overview ---
    status_counts_qs = Transaction.objects.filter(user=user).values('status').annotate(count=Count('id'))

    if status_counts_qs.exists():
        labels = [item['status'].capitalize() for item in status_counts_qs]
        values = [item['count'] for item in status_counts_qs]
    else:
        labels = ['Deposits', 'Withdrawals', 'Profits']
        values = [0, 0, 0]  # placeholder for new users

    status_chart = go.Figure(data=[go.Pie(labels=labels, values=values, hole=0.3)])
    status_chart.update_layout(title='Transaction Status Overview', template='plotly_dark')
    status_plot = plot(status_chart, output_type='div', include_plotlyjs=False)

    context = {
        'balance': balance,
        'transactions': transactions,
        'total_deposits': total_deposits,
        'total_withdrawals': total_withdrawals,
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

    # Get existing PIN object if any
    pin_obj = TransactionPIN.objects.filter(user=user).first()

    # Initialize forms
    set_form = SetNewPINForm()
    change_form = ChangePINForm()

    if request.method == "POST":

        # --- Update profile info (username/email/phone) ---
        # --- Update profile info (username/email/phone) ---
        if "update_profile" in request.POST:
            new_username = request.POST.get("username")
            new_email = request.POST.get("email")
            new_phone = request.POST.get("phone")

            # <-- Check if phone already exists for another user -->
            if CustomUser.objects.filter(phone=new_phone).exclude(pk=user.pk).exists():
                messages.error(request, "phone: This phone number is already registered.")
            else:
                # Save only if phone is unique
                user.username = new_username
                user.email = new_email
                user.phone = new_phone
                user.save()
                messages.success(request, "Profile updated successfully!")

            return redirect("user:profile")

        # --- Set PIN for first time ---
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

        # --- Change existing PIN ---
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

    # GET request or fallback
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
            phone = form.cleaned_data['phone']
            try:
                user = CustomUser.objects.get(phone=phone)
            except CustomUser.DoesNotExist:
                messages.error(request, "No user found with this phone.")
                return redirect('user:forgot_pin_request')

            otp = str(random.randint(100000, 999999))
            request.session['forgot_pin_user'] = user.id
            request.session['forgot_pin_otp'] = otp
            request.session['forgot_pin_otp_time'] = time.time()

            # TODO: Send SMS in production
            print(f"OTP for {phone}: {otp}")

            messages.success(request, "OTP sent to your phone.")
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
                request.session['otp_verified'] = True  # ✅ add this
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