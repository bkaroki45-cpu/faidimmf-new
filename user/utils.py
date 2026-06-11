from django.core.mail import EmailMultiAlternatives
from django.conf import settings
from django.db.models import Sum
import logging
import random
import smtplib
from finance.models import Transaction, Wallet, CompanyAccount, SystemState, LedgerEntry
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

        if investment.is_redeemed:
            return Decimal("0")

        if not investment.is_matured():
            return Decimal("0")

        # 🔒 prevent duplicates properly
        if LedgerEntry.objects.filter(
            reference=f"MATURE-{investment.id}",
            tx_type="investment_return"
        ).exists():
            return Decimal("0")

        total_return = investment.total_return()
        investment.is_redeemed = True
        investment.save(update_fields=["is_redeemed"])

        # =========================
        # User wallet gets principal + 3% after 24 hours.
        # The transaction signal posts the matching ledger entries once.
        # =========================
        Transaction.objects.create(
            user=user,
            amount=total_return,
            tx_type="investment_return",
            status="completed",
            checkout_id=f"MAT-{investment.id}"
        )

        return total_return


def mature_due_investments(user):
    """
    Redeem every investment whose 24-hour maturity date has passed.
    Returns the total amount credited to the user's wallet.
    """
    due_investments = InvestmentTracking.objects.filter(
        user=user,
        is_redeemed=False,
        maturity_date__lte=timezone.now(),
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
