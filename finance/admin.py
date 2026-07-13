from django.contrib import admin
from django import forms
from django.contrib import messages
from django.contrib.auth.admin import UserAdmin
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.timezone import localdate
from django.db import transaction as db_transaction
from django.db.models import Sum
from .models import CompanyAccount
from datetime import timedelta
from decimal import Decimal
from django.utils import timezone
from .models import Wallet, Transaction, InvestmentTracking, CompanyAccount
from user.models import CustomUser, ReferralRelationship, TransactionPIN
from django.contrib.admin import SimpleListFilter
from finance.models import LedgerEntry
from .admin_services import AdminTransactionError, create_admin_transaction
from user.utils import unlock_investment_principal


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

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class TransactionPINInline(admin.StackedInline):
    model = TransactionPIN
    readonly_fields = ('created_at',)
    can_delete = False
    verbose_name_plural = "Transaction PIN"
    classes = ('collapse',)


class TransactionInline(admin.TabularInline):
    model = Transaction
    fk_name = "user"
    fields = ('amount', 'tx_type', 'status_badge', 'origin', 'created_by_admin', 'checkout_id', 'timestamp')
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
    fields = ('amount', 'interest_rate', 'term_days', 'invested_at', 'maturity_date', 'is_redeemed', 'status_badge')
    readonly_fields = fields
    extra = 0
    can_delete = False
    classes = ('collapse',)

    def status_badge(self, obj):
        if obj.is_redeemed:
            return render_badge('#6b7280', 'Principal returned')
        elif not obj.maturity_date:
            return render_badge('#f59e0b', 'Missing maturity date')
        elif obj.is_matured():
            return render_badge('#10b981', 'Principal due')
        return render_badge('#3b82f6', 'Active')


class ReferralInline(admin.TabularInline):
    model = CustomUser
    fk_name = "referred_by"
    fields = ("username", "email", "phone", "date_joined", "is_active")
    readonly_fields = fields
    extra = 0
    can_delete = False
    verbose_name = "Referred user"
    verbose_name_plural = "Users referred by this account"
    classes = ("collapse",)

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


