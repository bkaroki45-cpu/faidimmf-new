import requests
import base64
from datetime import datetime
from django.http import JsonResponse
from django.conf import settings
from .accesstoken import get_access_token_value


def stk_push(request):

    phone = request.POST.get("phone", "").replace("+", "").strip()
    amount = request.POST.get("amount", 1)

    if not phone.startswith("254") or len(phone) != 12:
        return JsonResponse(
            {"error": "Invalid phone number"},
            status=400
        )

    try:
        amount = int(amount)
    except:
        return JsonResponse(
            {"error": "Invalid amount"},
            status=400
        )

    access_token = get_access_token_value()

    if not access_token:
        return JsonResponse(
            {"error": "Access token failed"},
            status=500
        )

    shortcode = "174379"

    passkey = "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919"

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

    password = base64.b64encode(
        f"{shortcode}{passkey}{timestamp}".encode()
    ).decode()

    payload = {
        "BusinessShortCode": shortcode,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": amount,
        "PartyA": phone,
        "PartyB": shortcode,
        "PhoneNumber": phone,
        "CallBackURL": settings.STK_CALLBACK_URL,
        "AccountReference": "FMMF",
        "TransactionDesc": "Deposit"
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    stk_url = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"

    print("STK URL:", stk_url)
    print("PAYLOAD:", payload)

    try:

        response = requests.post(
            stk_url,
            json=payload,
            headers=headers,
            timeout=30
        )

        print("RAW RESPONSE:", response.text)

        return JsonResponse(response.json())

    except Exception as e:
        print("STK ERROR:", str(e))

        return JsonResponse(
            {"error": str(e)},
            status=500
        )