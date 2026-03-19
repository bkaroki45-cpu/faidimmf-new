from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html
from .models import Wallet, Transaction, InvestmentTracking, CompanyAccount
from user.models import CustomUser, TransactionPIN
from django.utils.timezone import now, localdate

from django.db.models import Sum
from django.utils.html import format_html

# ------------------------------
# INLINES WITH BADGES
# ------------------------------

class WalletInline(admin.StackedInline):
    model = Wallet
    readonly_fields = ('balance',)
    can_delete = False
    verbose_name_plural = "Wallet"
    classes = ('collapse',)


class TransactionPINInline(admin.StackedInline):
    model = TransactionPIN
    readonly_fields = ('created_at', 'pin_status')
    can_delete = False
    verbose_name_plural = "Transaction PIN"
    classes = ('collapse',)

    def pin_status(self, obj):
        return "Set" if obj.pin else "Not Set"
    pin_status.short_description = "PIN Status"


class TransactionInline(admin.TabularInline):
    model = Transaction
    fields = ('amount', 'tx_type', 'status_badge', 'checkout_id', 'timestamp')
    readonly_fields = ('amount', 'tx_type', 'status_badge', 'checkout_id', 'timestamp')
    extra = 0
    can_delete = False
    verbose_name_plural = "Transactions"
    classes = ('collapse',)

    def status_badge(self, obj):
        color = {
            'pending': 'orange',
            'completed': 'green',
            'failed': 'red'
        }.get(obj.status.lower(), 'gray')
        return format_html('<span style="color: {};">{}</span>', color, obj.status)
    status_badge.short_description = 'Status'


class InvestmentInline(admin.TabularInline):
    model = InvestmentTracking
    fields = ('amount', 'interest_rate', 'invested_at', 'maturity_date', 'is_redeemed', 'status_badge')
    readonly_fields = ('amount', 'interest_rate', 'invested_at', 'maturity_date', 'is_redeemed', 'status_badge')
    extra = 0
    can_delete = False
    verbose_name_plural = "Investments"
    classes = ('collapse',)

    @admin.display(description='Status')
    def status_badge(self, obj):
        if obj.is_redeemed:
            color, label = 'gray', 'Redeemed'
        elif obj.is_matured():
            color, label = 'green', 'Matured'
        else:
            color, label = 'blue', 'Active'

        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            label
        )


# ------------------------------
# CUSTOM USER ADMIN
# ------------------------------
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


# ------------------------------
# COMPANY ACCOUNT ADMIN
# ------------------------------
@admin.register(CompanyAccount)
class CompanyAccountAdmin(admin.ModelAdmin):
    list_display = ('name', 'account_type', 'balance', 'created_at', 'updated_at')
    list_filter = ('account_type',)
    search_fields = ('name', 'account_type')
    readonly_fields = ('created_at', 'updated_at')


# ------------------------------
# TRANSACTION ADMIN (STANDALONE)
# ------------------------------
@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'tx_type', 'amount', 'status', 'timestamp', 'status_badge')

    def status_badge(self, obj):
        color = {
            'pending': 'orange',
            'completed': 'green',
            'failed': 'red'
        }.get(obj.status.lower(), 'gray')
        return format_html('<span style="color: {};">{}</span>', color, obj.status)
    status_badge.short_description = 'Status'

    def changelist_view(self, request, extra_context=None):
        # Use all transactions (not filtered by admin queryset)
        qs = Transaction.objects.all()

        # Use localdate() to avoid timezone issues
        today = localdate()
        current_month = today.month
        current_year = today.year

        # Filter transactions for today
        today_qs = qs.filter(timestamp__date=today)
        total_deposited_today = today_qs.filter(tx_type__iexact='deposit').aggregate(Sum('amount'))['amount__sum'] or 0
        total_withdrawn_today = today_qs.filter(tx_type__iexact='withdraw').aggregate(Sum('amount'))['amount__sum'] or 0

        # Filter transactions for this month
        month_qs = qs.filter(timestamp__year=current_year, timestamp__month=current_month)
        total_deposited_month = month_qs.filter(tx_type__iexact='deposit').aggregate(Sum('amount'))['amount__sum'] or 0
        total_withdrawn_month = month_qs.filter(tx_type__iexact='withdraw').aggregate(Sum('amount'))['amount__sum'] or 0

        # Pass totals to template
        extra_context = extra_context or {}
        extra_context.update({
            'total_deposited_today': total_deposited_today,
            'total_withdrawn_today': total_withdrawn_today,
            'total_deposited_month': total_deposited_month,
            'total_withdrawn_month': total_withdrawn_month,
        })

        return super().changelist_view(request, extra_context=extra_context)
# ------------------------------
# INVESTMENT ADMIN (STANDALONE)
# ------------------------------
@admin.register(InvestmentTracking)
class InvestmentTrackingAdmin(admin.ModelAdmin):
    list_display = ('user', 'amount', 'status_badge', 'invested_at', 'maturity_date', 'is_redeemed')

    @admin.display(description='Status')
    def status_badge(self, obj):
        if obj.is_redeemed:
            return format_html('<span style="color: gray; font-weight: bold;">Redeemed</span>')
        elif obj.is_matured():
            return format_html('<span style="color: green; font-weight: bold;">Matured</span>')
        else:
            return format_html('<span style="color: blue; font-weight: bold;">Active</span>')


# ------------------------------
# WALLET ADMIN (STANDALONE)
# ------------------------------
@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ('user', 'balance')
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('user', 'balance')


# ------------------------------
# TRANSACTION PIN ADMIN (STANDALONE)
# ------------------------------
@admin.register(TransactionPIN)
class TransactionPINAdmin(admin.ModelAdmin):
    list_display = ('user', 'created_at', 'pin_status')
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('created_at',)

    def pin_status(self, obj):
        return "Set" if obj.pin else "Not Set"
    pin_status.short_description = "PIN Status"