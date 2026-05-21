import logging

from celery import shared_task

from .models import Transaction
from .notifications import send_withdrawal_request_notification


logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def send_withdrawal_request_notification_task(self, transaction_id):
    try:
        transaction = Transaction.objects.select_related("user").get(id=transaction_id)
    except Transaction.DoesNotExist:
        logger.warning(
            "Telegram withdrawal notification skipped: transaction %s not found.",
            transaction_id,
        )
        return False

    if transaction.tx_type != "withdraw" or transaction.status != "pending":
        logger.info(
            "Telegram withdrawal notification skipped for transaction %s: "
            "tx_type=%s status=%s.",
            transaction_id,
            transaction.tx_type,
            transaction.status,
        )
        return False

    return send_withdrawal_request_notification(transaction)
