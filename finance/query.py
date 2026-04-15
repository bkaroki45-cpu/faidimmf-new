import requests
import json
import base64
from datetime import datetime
from django.http import JsonResponse
from .accesstoken import get_access_token_value  

# Map MPESA response codes to friendly messages
MPESA_RESPONSE_MESSAGES = {
    "0": "Success — Payment completed",
    "1": "Cancelled by user",
    "2": "Request failed",
    "1001": "Insufficient funds",
    "1002": "Invalid credentials",
    "1003": "Duplicate request",
    "1004": "Too many requests / rate limit",
    "1005": "Invalid phone number",
    "1032": "Timeout — no response from customer",
    "1037": "System busy — try again",
    "1041": "Duplicate CheckoutRequestID",
    "1044": "Invalid amount",
    "1045": "Invalid PayBill/Till number",
    "500": "Internal server error",
}
    # Add more codes as needed from Safaricom docs


def query_status(request):
    if request.method != 'POST':
        return JsonResponse({"error": "POST method required"}, status=405)

    checkout_request_id = request.POST.get('checkout_request_id')
    if not checkout_request_id:
        return JsonResponse({"error": "checkout_request_id is required"}, status=400)

    access_token = get_access_token_value()
    if not access_token:
        return JsonResponse({"error": "Could not get access token"}, status=500)

    business_shortcode = '174379'  # Sandbox shortcode
    passkey = 'bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919'
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    password_str = business_shortcode + passkey + timestamp
    password = base64.b64encode(password_str.encode()).decode('utf-8')

    payload = {
        "BusinessShortCode": business_shortcode,
        "Password": password,
        "Timestamp": timestamp,
        "CheckoutRequestID": checkout_request_id
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(
            "https://sandbox.safaricom.co.ke/mpesa/stkpushquery/v1/query",
            json=payload,
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        response_data = response.json()

        # Extract ResultCode and ResultDesc if present
        result_code = str(response_data.get("ResultCode", ""))
        result_desc = response_data.get("ResultDesc", "")

        human_message = MPESA_RESPONSE_MESSAGES.get(result_code, result_desc or "Unknown status")

        # Return both raw data and human-readable status
        return JsonResponse({
            "checkout_request_id": checkout_request_id,
            "status_code": result_code,
            "status_message": human_message,
            "raw_response": response_data
        })

    except requests.exceptions.RequestException as e:
        return JsonResponse({"error": f"Request failed: {str(e)}"}, status=500)