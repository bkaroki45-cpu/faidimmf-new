







from django.contrib.admin import SimpleListFilter, ModelAdmin

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html
from django.db.models import Sum
from django.utils import timezone
from datetime import timedelta

from .models import Wallet, Transaction, InvestmentTracking, CompanyAccount
from user.models import CustomUser, TransactionPIN
from finance.models import LedgerEntry
from user.utils import process_maturity, get_wallet_balance



# =========================
# BADGE HELPER
# =========================
def render_badge(color, label):
    return format_html(
        '<span style="background-color:{}; color:white; padding:4px 10px; border-radius:12px; font-size:12px; font-weight:bold;">{}</span>',
        color,
        label
    )


# =========================
# INLINES
# =========================
class WalletInline(admin.StackedInline):
    model = Wallet
    readonly_fields = ('balance',)
    can_delete = False
    verbose_name_plural = "Wallet"
    classes = ('collapse',)


class TransactionPINInline(admin.StackedInline):
    model = TransactionPIN
    readonly_fields = ('created_at',)
    can_delete = False
    verbose_name_plural = "Transaction PIN"
    classes = ('collapse',)


class TransactionInline(admin.TabularInline):
    model = Transaction
    fk_name = "user"
    fields = ('amount', 'tx_type', 'status_badge', 'checkout_id', 'timestamp')
    readonly_fields = fields
    extra = 0
    can_delete = False
    classes = ('collapse',)

    def status_badge(self, obj):
        color = {
            'pending': '#f59e0b',
            'completed': '#10b981',
            'failed': '#ef4444'
        }.get(obj.status.lower(), '#6b7280')

        return render_badge(color, obj.status)

    status_badge.short_description = 'Status'


class InvestmentInline(admin.TabularInline):
    model = InvestmentTracking
    fk_name = "user"
    fields = ('amount', 'interest_rate', 'invested_at', 'maturity_date', 'is_redeemed', 'status_badge')
    readonly_fields = fields
    extra = 0
    can_delete = False
    classes = ('collapse',)

    def status_badge(self, obj):
        if obj.is_redeemed:
            return render_badge('#6b7280', 'Redeemed')
        elif obj.is_matured():
            return render_badge('#10b981', 'Matured')
        return render_badge('#3b82f6', 'Active')


