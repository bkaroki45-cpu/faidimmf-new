# finance/utils.py

from django.core.mail import send_mail
from django.db.models import Sum
import random
from finance.models import Transaction, Wallet, CompanyAccount, SystemState, LedgerEntry
from decimal import Decimal
from django.utils import timezone
from django.db import transaction
from datetime import date
import uuid
from finance.models import InvestmentTracking, LedgerEntry, CompanyAccount, Transaction



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


from django.db import transaction
from decimal import Decimal
import uuid

def process_maturity(user, investment):

    if investment.is_redeemed:
        return Decimal("0")

    with transaction.atomic():

        investment = InvestmentTracking.objects.select_for_update().get(id=investment.id)

        if investment.is_redeemed:
            return Decimal("0")

        # 🔒 prevent duplicates properly
        if LedgerEntry.objects.filter(
            reference=f"MATURE-{investment.id}",
            tx_type="investment_return"
        ).exists():
            return Decimal("0")

        total_return = investment.total_return()
        profit = investment.calculate_profit()

        investment.is_redeemed = True
        investment.save(update_fields=["is_redeemed"])

        pool = CompanyAccount.objects.get(account_type="pool")
        reserve = CompanyAccount.objects.get(account_type="reserve")

        # =========================
        # 1. Pool decreases FULL return
        # =========================
        LedgerEntry.objects.create(
            user=None,
            account=pool,
            tx_type="investment_return",
            amount=total_return,
            is_credit=False,
            reference=f"MATURE-{investment.id}"
        )

        # =========================
        # 2. Reserve increases FULL return (IMPORTANT FIX)
        # =========================
        LedgerEntry.objects.create(
            user=None,
            account=reserve,
            tx_type="investment_return",
            amount=total_return,
            is_credit=True,
            reference=f"MATURE-{investment.id}"
        )

        # =========================
        # 3. User wallet (ONLY ONCE via transaction)
        # =========================
        Transaction.objects.create(
            user=user,
            amount=total_return,
            tx_type="investment_return",
            status="completed",
            checkout_id=f"MAT-{investment.id}"
        )

        return total_return

def reset_daily_if_needed():
    state, _ = SystemState.objects.get_or_create(id=1)

    if state.last_reset != date.today():
        CompanyAccount.objects.filter(
            account_type="investment_pool"
        ).update(
            invested_today=0,
            matured_today=0
        )

        state.last_reset = date.today()
        state.save()