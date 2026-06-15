from decimal import Decimal
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .admin_services import AdminTransactionError, create_admin_transaction
from .models import CompanyAccount, InvestmentTracking, LedgerEntry, Transaction, Wallet
from user.utils import mature_due_investments


class AdminTransactionCreationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="client",
            email="client@example.com",
            password="test-pass",
            phone="254700000000",
        )
        self.admin = get_user_model().objects.create_user(
            username="admin",
            email="admin@example.com",
            password="test-pass",
            is_staff=True,
        )
        self.reserve = CompanyAccount.objects.create(name="Reserve", account_type="reserve")
        self.system = CompanyAccount.objects.create(name="System", account_type="system")
        self.pool = CompanyAccount.objects.create(name="Pool", account_type="pool")

    def test_admin_deposit_posts_to_existing_ledger_path_once(self):
        tx = create_admin_transaction(
            user=self.user,
            tx_type="deposit",
            amount=Decimal("500.00"),
            note="Cash correction",
            admin_user=self.admin,
        )

        self.assertEqual(tx.status, "completed")
        self.assertEqual(tx.tx_type, "deposit")
        self.assertEqual(Wallet.objects.get(user=self.user).balance, Decimal("500.00"))
        self.assertEqual(
            LedgerEntry.objects.filter(user=self.user, tx_type="deposit", is_credit=True).count(),
            1,
        )
        self.assertEqual(self.reserve.balance, Decimal("500.00"))
        self.assertEqual(self.system.balance, Decimal("500.00"))

    def test_admin_withdrawal_debits_wallet_once(self):
        create_admin_transaction(
            user=self.user,
            tx_type="deposit",
            amount=Decimal("500.00"),
            admin_user=self.admin,
        )

        tx = create_admin_transaction(
            user=self.user,
            tx_type="withdraw",
            amount=Decimal("200.00"),
            note="Manual payout",
            admin_user=self.admin,
        )

        self.assertEqual(tx.status, "completed")
        self.assertEqual(Wallet.objects.get(user=self.user).balance, Decimal("300.00"))
        self.assertEqual(
            LedgerEntry.objects.filter(user=self.user, tx_type="withdraw", is_credit=False).count(),
            1,
        )

    def test_admin_withdrawal_rejects_insufficient_balance(self):
        with self.assertRaisesMessage(AdminTransactionError, "Insufficient user wallet balance."):
            create_admin_transaction(
                user=self.user,
                tx_type="withdraw",
                amount=Decimal("1.00"),
                admin_user=self.admin,
            )

        self.assertFalse(Transaction.objects.exists())
        self.assertEqual(Wallet.objects.get(user=self.user).balance, Decimal("0"))

    def test_admin_withdrawal_checks_wallet_not_reserve_liquidity(self):
        LedgerEntry.objects.create(
            user=self.user,
            account=self.system,
            tx_type="deposit",
            amount=Decimal("500.00"),
            is_credit=True,
            reference="SYSTEM-WALLET-CREDIT",
        )

        tx = create_admin_transaction(
            user=self.user,
            tx_type="withdraw",
            amount=Decimal("500.00"),
            admin_user=self.admin,
        )

        self.assertEqual(tx.status, "completed")
        self.assertEqual(Wallet.objects.get(user=self.user).balance, Decimal("0.00"))
        self.assertEqual(self.reserve.balance, Decimal("0"))

    def test_company_account_balance_never_displays_negative(self):
        LedgerEntry.objects.create(
            user=None,
            account=self.pool,
            tx_type="investment_return",
            amount=Decimal("100.00"),
            is_credit=False,
            reference="POOL-NEGATIVE",
        )

        self.assertEqual(self.pool.raw_balance, Decimal("-100.00"))
        self.assertEqual(self.pool.balance, Decimal("0"))

    def test_admin_investment_matches_user_investment_records(self):
        create_admin_transaction(
            user=self.user,
            tx_type="deposit",
            amount=Decimal("500.00"),
            admin_user=self.admin,
        )

        tx = create_admin_transaction(
            user=self.user,
            tx_type="invest",
            amount=Decimal("150.00"),
            note="Manual investment",
            admin_user=self.admin,
        )

        self.assertEqual(tx.status, "completed")
        self.assertEqual(Wallet.objects.get(user=self.user).balance, Decimal("350.00"))
        self.assertTrue(
            InvestmentTracking.objects.filter(user=self.user, amount=Decimal("150.00")).exists()
        )
        self.assertEqual(
            LedgerEntry.objects.filter(user=self.user, tx_type="invest", is_credit=False).count(),
            1,
        )
        self.pool.refresh_from_db()
        self.assertEqual(self.pool.invested_today, Decimal("150.00"))

    def test_maturity_credits_daily_profit_without_unlocking_principal(self):
        investment = InvestmentTracking.objects.create(
            user=self.user,
            amount=Decimal("2500.00"),
            interest_rate=Decimal("0.025"),
            invested_at=timezone.now() - timedelta(days=1, minutes=1),
        )

        credited = mature_due_investments(self.user)
        investment.refresh_from_db()

        self.assertEqual(credited, Decimal("62.50"))
        self.assertFalse(investment.is_redeemed)
        self.assertEqual(Wallet.objects.get(user=self.user).balance, Decimal("62.50"))
        self.assertTrue(Transaction.objects.filter(checkout_id=f"PROFIT-{investment.id}-1").exists())
        self.assertFalse(Transaction.objects.filter(checkout_id=f"PRINCIPAL-{investment.id}").exists())

    def test_maturity_returns_principal_after_week_without_duplicates(self):
        investment = InvestmentTracking.objects.create(
            user=self.user,
            amount=Decimal("2500.00"),
            interest_rate=Decimal("0.025"),
            invested_at=timezone.now() - timedelta(days=7, minutes=1),
        )

        credited = mature_due_investments(self.user)
        credited_again = mature_due_investments(self.user)
        investment.refresh_from_db()

        self.assertEqual(credited, Decimal("2937.50"))
        self.assertEqual(credited_again, Decimal("0"))
        self.assertTrue(investment.is_redeemed)
        self.assertEqual(Wallet.objects.get(user=self.user).balance, Decimal("2937.50"))
        self.assertEqual(
            Transaction.objects.filter(checkout_id__startswith=f"PROFIT-{investment.id}-").count(),
            7,
        )
        self.assertEqual(Transaction.objects.filter(checkout_id=f"PRINCIPAL-{investment.id}").count(), 1)

    @override_settings(TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID="")
    def test_admin_action_button_completes_pending_withdrawal(self):
        create_admin_transaction(
            user=self.user,
            tx_type="deposit",
            amount=Decimal("500.00"),
            admin_user=self.admin,
        )
        LedgerEntry.objects.create(
            user=self.user,
            account=self.reserve,
            tx_type="withdraw",
            amount=Decimal("500.00"),
            is_credit=False,
        )
        tx = Transaction.objects.create(
            user=self.user,
            tx_type="withdraw",
            amount=Decimal("500.00"),
            status="pending",
            checkout_id="WITHDRAW-1",
        )

        self.client.force_login(self.admin)
        url = reverse("admin:finance_transaction_complete_withdrawal", args=[tx.id])

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.get(url)

        tx.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(tx.status, "completed")
        self.assertIsNotNone(tx.completed_at)
        self.assertEqual(Wallet.objects.get(user=self.user).balance, Decimal("0.00"))
        self.assertEqual(
            LedgerEntry.objects.filter(
                user=None,
                account=self.system,
                tx_type="withdraw",
                is_credit=False,
            ).count(),
            1,
        )

    @override_settings(TELEGRAM_BOT_TOKEN="token", TELEGRAM_CHAT_ID="chat")
    @patch("finance.notifications.send_telegram_message", return_value=True)
    def test_telegram_tracks_created_and_status_changed_transactions(self, send_message):
        with self.captureOnCommitCallbacks(execute=True):
            tx = Transaction.objects.create(
                user=self.user,
                tx_type="invest",
                amount=Decimal("100.00"),
                status="completed",
                checkout_id="INVEST-1",
            )

        self.assertEqual(send_message.call_count, 1)
        self.assertIn("Investment", send_message.call_args.args[0])

        send_message.reset_mock()
        tx.status = "failed"
        tx.result_desc = "Admin correction"

        with self.captureOnCommitCallbacks(execute=True):
            tx.save(update_fields=["status", "result_desc"])

        self.assertEqual(send_message.call_count, 1)
        message = send_message.call_args.args[0]
        self.assertIn("Transaction Status Updated", message)
        self.assertIn("Failed", message)
