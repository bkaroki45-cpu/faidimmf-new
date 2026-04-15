import os
import requests
from dotenv import load_dotenv

load_dotenv()

CONSUMER_KEY = os.getenv('CONSUMER_KEY')
CONSUMER_SECRET = os.getenv('CONSUMER_SECRET')
MPESA_BASE_URL = os.getenv('MPESA_BASE_URL', 'https://sandbox.safaricom.co.ke')


def get_access_token_value():
    access_token_url = f"{MPESA_BASE_URL}/oauth/v1/generate?grant_type=client_credentials"
    headers = {"Content-Type": "application/json"}
    auth = (CONSUMER_KEY, CONSUMER_SECRET)

    try:
        response = requests.get(access_token_url, auth=auth, headers=headers)
        response.raise_for_status()
        result = response.json()
        print("Access token response:", result)  # <--- debug
        return result.get("access_token")
    except requests.exceptions.RequestException as e:
        print("Error getting access token:", e)
        return None