# utils.py
from django.core.mail import send_mail
import random

def send_otp_email(user_email):
    otp = str(random.randint(100000, 999999))
    subject = "Your OTP Code"
    message = f"Your OTP code is: {otp}. It will expire in 5 minutes."
    from_email = "Faidi MMF <your_email@gmail.com>"  # Set in settings.py EMAIL_HOST_USER

    send_mail(subject, message, from_email, [user_email])
    return otp