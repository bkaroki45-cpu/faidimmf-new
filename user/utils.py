from django.core.mail import EmailMultiAlternatives
from django.conf import settings
from django.db.models import Sum
import logging
import random
import smtplib
from finance.models import (
    INVESTMENT_LOCK_DAYS,
    Transaction,
    Wallet,
    CompanyAccount,
    SystemState,
    LedgerEntry,
)
from decimal import Decimal
from django.utils import timezone
from django.db import transaction
from datetime import date
import uuid
from finance.models import InvestmentTracking, LedgerEntry, CompanyAccount, Transaction

logger = logging.getLogger(__name__)


# ==============================
# OTP FUNCTION
# ==============================
def send_otp_email(user_email, purpose="verification", expiry_minutes=5):
    otp = str(random.randint(100000, 999999))
    subject = "Your Faidii MMF Verification Code"
    message = (
        f"Your Faidii MMF {purpose} code is: {otp}. It will expire in {expiry_minutes} minutes.\n\n"
        "If you did not request this code, you can ignore this email.\n\n"
        "FAIDII Money Market Fund"
    )

    email = EmailMultiAlternatives(
        subject=subject,
        body=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user_email],
        headers={"List-Unsubscribe": "<mailto:faidimmf@gmail.com?subject=unsubscribe>"},
    )
    try:
        email.send(fail_silently=False)
    except (smtplib.SMTPException, OSError):
        logger.exception("Unable to send OTP email to %s", user_email)
        return None

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

        total_credited = Decimal("0")
        now = timezone.now()
        elapsed_days = int((now - investment.invested_at).total_seconds() // 86400)
        payable_days = min(elapsed_days, INVESTMENT_LOCK_DAYS)
        daily_profit = investment.calculate_profit()

        # 🔒 prevent duplicates properly
        for day_number in range(1, payable_days + 1):
            reference = f"PROFIT-{investment.id}-{day_number}"
            if Transaction.objects.filter(checkout_id=reference).exists():
                continue

            Transaction.objects.create(
                user=user,
                amount=daily_profit,
                tx_type="investment_return",
                status="completed",
                checkout_id=reference,
                result_desc=f"Daily investment profit day {day_number} for investment #{investment.id}",
            )
            total_credited += daily_profit

        if investment.is_redeemed or not investment.is_matured():
            return total_credited

        principal_reference = f"PRINCIPAL-{investment.id}"
        if not Transaction.objects.filter(checkout_id=principal_reference).exists():
            Transaction.objects.create(
                user=user,
                amount=investment.amount,
                tx_type="investment_return",
                status="completed",
                checkout_id=principal_reference,
                result_desc=f"Investment principal returned for investment #{investment.id}",
            )
            total_credited += investment.amount

        investment.is_redeemed = True
        investment.save(update_fields=["is_redeemed"])

        return total_credited


def mature_due_investments(user):
    """
    Credit due daily profits and return principal after the 7-day lock.
    Returns the total amount credited to the user's wallet.
    """
    due_investments = InvestmentTracking.objects.filter(
        user=user,
        is_redeemed=False,
        invested_at__lte=timezone.now(),
    )

    total_credited = Decimal("0")

    for investment in due_investments:
        total_credited += process_maturity(user, investment)

    return total_credited

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
