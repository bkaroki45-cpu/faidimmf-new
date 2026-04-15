from django.db import models
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal, ROUND_DOWN
from django.db.models import Sum
from django.db.models.signals import post_save

# =========================
# TRANSACTIONS
# =========================

from django.core.exceptions import ValidationError


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
    # UNIQUE IDS (FIXED 🔥)
    # ======================
    checkout_id = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True
    )

    mpesa_code = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True
    )

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


    @property
    def display_message(self):
        """
        Returns a readable description for the transaction.
        Uses result_desc if set, otherwise generates default.
        """
        if self.result_desc:
            return self.result_desc
        # Default messages based on tx_type
        if self.tx_type == "withdraw":
            return f"Withdrawal of KES {self.amount}"
        if self.tx_type == "deposit":
            return f"Deposit of KES {self.amount}"
        if self.tx_type == "invest":
            return f"Investment of KES {self.amount}"
        if self.tx_type == "referral":
            return f"Referral bonus of KES {self.amount}"
        if self.tx_type == "investment_return":
            return f"Investment return of KES {self.amount}"
        return "Transaction processed"

    # ======================
    # METHODS
    # ======================
    def mark_completed(self):
        self.status = "completed"
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "completed_at"])

    def is_credit(self):
        return self.tx_type in ["deposit", "referral", "investment_return"]

    def signed_amount(self):
        return self.amount if self.is_credit() else -self.amount

    def __str__(self):
        return f"{self.tx_type} - {self.amount} KES - {self.status}"

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

    @property
    def balance(self):
        credits = LedgerEntry.objects.filter(
            user=self.user,
            is_credit=True
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

        debits = LedgerEntry.objects.filter(
            user=self.user,
            is_credit=False
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

        return credits - debits


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_wallet(sender, instance, created, **kwargs):
    if created:
        Wallet.objects.create(user=instance)



# =========================
# COMPANY ACCOUNTS
# =========================

class CompanyAccount(models.Model):

    ACCOUNT_TYPES = [
        ("reserve", "Reserve"),
        ("system", "System"),
        ("pool", "Investment Pool"),
    ]

    name = models.CharField(max_length=100)
    account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPES)
    invested_today = models.DecimalField(max_digits=20, decimal_places=2, default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.account_type})"

    # =========================
    # LEDGER BALANCE (REAL SOURCE OF TRUTH)
    # =========================
    @property
    def balance(self):
        credits = LedgerEntry.objects.filter(
            account=self,
            is_credit=True
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

        debits = LedgerEntry.objects.filter(
            account=self,
            is_credit=False
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

        return credits - debits

    # =========================
    # POST TRANSACTION ENGINE
    # =========================
    @staticmethod
    def post_transaction(tx):
        """
        Creates LedgerEntries for a transaction, linking to company accounts
        and ensuring Wallet reflects the user's balance correctly.
        """
        try:
            reserve = CompanyAccount.objects.get(account_type="reserve")
            system = CompanyAccount.objects.get(account_type="system")
            pool = CompanyAccount.objects.get(account_type="pool")
        except CompanyAccount.DoesNotExist as e:
            raise ValueError(f"Required company account missing: {e}")

        amount = tx.amount

        if tx.tx_type == "deposit":
            # User wallet entry
            LedgerEntry.objects.create(
                user=tx.user,       # Only this one affects wallet
                account=reserve,
                tx_type="deposit",
                amount=amount,
                is_credit=True
            )

            # Only company accounting, no user
            LedgerEntry.objects.create(
                user=None,
                account=system,
                tx_type="deposit",
                amount=amount,
                is_credit=True
            )

        elif tx.tx_type == "withdraw":
            LedgerEntry.objects.create(
                user=tx.user,
                account=reserve,
                tx_type="withdraw",
                amount=amount,
                is_credit=False
            )
            LedgerEntry.objects.create(
                user=None,
                account=system,
                tx_type="withdraw",
                amount=amount,
                is_credit=False
            )

        elif tx.tx_type == "invest":
            LedgerEntry.objects.create(
                user=None,
                account=system,
                tx_type="invest",
                amount=amount,
                is_credit=False
            )
            LedgerEntry.objects.create(
                user=None,
                account=pool,
                tx_type="invest",
                amount=amount,
                is_credit=True
            )

        elif tx.tx_type == "investment_return":
            LedgerEntry.objects.create(
                user=None,
                account=pool,
                tx_type="investment_return",
                amount=amount,
                is_credit=False
            )
            LedgerEntry.objects.create(
                user=tx.user,   # Only the system-to-user return affects wallet
                account=system,
                tx_type="investment_return",
                amount=amount,
                is_credit=True
            )

        else:
            raise ValueError(f"Unknown transaction type: {tx.tx_type}")
        
    # In your CompanyAccount model or a transaction handler
    @staticmethod
    def post_referral_bonus(referrer, amount, referred_user):
        """
        Credit the referral bonus to the referrer's wallet via LedgerEntry.
        """
        try:
            reserve = CompanyAccount.objects.get(account_type="reserve")
            system = CompanyAccount.objects.get(account_type="system")
        except CompanyAccount.DoesNotExist as e:
            raise ValueError(f"Required company account missing: {e}")

        # Create ledger entries
        LedgerEntry.objects.create(
            user=referrer,          # affects wallet
            account=reserve,        # where user funds are stored
            tx_type="referral_bonus",
            amount=amount,
            is_credit=True,
            metadata=f"Referral bonus from {referred_user.username}"
        )

        LedgerEntry.objects.create(
            user=None,              # company bookkeeping only
            account=system,
            tx_type="referral_bonus",
            amount=amount,
            is_credit=False,
            metadata=f"Referral bonus for {referrer.username}"
        )

  
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
    

    from django.conf import settings



class SystemState(models.Model):
    last_reset = models.DateField(default=timezone.now)




class LedgerEntry(models.Model):
    ENTRY_TYPES = [
        ("deposit", "Deposit"),
        ("withdraw", "Withdraw"),
        ("invest", "Invest"),
        ("investment_return", "Investment Return"),
        ("fee", "Fee"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True)
    account = models.ForeignKey("CompanyAccount", on_delete=models.CASCADE)
    phone_number = models.CharField(max_length=20, null=True, blank=True)
    tx_type = models.CharField(max_length=30, choices=ENTRY_TYPES)
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    is_credit = models.BooleanField(default=False)  # money in/out
    reference = models.CharField(max_length=100, null=True, blank=True)
    metadata = models.TextField(null=True, blank=True)


