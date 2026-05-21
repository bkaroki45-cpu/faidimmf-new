import logging

import requests
from django.conf import settings


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


def send_withdrawal_request_notification(transaction):
    user = transaction.user
    username = getattr(user, "username", "Unknown")
    phone = transaction.phone_number or getattr(user, "phone", None) or "Not provided"

    message = (
        "<b>🚨 NEW WITHDRAWAL REQUEST</b>\n\n"
        f"User: {username}\n"
        f"Amount: KES {transaction.amount}\n"
        f"Phone: {phone}\n"
        "Status: Pending Approval"
    )

    return send_telegram_message(message)


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
