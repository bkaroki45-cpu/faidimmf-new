import os
import requests
from dotenv import load_dotenv
from django.conf import settings

load_dotenv()


def get_access_token_value():
    consumer_key = (
        getattr(settings, "CONSUMER_KEY", None)
        or os.getenv("MPESA_PRODUCTION_CONSUMER_KEY")
        or os.getenv("CONSUMER_KEY")
    )
    consumer_secret = (
        getattr(settings, "CONSUMER_SECRET", None)
        or os.getenv("MPESA_PRODUCTION_CONSUMER_SECRET")
        or os.getenv("CONSUMER_SECRET")
    )
    base_url = getattr(settings, "MPESA_BASE_URL", None) or os.getenv(
        "MPESA_BASE_URL",
        "https://sandbox.safaricom.co.ke",
    )

    access_token_url = f"{base_url}/oauth/v1/generate?grant_type=client_credentials"
    headers = {"Content-Type": "application/json"}
    auth = (consumer_key, consumer_secret)

    try:
        response = requests.get(access_token_url, auth=auth, headers=headers)
        response.raise_for_status()
        result = response.json()
        return result.get("access_token")
    except requests.exceptions.RequestException as e:
        print("Error getting access token:", e)
        return None
