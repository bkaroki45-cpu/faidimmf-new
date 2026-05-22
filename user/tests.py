from django.test import TestCase
from django.urls import reverse
from unittest.mock import patch


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
