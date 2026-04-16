from django.http import JsonResponse
from datetime import datetime
import requests
import base64
from .accesstoken import get_access_token_value
from django.conf import settings

def stk_push(request):
    if request.method != "POST":
        return JsonResponse({"error": "Only POST requests allowed"}, status=400)

    phone = request.POST.get("phone", "").replace("+", "").strip()
    amount = request.POST.get("amount", 1)

    # Validate phone and amount
    if not phone.startswith("254") or len(phone) != 12:
        return JsonResponse({"error": "Invalid phone number format"}, status=400)

    try:
        amount = int(amount)
    except ValueError:
        return JsonResponse({"error": "Invalid amount"}, status=400)

    access_token = get_access_token_value()
    if not access_token:
        return JsonResponse({"error": "Could not retrieve access token"}, status=500)

    business_shortcode = settings.MPESA_SHORTCODE
    passkey = settings.MPESA_PASSKEY
    callback_url = settings.STK_CALLBACK_URL

    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    password = base64.b64encode(f"{business_shortcode}{passkey}{timestamp}".encode()).decode('utf-8')

    payload = {
        "BusinessShortCode": business_shortcode,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": amount,
        "PartyA": phone,
        "PartyB": business_shortcode,
        "PhoneNumber": phone,
        "CallBackURL": settings.STK_CALLBACK_URL,
        "AccountReference": "FMMF",
        "TransactionDesc": "Deposit"
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(
            "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest",
            json=payload,
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        res_json = response.json()
        return JsonResponse(res_json)
    except requests.RequestException as e:
        return JsonResponse({"error": f"STK push request failed: {str(e)}"}, status=500)