# =========================
# CUSTOM USER ADMIN
# =========================
@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = (
        'username',
        'email',
        'phone',
        'referred_by_user',
        'referrals_count',
        'is_staff',
        'is_superuser',
        'is_active',
    )
    search_fields = (
        'username',
        'email',
        'phone',
        'referral_code',
        'referred_by__username',
        'referred_by__email',
        'referred_by__referral_code',
    )
    list_filter = ('is_staff', 'is_superuser', 'is_active', 'groups', 'referred_by')
    readonly_fields = ('last_login', 'date_joined', 'referral_code')
    autocomplete_fields = ('referred_by',)
    actions = ("suspend_users", "unsuspend_users")

    fieldsets = (
        (None, {'fields': ('username', 'email', 'password', 'phone', 'referral_code', 'referred_by')}),
        ('Permissions', {'fields': ('is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )

    inlines = [WalletInline, TransactionPINInline, ReferralInline, TransactionInline, InvestmentInline]

    user_owned_delete_models = {
        "wallet",
        "transaction",
        "investment tracking",
        "transaction pin",
        "password reset otp",
    }

    def has_view_permission(self, request, obj=None):
        return super().has_view_permission(request, obj) or request.user.has_perm("user.delete_customuser")

    def has_delete_permission(self, request, obj=None):
        if obj and obj == request.user:
            return False
        if obj and not request.user.is_superuser and (obj.is_staff or obj.is_superuser):
            return False
        return super().has_delete_permission(request, obj)

    def get_deleted_objects(self, objs, request):
        deleted_objects, model_count, perms_needed, protected = super().get_deleted_objects(objs, request)

        if request.user.has_perm("user.delete_customuser"):
            perms_needed = {
                perm
                for perm in perms_needed
                if perm.lower() not in self.user_owned_delete_models
            }

        return deleted_objects, model_count, perms_needed, protected

    def delete_queryset(self, request, queryset):
        if not request.user.is_superuser:
            queryset = queryset.filter(is_staff=False, is_superuser=False).exclude(pk=request.user.pk)
        super().delete_queryset(request, queryset)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('referred_by').prefetch_related('referrals')

    def referred_by_user(self, obj):
        if not obj.referred_by:
            return "-"
        url = reverse("admin:user_customuser_change", args=[obj.referred_by_id])
        return format_html('<a href="{}">{}</a>', url, obj.referred_by.username)

    referred_by_user.short_description = "Referred by"
    referred_by_user.admin_order_field = "referred_by__username"

    def referrals_count(self, obj):
        return obj.referrals.count()

    referrals_count.short_description = "Referrals"

    @admin.action(description="Suspend selected users")
    def suspend_users(self, request, queryset):
        queryset = queryset.exclude(pk=request.user.pk)
        if not request.user.is_superuser:
            queryset = queryset.filter(is_staff=False, is_superuser=False)
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} user(s) suspended.")

    @admin.action(description="Unsuspend selected users")
    def unsuspend_users(self, request, queryset):
        if not request.user.is_superuser:
            queryset = queryset.filter(is_staff=False, is_superuser=False)
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} user(s) unsuspended.")


@admin.register(ReferralRelationship)
class ReferralRelationshipAdmin(admin.ModelAdmin):
    list_display = (
        "referred_user",
        "referred_user_code",
        "referred_by_user",
        "referrer_code",
        "date_joined",
        "is_active",
    )
    search_fields = (
        "username",
        "email",
        "phone",
        "referral_code",
        "referred_by__username",
        "referred_by__email",
        "referred_by__phone",
        "referred_by__referral_code",
    )
    list_filter = ("is_active", "date_joined", "referred_by")
    readonly_fields = (
        "username",
        "email",
        "phone",
        "referral_code",
        "referred_by_link",
        "date_joined",
        "is_active",
    )
    fields = (
        "username",
        "email",
        "phone",
        "referral_code",
        "referred_by_link",
        "date_joined",
        "is_active",
    )
    ordering = ("-date_joined",)

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .filter(referred_by__isnull=False)
            .select_related("referred_by")
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def referred_user(self, obj):
        url = reverse("admin:user_customuser_change", args=[obj.pk])
        return format_html('<a href="{}">{}</a>', url, obj.username)

    referred_user.short_description = "Referred user"
    referred_user.admin_order_field = "username"

    def referred_user_code(self, obj):
        return obj.referral_code

    referred_user_code.short_description = "User code"
    referred_user_code.admin_order_field = "referral_code"

    def referred_by_user(self, obj):
        url = reverse("admin:user_customuser_change", args=[obj.referred_by_id])
        return format_html('<a href="{}">{}</a>', url, obj.referred_by.username)

    referred_by_user.short_description = "Referred by"
    referred_by_user.admin_order_field = "referred_by__username"

    def referrer_code(self, obj):
        return obj.referred_by.referral_code

    referrer_code.short_description = "Referrer code"
    referrer_code.admin_order_field = "referred_by__referral_code"

    def referred_by_link(self, obj):
        return self.referred_by_user(obj)

    referred_by_link.short_description = "Referred by"


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
    list_display = (
        "name",
        "account_type",
        "display_balance",
        "created_at",
    )
    readonly_fields = ("name", "account_type", "invested_today", "created_at", "display_balance")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        """
        Only show 'reserve' and 'pool' accounts in admin
        """
        qs = super().get_queryset(request)
        return qs.filter(account_type__in=["reserve", "pool"])

    def display_balance(self, obj):
        return obj.balance

@admin.action(description="Mark selected withdrawals as PAID")
def mark_withdrawal_paid(self, request, queryset):
    reserve_account = CompanyAccount.objects.get(account_type="reserve")

    for tx in queryset:
        if tx.tx_type != "withdraw" or tx.status != "pending":
            continue

        wallet = Wallet.objects.filter(user=tx.user).first()

        if not wallet:
            continue

        # Prevent double processing
        if tx.status == "completed":
            continue

        amount = tx.amount

        # -----------------------------
        # 1. Deduct from user wallet
        # -----------------------------
        if wallet.balance < amount:
            continue  # skip insufficient balance safety

        wallet.balance -= amount
        wallet.save()

        # -----------------------------
        # 2. Deduct from reserve account
        # -----------------------------
        if reserve_account.balance < amount:
            continue  # avoid negative reserve

        reserve_account.balance -= amount
        reserve_account.save()

        # -----------------------------
        # 3. Mark transaction completed
        # -----------------------------
        tx.status = "completed"
        tx.result_desc = "Paid manually via M-Pesa Till"
        tx.completed_at = timezone.now()
        tx.save()

        # -----------------------------
        # 4. Ledger update (if you use it)
        # -----------------------------
        try:
            CompanyAccount.post_transaction(tx)
        except Exception as e:
            print("Ledger error:", e)
from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils import timezone

from .models import Transaction, Wallet, CompanyAccount


# =========================
# HELPER BADGE
# =========================
def render_badge(color, text):
    return mark_safe(
        f'''
        <span style="
            background:{color};
            color:white;
            padding:4px 10px;
            border-radius:20px;
            font-size:12px;
            font-weight:bold;
        ">
            {text}
        </span>
        '''
    )


# =========================
# TRANSACTION ADMIN
# =========================
class ManualTransactionForm(forms.Form):
    TRANSACTION_TYPES = (
        ("deposit", "Deposit"),
        ("withdraw", "Withdrawal"),
        ("invest", "Investment"),
    )

    tx_type = forms.ChoiceField(
        label="Transaction type",
        choices=TRANSACTION_TYPES,
    )
    user = forms.ModelChoiceField(
        queryset=CustomUser.objects.order_by("username"),
        label="User",
        help_text="Select the user whose wallet/history should receive this transaction.",
    )
    amount = forms.DecimalField(
        max_digits=20,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )
    note = forms.CharField(
        label="Description / note",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    change_list_template = "admin/finance/transaction/change_list.html"

    list_display = (
        'id',
        'user',
        'phone_number',
        'wallet_balance',
        'tx_type',
        'amount',
        'status_badge',
        'origin_badge',
        'created_by_admin',
        'timestamp',
        'action_buttons'
    )

    list_filter = ('tx_type', 'status', 'origin')

    search_fields = (
        'user__username',
        'user__phone',
        'created_by_admin__username',
    )

    actions = [
        'mark_withdrawal_paid',
        'reject_withdrawals'
    ]

    readonly_fields = (
        'user',
        'amount',
        'checkout_id',
        'mpesa_code',
        'conversation_id',
        'originator_conversation_id',
        'phone_number',
        'status',
        'tx_type',
        'reference_user',
        'origin',
        'created_by_admin',
        'result_desc',
        'timestamp',
        'completed_at',
        'wallet_balance',
        'status_badge',
        'action_buttons',
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<int:transaction_id>/complete-withdrawal/",
                self.admin_site.admin_view(self.complete_withdrawal_view),
                name="finance_transaction_complete_withdrawal",
            ),
            path(
                "manual-create/",
                self.admin_site.admin_view(self.manual_create_view),
                name="finance_transaction_manual_create",
            ),
        ]
        return custom_urls + urls

    def complete_withdrawal_view(self, request, transaction_id):
        with db_transaction.atomic():
            tx = Transaction.objects.select_for_update().filter(
                id=transaction_id,
                tx_type="withdraw",
            ).first()

            if not tx:
                messages.error(request, "Withdrawal transaction not found.")
                return redirect(reverse("admin:finance_transaction_changelist"))

            if tx.status != "pending":
                messages.warning(request, "Withdrawal has already been processed.")
                return redirect(reverse("admin:finance_transaction_changelist"))

            tx.status = "completed"
            tx.result_desc = f"Withdrawal paid by admin {request.user.username}"
            tx.completed_at = timezone.now()
            tx.save(update_fields=["status", "result_desc", "completed_at"])

        messages.success(request, "Withdrawal marked as completed.")
        return redirect(reverse("admin:finance_transaction_changelist"))

    def manual_create_view(self, request):
        if request.method == "POST":
            form = ManualTransactionForm(request.POST)
            if form.is_valid():
                try:
                    tx = create_admin_transaction(
                        user=form.cleaned_data["user"],
                        tx_type=form.cleaned_data["tx_type"],
                        amount=form.cleaned_data["amount"],
                        note=form.cleaned_data["note"],
                        admin_user=request.user,
                    )
                except AdminTransactionError as exc:
                    form.add_error(None, str(exc))
                else:
                    messages.success(
                        request,
                        f"Transaction {tx.checkout_id} created successfully.",
                    )
                    return redirect(reverse("admin:finance_transaction_changelist"))
        else:
            form = ManualTransactionForm()

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Create Transaction",
            "form": form,
        }
        return TemplateResponse(
            request,
            "admin/finance/transaction/manual_transaction.html",
            context,
        )

    def changelist_view(self, request, extra_context=None):
        today = localdate()
        month_start = today.replace(day=1)
        completed = Transaction.objects.filter(status="completed")

        totals = {
            "total_deposited_today": completed.filter(
                tx_type="deposit",
                timestamp__date=today,
            ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00"),
            "total_withdrawn_today": completed.filter(
                tx_type="withdraw",
                timestamp__date=today,
            ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00"),
            "total_deposited_month": completed.filter(
                tx_type="deposit",
                timestamp__date__gte=month_start,
            ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00"),
            "total_withdrawn_month": completed.filter(
                tx_type="withdraw",
                timestamp__date__gte=month_start,
            ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00"),
        }
        if extra_context:
            totals.update(extra_context)
        return super().changelist_view(request, extra_context=totals)

    # -----------------------
    # PHONE NUMBER
    # -----------------------
    def phone_number(self, obj):
        return getattr(obj.user, 'phone', 'No phone')

    phone_number.short_description = "Phone"

    # -----------------------
    # WALLET BALANCE
    # -----------------------
    def wallet_balance(self, obj):
        wallet = Wallet.objects.filter(user=obj.user).first()
        return wallet.balance if wallet else 0

    wallet_balance.short_description = "Wallet Balance"

    # -----------------------
    # STATUS BADGE
    # -----------------------
    def status_badge(self, obj):

        color = {
            'pending': '#f59e0b',
            'completed': '#10b981',
            'failed': '#ef4444'
        }.get(obj.status.lower(), '#6b7280')

        return render_badge(color, obj.status)

    status_badge.short_description = "Status"

    def origin_badge(self, obj):
        if obj.origin == "admin_manual":
            admin_name = getattr(obj.created_by_admin, "username", "Unknown admin")
            return render_badge("#7c3aed", f"Manual by {admin_name}")
        return render_badge("#2563eb", "Normal")

    origin_badge.short_description = "Source"

    # -----------------------
    # ACTION BUTTONS
    # -----------------------
    def action_buttons(self, obj):

        if obj.tx_type == "withdraw" and obj.status == "pending":
            url = reverse(
                "admin:finance_transaction_complete_withdrawal",
                args=[obj.id],
            )

            return format_html(
                '<a class="button" href="{}" '
                'style="background:#10b981; color:#fff; padding:5px 10px; '
                'border-radius:4px; font-weight:bold; text-decoration:none;">'
                'Mark Completed</a>',
                url,
            )

        return "—"

    action_buttons.short_description = "Action"

    # =========================
    # MARK WITHDRAWAL AS PAID
    # =========================
    @admin.action(description="Mark selected withdrawals as PAID")
    def mark_withdrawal_paid(self, request, queryset):
        for tx in queryset:

            if tx.tx_type != "withdraw":
                continue

            if tx.status != "pending":
                continue

            wallet = Wallet.objects.filter(
                user=tx.user
            ).first()

            if not wallet:
                continue

            # -----------------------
            # UPDATE TRANSACTION
            # -----------------------
            tx.status = "completed"
            tx.result_desc = f"Paid manually via M-Pesa Till by admin {request.user.username}"
            tx.completed_at = timezone.now()

            tx.save()

            # The withdrawal request already debited the user's wallet when it
            # was created. Approval only marks the transaction as paid.

        self.message_user(
            request,
            "Selected withdrawals marked as paid."
        )

    # =========================
    # REJECT WITHDRAWALS
    # =========================
    @admin.action(description="Reject selected withdrawals")
    def reject_withdrawals(self, request, queryset):

        updated = 0

        for tx in queryset:

            if tx.tx_type == "withdraw" and tx.status == "pending":

                tx.status = "failed"
                tx.result_desc = "Withdrawal rejected"

                tx.save()

                updated += 1

        self.message_user(
            request,
            f"{updated} withdrawal(s) rejected."
        )

# =========================
# INVESTMENT ADMIN
# =========================
@admin.register(InvestmentTracking)
class InvestmentTrackingAdmin(admin.ModelAdmin):
    list_display = (
        'user',
        'amount',
        'term_days',
        'status_badge',
        'invested_at',
        'maturity_date',
        'is_redeemed',
        'action_buttons',
    )
    actions = ('unlock_selected_principal',)
    readonly_fields = (
        'user',
        'amount',
        'interest_rate',
        'term_days',
        'invested_at',
        'maturity_date',
        'is_redeemed',
        'status_badge',
        'action_buttons',
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<int:investment_id>/unlock-principal/",
                self.admin_site.admin_view(self.unlock_principal_view),
                name="finance_investmenttracking_unlock_principal",
            ),
        ]
        return custom_urls + urls

    def status_badge(self, obj):
        if obj.is_redeemed:
            return render_badge('#6b7280', 'Principal returned')
        elif not obj.maturity_date:
            return render_badge('#f59e0b', 'Missing maturity date')
        elif obj.is_matured():
            return render_badge('#10b981', 'Principal due')
        return render_badge('#3b82f6', 'Active')

    def action_buttons(self, obj):
        if obj.is_redeemed:
            return "—"

        url = reverse(
            "admin:finance_investmenttracking_unlock_principal",
            args=[obj.id],
        )
        return format_html(
            '<a class="button" href="{}" '
            'style="background:#f59e0b; color:#111827; padding:5px 10px; '
            'border-radius:4px; font-weight:bold; text-decoration:none;">'
            'Unlock Principal</a>',
            url,
        )

    action_buttons.short_description = "Action"

    def unlock_principal_view(self, request, investment_id):
        investment = InvestmentTracking.objects.select_related("user").filter(id=investment_id).first()

        if not investment:
            messages.error(request, "Investment not found.")
            return redirect(reverse("admin:finance_investmenttracking_changelist"))

        if investment.is_redeemed:
            messages.warning(request, "This investment principal is already in the user's wallet.")
            return redirect(reverse("admin:finance_investmenttracking_changelist"))

        credited = unlock_investment_principal(investment, admin_user=request.user)
        messages.success(
            request,
            f"Unlocked KES {credited} to {investment.user.username}'s wallet.",
        )
        return redirect(reverse("admin:finance_investmenttracking_changelist"))

    @admin.action(description="Unlock selected investment principal to user wallets")
    def unlock_selected_principal(self, request, queryset):
        unlocked = 0
        total = Decimal("0.00")

        for investment in queryset.select_related("user"):
            if investment.is_redeemed:
                continue
            credited = unlock_investment_principal(investment, admin_user=request.user)
            if credited:
                unlocked += 1
                total += credited

        self.message_user(
            request,
            f"Unlocked {unlocked} investment(s), total credited KES {total}.",
        )


# =========================
# WALLET ADMIN
# =========================
@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ('user', 'balance')
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('user', 'balance')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


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


