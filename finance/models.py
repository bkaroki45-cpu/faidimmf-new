from django.db import models
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
import datetime
from decimal import Decimal,ROUND_DOWN




class Transaction(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True)
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    
    # Internal reference
    checkout_id = models.CharField(max_length=100, unique=True)
    
    # M-Pesa B2C identifiers
    mpesa_code = models.CharField(max_length=100, unique=True, null=True, blank=True)
    conversation_id = models.CharField(max_length=100, null=True, blank=True)
    originator_conversation_id = models.CharField(max_length=100, null=True, blank=True)
    
    phone_number = models.CharField(max_length=15)
    status = models.CharField(max_length=20, default='pending')
    tx_type = models.CharField(
        max_length=10,
        choices=[('deposit','Deposit'),('withdraw','Withdraw')],
        default='deposit'
    )
    result_desc = models.TextField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.tx_type} - {self.amount} KES - {self.status}"


class Wallet(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    balance = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal('0.00'))

    def __str__(self):
        return f"{self.user.username} Wallet"


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_wallet(sender, instance, created, **kwargs):
    if created:
        Wallet.objects.create(user=instance)

# finance/models.py






class CompanyAccount(models.Model):
    ACCOUNT_TYPE_CHOICES = [
        ("liquidity", "Liquidity Reserve"),
        ("investment_pool", "Investment Pool"),
    ]
    name = models.CharField(max_length=100)
    account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPE_CHOICES)
    account_number = models.CharField(max_length=50, blank=True, null=True)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Company Account"
        verbose_name_plural = "Company Accounts"

    def __str__(self):
        return f"{self.name} ({self.account_type}) - Balance: {self.balance}"

    def deposit(self, amount):
        self.balance += Decimal(amount)
        self.save()

    def withdraw(self, amount):
        amount = Decimal(amount)
        if amount > self.balance:
            raise ValueError("Insufficient funds in company account")
        self.balance -= amount
        self.save()




# finance/models.py

class InvestmentTracking(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    # Daily interest rate: 0.5%
    interest_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=Decimal('0.005')
    )

    invested_at = models.DateTimeField(default=timezone.now)
    maturity_date = models.DateTimeField(null=False, blank=False)
    is_redeemed = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if self.invested_at is None:
            self.invested_at = timezone.now()

        if self.maturity_date is None:
            self.maturity_date = self.invested_at + timedelta(hours=24)

        super().save(*args, **kwargs)

    def is_matured(self):
        if self.maturity_date is None:
            return False
        return timezone.now() >= self.maturity_date

    def calculate_profit(self):
        return (self.amount * self.interest_rate).quantize(
            Decimal('0.01'),
            rounding=ROUND_DOWN
        )

    def total_return(self):
        return (self.amount + self.calculate_profit()).quantize(
            Decimal('0.01'),
            rounding=ROUND_DOWN
        )

    def __str__(self):
        return f"{self.user.username} - KSh {self.amount} - {'Redeemed' if self.is_redeemed else 'Active'}"