# =========================
# CUSTOM USER ADMIN
# =========================
@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'phone', 'is_staff', 'is_active')
    search_fields = ('username', 'email', 'phone')
    list_filter = ('is_staff', 'is_superuser', 'is_active')

    fieldsets = (
        (None, {'fields': ('username', 'email', 'password', 'phone')}),
        ('Permissions', {'fields': ('is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )

    inlines = [WalletInline, TransactionPINInline, TransactionInline, InvestmentInline]


class DaysFilter(SimpleListFilter):
    title = "Report Period"
    parameter_name = "days"

    def lookups(self, request, model_admin):
        return (
            ("1", "Today"),
            ("2", "2 Days"),
            ("3", "3 Days"),
            ("7", "7 Days"),
        )

   

# =========================
# COMPANY ACCOUNT ADMIN (FIXED - SINGLE VERSION ONLY)
@admin.register(CompanyAccount)
class CompanyAccountAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "account_type",
        "display_balance",
        "created_at",
    )

    def get_queryset(self, request):
        """
        Only show 'reserve' and 'pool' accounts in admin
        """
        qs = super().get_queryset(request)
        return qs.filter(account_type__in=["reserve", "pool"])

    def display_balance(self, obj):

        if obj.account_type == "reserve":

            credits = LedgerEntry.objects.filter(
                account=obj,
                is_credit=True
            ).aggregate(total=Sum("amount"))["total"] or 0

            debits = LedgerEntry.objects.filter(
                account=obj,
                is_credit=False
            ).aggregate(total=Sum("amount"))["total"] or 0

            return credits - debits


        elif obj.account_type == "pool":

            # ✅ ACTIVE INVESTMENTS ONLY (NOT LEDGER)
            active = InvestmentTracking.objects.filter(
                is_redeemed=False
            ).aggregate(total=Sum("amount"))["total"] or 0

            return active

        



@admin.action(description="Mark withdrawals as PAID")
def mark_withdrawal_paid(self, request, queryset):

    for tx in queryset:

        if tx.tx_type != "withdraw" or tx.status != "pending":
            continue

        tx.status = "completed"
        tx.result_desc = "Paid manually via M-Pesa"
        tx.completed_at = timezone.now()
        tx.save()
# =========================
# TRANSACTION ADMIN
# =========================
@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):

    list_display = (
        'id',
        'user',
        'phone_number',
        'wallet_balance',
        'tx_type',
        'amount',
        'status_badge',
        'timestamp',
        'action_buttons'
    )

    list_filter = ('tx_type', 'status')
    search_fields = ('user__username', 'user__phone')

    actions = ['mark_withdrawal_paid', 'reject_withdrawals']

    # -----------------------
    # PHONE NUMBER
    # -----------------------
    def phone_number(self, obj):
        return obj.user.phone if hasattr(obj.user, 'phone') else "No phone"
    phone_number.short_description = "Phone"

    # -----------------------
    # WALLET BALANCE
    # -----------------------
    def wallet_balance(self, obj):
        return get_wallet_balance(obj.user)

    # -----------------------
    # STATUS BADGE (KEEP YOUR STYLE)
    # -----------------------
    def status_badge(self, obj):
        color = {
            'pending': '#f59e0b',
            'completed': '#10b981',
            'failed': '#ef4444'
        }.get(obj.status.lower(), '#6b7280')

        return render_badge(color, obj.status)

    status_badge.short_description = 'Status'

    # -----------------------
    # ACTION BUTTONS
    # -----------------------
    def action_buttons(self, obj):
        return format_html(
            '<a href="{}">View</a> | <a href="{}">Edit</a>',
            f"/admin/finance/transaction/{obj.id}/change/",
            f"/admin/finance/transaction/{obj.id}/change/",
        )

    action_buttons.short_description = "Actions"

    # -----------------------
    # APPROVE WITHDRAWAL (MARK PAID)
    # ---------------------

            # -----------------------
            # SAFETY CHECKS
            
    @admin.action(description="Mark selected withdrawals as PAID")
    def mark_withdrawal_paid(self, request, queryset):

        reserve_account = CompanyAccount.objects.filter(account_type="reserve").first()

        for tx in queryset:
            if tx.tx_type != "withdraw" or tx.status != "pending":
                continue

            wallet = Wallet.objects.filter(user=tx.user).first()
            if not wallet:
                continue

            amount = tx.amount

            if get_wallet_balance() < amount:
                continue

            if reserve_account.balance < amount:
                continue

            # ✅ 1. Deduct wallet
            
            wallet.save()

            # ✅ 2. Deduct reserve
            reserve_account.balance -= amount
            reserve_account.save()

            # ✅ 3. Mark transaction
            tx.status = "completed"
            tx.completed_at = timezone.now()
            tx.save()

            # ✅ 4. IMPORTANT: ledger sync
            CompanyAccount.post_transaction(tx)



# =========================
# INVESTMENT ADMIN
# =========================
@admin.register(InvestmentTracking)
class InvestmentTrackingAdmin(admin.ModelAdmin):
    list_display = ('user', 'amount', 'status_badge', 'invested_at', 'maturity_date', 'is_redeemed')

    def status_badge(self, obj):
        if obj.is_redeemed:
            return render_badge('#6b7280', 'Redeemed')
        elif obj.is_matured():
            return render_badge('#10b981', 'Matured')
        return render_badge('#3b82f6', 'Active')


# =========================
# WALLET ADMIN
# =========================
@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ('user', 'balance')
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('user', 'balance')


# =========================
# PIN ADMIN
# =========================
@admin.register(TransactionPIN)
class TransactionPINAdmin(admin.ModelAdmin):
    list_display = ('user', 'created_at', 'pin_status')
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('created_at',)

    def pin_status(self, obj):
        return "Set" if obj.pin else "Not Set"

    pin_status.short_description = "PIN Status"


@admin.action(description="Sync selected accounts")
def sync_accounts(modeladmin, request, queryset):
    for acc in queryset:
        acc.sync_from_transactions()

def get_queryset(self, request):
    qs = super().get_queryset(request)
    for obj in qs:
        obj.sync_from_transactions()
    return qs

