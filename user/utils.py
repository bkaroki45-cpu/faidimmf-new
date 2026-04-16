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
from django.db.models import Sum
from decimal import Decimal
from finance.models import LedgerEntry

def get_wallet_balance(user):

    credits = LedgerEntry.objects.filter(
        user=user,
        is_credit=True
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

    debits = LedgerEntry.objects.filter(
        user=user,
        is_credit=False
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

    return credits - debits




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




from decimal import Decimal
from django.db import transaction

def process_maturity(user, investment):

    with transaction.atomic():

        investment = InvestmentTracking.objects.select_for_update().get(id=investment.id)

        # ✅ HARD LOCK (MOST IMPORTANT)
        if investment.is_redeemed:
            return Decimal("0")

        # ✅ GLOBAL GUARD (prevents duplicate runs)
        if LedgerEntry.objects.filter(
            reference=f"MATURE-{investment.id}"
        ).exists():
            return Decimal("0")

        principal = investment.amount
        profit = investment.calculate_profit()
        total = principal + profit

        investment.is_redeemed = True
        investment.save(update_fields=["is_redeemed"])

        pool = CompanyAccount.objects.select_for_update().get(account_type="pool")
        reserve = CompanyAccount.objects.select_for_update().get(account_type="reserve")

        # =========================
        # 1. POOL DEBIT
        # =========================
        LedgerEntry.objects.create(
            user=None,
            account=pool,
            tx_type="maturity_pool_debit",
            amount=principal,
            is_credit=False,
            reference=f"MATURE-{investment.id}"
        )

        

        # =========================
        # 3. USER WALLET CREDIT
        # =========================
        LedgerEntry.objects.create(
            user=user,
            account=reserve,
            tx_type="investment_return",
            amount=total,
            is_credit=True,
            reference=f"MATURE-{investment.id}"
        )

        return total
    

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