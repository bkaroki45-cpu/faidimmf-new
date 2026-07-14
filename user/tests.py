from django.test import TestCase
from django.urls import reverse
from unittest.mock import patch
from user.models import CustomUser, PasswordResetOTP, TransactionPIN


class SignupNotificationTests(TestCase):
    @patch("user.views.notify_signup")
    def test_register_sends_signup_notification_after_commit(self, notify_signup):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("user:register"),
                {
                    "username": "newclient",
                    "email": "newclient@example.com",
                    "password1": "StrongPass123!",
                    "password2": "StrongPass123!",
                },
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(notify_signup.call_count, 1)
        self.assertEqual(notify_signup.call_args.args[0].username, "newclient")


class PasswordResetOtpTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username="client",
            email="client@example.com",
            password="StrongPass123!",
        )

    @patch("user.views.send_otp_email", return_value="123456")
    def test_forgot_password_saves_otp_after_email_send(self, send_otp_email):
        response = self.client.post(
            reverse("user:forgot_password"),
            {"email": self.user.email},
        )

        self.assertRedirects(response, reverse("user:verify_otp"))
        send_otp_email.assert_called_once_with(
            self.user.email,
            purpose="password reset",
            expiry_minutes=10,
        )
        self.assertTrue(
            PasswordResetOTP.objects.filter(user=self.user, otp="123456").exists()
        )

    @patch("user.views.send_otp_email", return_value=None)
    def test_forgot_password_does_not_save_otp_when_email_send_fails(self, send_otp_email):
        response = self.client.post(
            reverse("user:forgot_password"),
            {"email": self.user.email},
        )

        self.assertRedirects(response, reverse("user:forgot_password"))
        send_otp_email.assert_called_once_with(
            self.user.email,
            purpose="password reset",
            expiry_minutes=10,
        )
        self.assertFalse(PasswordResetOTP.objects.filter(user=self.user).exists())


class LoginTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username="loginclient",
            email="loginclient@example.com",
            password="StrongPass123!",
        )

    @patch("user.views.send_otp_email")
    def test_login_authenticates_without_otp_email(self, send_otp_email):
        response = self.client.post(
            reverse("user:login"),
            {
                "username": self.user.username,
                "password": "StrongPass123!",
            },
        )

        self.assertRedirects(response, reverse("user:dashboard"))
        send_otp_email.assert_not_called()
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.id)


class PinManagementTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username="pinclient",
            email="pinclient@example.com",
            password="StrongPass123!",
        )
        self.client.force_login(self.user)
        self.pin = TransactionPIN.objects.create(user=self.user)
        self.pin.set_pin("1234")
        self.pin.save(update_fields=["pin"])

    def test_profile_shows_pin_action_buttons(self):
        response = self.client.get(reverse("user:profile"))

        self.assertContains(response, reverse("user:change_pin"))
        self.assertContains(response, reverse("user:forgot_pin_request"))
        self.assertNotContains(response, reverse("user:forgot_password"))
        self.assertNotContains(response, 'name="current_pin"')

    def test_change_pin_saves_the_new_pin(self):
        response = self.client.post(
            reverse("user:change_pin"),
            {
                "current_pin": "1234",
                "new_pin": "5678",
                "confirm_new_pin": "5678",
            },
        )

        self.assertRedirects(response, reverse("user:profile"))
        self.pin.refresh_from_db()
        self.assertTrue(self.pin.check_pin("5678"))

    def test_profile_can_set_and_save_a_pin(self):
        self.pin.delete()

        response = self.client.post(
            reverse("user:profile"),
            {"set_pin": "", "pin": "4321", "confirm_pin": "4321"},
        )

        self.assertRedirects(response, reverse("user:profile"))
        self.assertTrue(TransactionPIN.objects.get(user=self.user).check_pin("4321"))
