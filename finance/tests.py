from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from .admin_services import AdminTransactionError, create_admin_transaction
from .models import CompanyAccount, InvestmentTracking, LedgerEntry, Transaction, Wallet


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
