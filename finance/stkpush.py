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

    shortcode = settings.MPESA_SHORTCODE
    passkey = settings.MPESA_PASSKEY

    if not shortcode or not passkey:
        return JsonResponse(
            {"error": "M-Pesa shortcode or passkey is not configured"},
            status=500
        )

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

    base_url = settings.MPESA_BASE_URL or "https://sandbox.safaricom.co.ke"
    stk_url = f"{base_url}/mpesa/stkpush/v1/processrequest"

    try:

        response = requests.post(
            stk_url,
            json=payload,
            headers=headers,
            timeout=30
        )

        return JsonResponse(response.json())

    except Exception as e:
        return JsonResponse(
            {"error": str(e)},
            status=500
        )
