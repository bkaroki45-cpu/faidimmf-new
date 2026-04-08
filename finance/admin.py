from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html
from django.utils.timezone import localdate
from django.db.models import Sum
from .models import CompanyAccount
from datetime import timedelta
from django.utils import timezone
from .models import Wallet, Transaction, InvestmentTracking, CompanyAccount
from user.models import CustomUser, TransactionPIN
from django.contrib.admin import SimpleListFilter
from finance.models import LedgerEntry



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

    def queryset(self, request, queryset):
        if self.value():
            days = int(self.value())
            start = timezone.now() - timedelta(days=days)
            return queryset.filter(created_at__gte=start)
        return queryset

# =========================
# COMPANY ACCOUNT ADMIN (FIXED - SINGLE VERSION ONLY)
@admin.register(CompanyAccount)
class CompanyAccountAdmin(admin.ModelAdmin):
    actions = ["sync_accounts"] 

    list_display = (
        "name",
        "account_type",
        "display_real_balance",
        "display_system_balance",
        "display_pool_invested",
        "display_pool_matured",
        "created_at",
    )

    def display_real_balance(self, obj):

        if obj.account_type != "reserve":
            return "—"

        credits = LedgerEntry.objects.filter(
            account=obj,
            is_credit=True
        ).aggregate(total=Sum("amount"))["total"] or 0

        debits = LedgerEntry.objects.filter(
            account=obj,
            is_credit=False
        ).aggregate(total=Sum("amount"))["total"] or 0

        return credits - debits

    def display_system_balance(self, obj):
        total_credit = LedgerEntry.objects.filter(
            account=obj,
            is_credit=True
        ).aggregate(total=Sum("amount"))["total"] or 0

        total_debit = LedgerEntry.objects.filter(
            account=obj,
            is_credit=False
        ).aggregate(total=Sum("amount"))["total"] or 0

        return total_credit - total_debit

    def display_pool_invested(self, obj):
        total = LedgerEntry.objects.filter(
            account=obj,
            tx_type="invest",
            is_credit=True
        ).aggregate(total=Sum("amount"))["total"] or 0

        return total

    def display_pool_matured(self, obj):
        total = LedgerEntry.objects.filter(
            account=obj,
            tx_type="investment_return",
            is_credit=True
        ).aggregate(total=Sum("amount"))["total"] or 0

        return total
# =========================
# TRANSACTION ADMIN
# =========================
@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'tx_type', 'amount', 'status_badge', 'timestamp')

    def status_badge(self, obj):
        color = {
            'pending': '#f59e0b',
            'completed': '#10b981',
            'failed': '#ef4444'
        }.get(obj.status.lower(), '#6b7280')

        return render_badge(color, obj.status)

    status_badge.short_description = 'Status'

    def changelist_view(self, request, extra_context=None):
        qs = Transaction.objects.filter(status__iexact='completed')

        today = localdate()
        month_qs = qs.filter(timestamp__year=today.year, timestamp__month=today.month)
        today_qs = qs.filter(timestamp__date=today)

        extra_context = extra_context or {}
        extra_context.update({
            "total_deposited_today": today_qs.filter(tx_type='deposit').aggregate(Sum('amount'))['amount__sum'] or 0,
            "total_withdrawn_today": today_qs.filter(tx_type='withdraw').aggregate(Sum('amount'))['amount__sum'] or 0,
            "total_deposited_month": month_qs.filter(tx_type='deposit').aggregate(Sum('amount'))['amount__sum'] or 0,
            "total_withdrawn_month": month_qs.filter(tx_type='withdraw').aggregate(Sum('amount'))['amount__sum'] or 0,
        })

        return super().changelist_view(request, extra_context=extra_context)


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