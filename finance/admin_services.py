import uuid
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from .models import (
    INVESTMENT_DAILY_INTEREST_RATE,
    CompanyAccount,
    InvestmentTracking,
    LedgerEntry,
    Transaction,
    Wallet,
)


class AdminTransactionError(ValueError):
    pass


def parse_admin_amount(amount):
    try:
        parsed = Decimal(str(amount)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        raise AdminTransactionError("Enter a valid amount.")

    if parsed <= 0:
        raise AdminTransactionError("Amount must be greater than zero.")

    return parsed


def create_admin_transaction(*, user, tx_type, amount, note="", admin_user=None):
    amount = parse_admin_amount(amount)
    note = (note or "").strip()
    default_descriptions = {
        "deposit": "Deposit processed",
        "withdraw": "Withdrawal processed",
        "invest": "Investment processed",
    }
    result_desc = note or default_descriptions.get(tx_type, "Transaction processed")

    if tx_type not in {"deposit", "withdraw", "invest"}:
        raise AdminTransactionError("Unsupported transaction type.")

    with transaction.atomic():
        wallet, _ = Wallet.objects.select_for_update().get_or_create(user=user)
        reserve = CompanyAccount.objects.select_for_update().get(account_type="reserve")

        if tx_type in {"withdraw", "invest"} and amount > wallet.balance:
            raise AdminTransactionError("Insufficient user wallet balance.")

        checkout_id = f"ADM-{uuid.uuid4()}"

        if tx_type == "invest":
            pool = CompanyAccount.objects.select_for_update().get(account_type="pool")

            # Match the user investment flow: debit the user's reserve-backed wallet
            # immediately, then create a completed Transaction so the existing
            # post_save signal records the system/pool ledger entries.
            LedgerEntry.objects.create(
                user=user,
                account=reserve,
                tx_type="invest",
                amount=amount,
                is_credit=False,
                reference=checkout_id,
                metadata=result_desc,
            )

            pool.invested_today += amount
            pool.save(update_fields=["invested_today"])

            InvestmentTracking.objects.create(
                user=user,
                amount=amount,
                interest_rate=INVESTMENT_DAILY_INTEREST_RATE,
            )

            tx = Transaction.objects.create(
                user=user,
                amount=amount,
                tx_type="invest",
                status="completed",
                checkout_id=checkout_id,
                phone_number=getattr(user, "phone", None),
                result_desc=result_desc,
                origin="admin_manual",
                created_by_admin=admin_user,
                completed_at=timezone.now(),
            )
            return tx

        if tx_type == "withdraw":
            tx = Transaction.objects.create(
                user=user,
                amount=amount,
                tx_type="withdraw",
                status="pending",
                checkout_id=checkout_id,
                phone_number=getattr(user, "phone", None),
                result_desc=result_desc,
                origin="admin_manual",
                created_by_admin=admin_user,
            )

            LedgerEntry.objects.create(
                user=user,
                account=reserve,
                tx_type="withdraw",
                amount=amount,
                is_credit=False,
                reference=checkout_id,
                metadata=result_desc,
            )

            return tx

        tx = Transaction.objects.create(
            user=user,
            amount=amount,
            tx_type=tx_type,
            status="completed",
            checkout_id=checkout_id,
            phone_number=getattr(user, "phone", None),
            result_desc=result_desc,
            origin="admin_manual",
            created_by_admin=admin_user,
            completed_at=timezone.now(),
        )

        return tx
