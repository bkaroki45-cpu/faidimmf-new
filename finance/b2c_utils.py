import requests
from django.conf import settings

def send_b2c_payment(phone_number, amount, remarks="MMF Payout", occasion="Payout"):
    from .accesstoken import get_access_token_value

    token = get_access_token_value()
    if not token:
        return {"status": "error", "message": "Cannot get access token"}

    # Format phone
    def format_phone_number(phone):
        if not phone:
            return None
        phone = phone.strip()
        if phone.startswith("+"): phone = phone[1:]
        if phone.startswith("0"): phone = "254" + phone[1:]
        if not phone.startswith("254"): phone = "254" + phone
        return phone

    phone_number = format_phone_number(phone_number)
    if not phone_number:
        return {"status": "error", "message": "Invalid phone number"}

    payload = {
        "InitiatorName": settings.MPESA_B2C_INITIATOR,
        "SecurityCredential": settings.MPESA_B2C_SECURITY_CREDENTIAL,
        "CommandID": "BusinessPayment",
        "Amount": amount,
        "PartyA": settings.MPESA_B2C_PARTYA,
        "PartyB": phone_number,
        "Remarks": remarks,
        "QueueTimeOutURL": settings.B2C_TIMEOUT_URL,
        "ResultURL": settings.B2C_RESULT_URL,
        "Occasion": occasion
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(f"{settings.MPESA_BASE_URL}/mpesa/b2c/v1/paymentrequest",
                                 json=payload, headers=headers, timeout=30)
        data = response.json()
        return {
            "response": data,
            "conversation_id": data.get("ConversationID"),
            "originator_conversation_id": data.get("OriginatorConversationID"),
            "ResponseCode": data.get("ResponseCode")
        }
    except requests.RequestException as e:
        return {"status": "error", "message": str(e)}