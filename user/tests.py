from django.test import TestCase
from django.urls import reverse
from unittest.mock import patch
from user.models import CustomUser, PasswordResetOTP


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
