# finance/utils.py

from django.core.mail import send_mail
from django.db.models import Sum
import random
from finance.models import Transaction, Wallet, CompanyAccount
from decimal import Decimal
from django.utils import timezone
from django.db import transaction



# ==============================
# OTP FUNCTION
# ==============================
def send_otp_email(user_email):
    otp = str(random.randint(100000, 999999))
    subject = "Your OTP Code"
    message = f"Your OTP code is: {otp}. It will expire in 5 minutes."

    from_email = "Faidi MMF <your_email@gmail.com>"  # set EMAIL_HOST_USER in settings

    send_mail(subject, message, from_email, [user_email])
    return otp


# ==============================
# WALLET BALANCE CALCULATOR
# ==============================
def get_wallet_balance(user):

    deposits = Transaction.objects.filter(
        user=user,
        tx_type__iexact="deposit",
        status__iexact="completed"
    ).aggregate(total=Sum("amount"))["total"] or 0

    withdrawals = Transaction.objects.filter(
        user=user,
        tx_type__iexact="withdraw",
        status__iexact="completed"
    ).aggregate(total=Sum("amount"))["total"] or 0

    investments = Transaction.objects.filter(
        user=user,
        tx_type__iexact="invest",
        status__iexact="completed"
    ).aggregate(total=Sum("amount"))["total"] or 0

    referral_bonus = Transaction.objects.filter(
        user=user,
        tx_type__iexact="referral",
        status__iexact="completed"
    ).aggregate(total=Sum("amount"))["total"] or 0

    investment_returns = Transaction.objects.filter(
        user=user,
        tx_type__iexact="investment_return",
        status__iexact="completed"
    ).aggregate(total=Sum("amount"))["total"] or 0

    return (
        deposits
        + referral_bonus
        + investment_returns
        - withdrawals
        - investments
    )




def credit_referral_bonus(user, ref_user):
    first_deposit = Transaction.objects.filter(
        user=ref_user,
        tx_type__iexact="deposit",
        status__iexact="completed"
    ).order_by('timestamp').first()

    if not first_deposit:
        return Decimal("0.00")

    bonus = (first_deposit.amount * Decimal("0.10")).quantize(Decimal("0.01"))

    # 🔥 Prevent double crediting
    exists = Transaction.objects.filter(
        user=user,
        tx_type="referral",
        reference_user=ref_user
    ).exists()

    if exists:
        return bonus

    Transaction.objects.create(
        user=user,
        tx_type="referral",
        amount=bonus,
        status="completed",
        reference_user=ref_user
    )

    return bonus



def process_maturity(user, investment):
    """
    Safely redeems ONE investment (ONLY ONCE)
    """

    # 🔥 HARD GUARD
    if investment.is_redeemed:
        return 0

    wallet, _ = Wallet.objects.get_or_create(user=user)
    pool_account = CompanyAccount.objects.get(account_type="investment_pool")

    profit = investment.amount * investment.interest_rate
    total = investment.amount + profit

    with transaction.atomic():

        # 🔥 DOUBLE SAFETY CHECK (VERY IMPORTANT)
        investment.refresh_from_db()
        if investment.is_redeemed:
            return 0

        # 1. Create transaction
        Transaction.objects.create(
            user=user,
            tx_type="investment_return",
            amount=total,
            status="completed"
        )

        # 2. Update wallet
        wallet.balance += total
        wallet.save()

        # 3. Reduce pool
        pool_account.balance -= investment.amount
        pool_account.save()

        # 4. Mark redeemed
        investment.is_redeemed = True
        investment.save()

    return total