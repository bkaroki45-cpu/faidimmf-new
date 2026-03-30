from django.db import models
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal, ROUND_DOWN


# =========================
# TRANSACTIONS
# =========================
from django.db import models
from django.conf import settings
from django.utils import timezone


from django.db import models
from django.conf import settings
from django.utils import timezone


class Transaction(models.Model):

    TRANSACTION_TYPES = [
        ('deposit', 'Deposit'),
        ('withdraw', 'Withdraw'),
        ('invest', 'Invest'),
        ('referral', 'Referral Bonus'),
        ('investment_return', 'Investment Return'),
    ]

    STATUS_TYPES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )

    # ======================
    # CORE AMOUNT
    # ======================
    amount = models.DecimalField(max_digits=20, decimal_places=2)

    # ======================
    # UNIQUE IDS
    # ======================
    checkout_id = models.CharField(max_length=100, unique=True)

    mpesa_code = models.CharField(max_length=100, unique=True, null=True, blank=True)
    conversation_id = models.CharField(max_length=100, null=True, blank=True)
    originator_conversation_id = models.CharField(max_length=100, null=True, blank=True)

    # ======================
    # PAYMENT INFO
    # ======================
    phone_number = models.CharField(max_length=15, null=True, blank=True)

    # ======================
    # STATUS & TYPE
    # ======================
    status = models.CharField(
        max_length=20,
        choices=STATUS_TYPES,
        default='pending'
    )

    tx_type = models.CharField(
        max_length=20,
        choices=TRANSACTION_TYPES,
        default='deposit'
    )

    # ======================
    # REFERRAL SUPPORT
    # ======================
    reference_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="referral_source"
    )

    # ======================
    # EXTRA INFO
    # ======================
    result_desc = models.TextField(null=True, blank=True)

    timestamp = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # ======================
    # METHODS
    # ======================
    def mark_completed(self):
        self.status = "completed"
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "completed_at"])

    def is_credit(self):
        """
        Money IN types (wallet increases)
        """
        return self.tx_type in ["deposit", "referral", "investment_return"]

    def signed_amount(self):
        """
        Returns positive or negative value depending on type
        """
        if self.is_credit():
            return self.amount
        return -self.amount

    def __str__(self):
        return f"{self.tx_type} - {self.amount} KES - {self.status}"

# =========================
# WALLET (FIXED - NO RESET BUG)
# =========================
class Wallet(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    balance = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal('0.00'))

    def __str__(self):
        return f"{self.user.username} Wallet"


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_wallet(sender, instance, created, **kwargs):
    if created:
        Wallet.objects.create(user=instance)


# =========================
# COMPANY ACCOUNTS
# =========================
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

    def __str__(self):
        return f"{self.name} ({self.account_type})"

    def deposit(self, amount):
        self.balance += Decimal(amount)
        self.save()

    def withdraw(self, amount):
        amount = Decimal(amount)
        if amount > self.balance:
            raise ValueError("Insufficient funds")
        self.balance -= amount
        self.save()


# =========================
# INVESTMENTS
# =========================
class InvestmentTracking(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    interest_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=Decimal('0.005')  # 0.5% daily
    )

    invested_at = models.DateTimeField(default=timezone.now)
    maturity_date = models.DateTimeField(null=True, blank=True)
    is_redeemed = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if not self.invested_at:
            self.invested_at = timezone.now()

        if not self.maturity_date:
            self.maturity_date = self.invested_at + timedelta(hours=24)

        super().save(*args, **kwargs)

    def is_matured(self):
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
        return f"{self.user.username} - KSh {self.amount}"