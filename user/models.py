from django.db import models
from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.contrib.auth.hashers import make_password, check_password
import uuid
from django.utils import timezone



class CustomUser(AbstractUser):
    phone = models.CharField(max_length=15, null=True, blank=True, unique=False)
    email = models.EmailField(unique=True, blank=False, null=False)  # ✅ make email unique

    referral_code = models.CharField(max_length=10, blank=True, unique=True)
    referred_by = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='referrals'
    )

    def save(self, *args, **kwargs):
        if not self.referral_code:
            self.referral_code = self.generate_unique_referral_code()
        super().save(*args, **kwargs)

    def generate_unique_referral_code(self):
        code = uuid.uuid4().hex[:10].upper()
        while CustomUser.objects.filter(referral_code=code).exists():
            code = uuid.uuid4().hex[:10].upper()
        return code




class TransactionPIN(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='transaction_pin'
    )
    pin = models.CharField(max_length=128)  # store hashed PIN
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} PIN"

    # Set PIN securely
    def set_pin(self, raw_pin):
        self.pin = make_password(raw_pin)
        self.save()

    # Verify PIN
    def check_pin(self, raw_pin):
        return check_password(raw_pin, self.pin)
    

class PasswordResetOTP(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    otp = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    is_used = models.BooleanField(default=False)

    def is_valid(self):
        return (timezone.now() - self.created_at).seconds < 600  # 10 minutes