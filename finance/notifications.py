import logging

import requests
from django.conf import settings
from django.utils import timezone


logger = logging.getLogger(__name__)


def send_telegram_message(message):
    """
    Send a message to the configured Telegram chat.

    Returns True when Telegram accepts the message, otherwise False.
    Failures are logged and swallowed so user-facing workflows do not crash.
    """
    bot_token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    chat_id = getattr(settings, "TELEGRAM_CHAT_ID", "")

    if not bot_token or not chat_id:
        logger.warning("Telegram notification skipped: missing bot token or chat ID.")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=getattr(settings, "TELEGRAM_TIMEOUT_SECONDS", 5),
        )
        response.raise_for_status()
    except requests.RequestException:
        logger.exception("Telegram notification failed.")
        return False

    return True


def send_transaction_notification(transaction, event="updated"):
    user = transaction.user
    username = getattr(user, "username", "Unknown")
    phone = transaction.phone_number or getattr(user, "phone", None) or "Not provided"
    tx_labels = {
        "deposit": "Deposit",
        "withdraw": "Withdrawal",
        "invest": "Investment",
        "referral": "Referral Bonus",
        "investment_return": "Investment Maturity Redeemed",
    }
    status_labels = {
        "pending": "Pending",
        "completed": "Completed",
        "failed": "Failed",
    }
    event_labels = {
        "created": "New Transaction",
        "status_changed": "Transaction Status Updated",
        "updated": "Transaction Updated",
    }
    tx_label = tx_labels.get(transaction.tx_type, transaction.tx_type.title())
    status_label = status_labels.get(transaction.status, transaction.status.title())
    identifier = (
        transaction.checkout_id
        or transaction.mpesa_code
        or transaction.conversation_id
        or f"TX-{transaction.id}"
    )
    title = event_labels.get(event, "Transaction Updated")

    if transaction.tx_type == "withdraw" and transaction.status == "pending":
        title = "NEW WITHDRAWAL REQUEST"
    else:
        title = f"{title}: {tx_label}"

    message = (
        f"<b>{title}</b>\n\n"
        f"User: {username}\n"
        f"Amount: KES {transaction.amount}\n"
        f"Type: {tx_label}\n"
        f"Status: {status_label}\n"
        f"Phone: {phone}\n"
        f"Reference: {identifier}\n"
        f"Time: {timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M:%S')}"
    )

    if transaction.result_desc:
        message += f"\nNote: {transaction.result_desc}"

    return send_telegram_message(message)


def send_withdrawal_request_notification(transaction):
    return send_transaction_notification(transaction, event="created")


def notify_withdrawal_request(transaction):
    """
    Dispatch a withdrawal notification.

    Uses Celery when TELEGRAM_USE_CELERY=True, otherwise sends immediately.
    Falls back to immediate sending if the task cannot be queued.
    """
    if getattr(settings, "TELEGRAM_USE_CELERY", False):
        try:
            from .tasks import send_withdrawal_request_notification_task

            send_withdrawal_request_notification_task.delay(transaction.id)
            return True
        except Exception:
            logger.exception(
                "Could not queue Telegram withdrawal notification; sending inline."
            )

    return send_withdrawal_request_notification(transaction)


def notify_transaction(transaction, event="updated"):
    """
    Dispatch a Telegram notification for any transaction type.

    Uses Celery when TELEGRAM_USE_CELERY=True, otherwise sends immediately.
    Falls back to immediate sending if the task cannot be queued.
    """
    if getattr(settings, "TELEGRAM_USE_CELERY", False):
        try:
            from .tasks import send_transaction_notification_task

            send_transaction_notification_task.delay(transaction.id, event)
            return True
        except Exception:
            logger.exception(
                "Could not queue Telegram transaction notification; sending inline."
            )

    return send_transaction_notification(transaction, event=event)
