from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import reverse


class SuspendedUserMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user and user.is_authenticated and not user.is_active:
            logout(request)
            messages.error(request, "Your account has been suspended. Contact support.")
            return redirect(reverse("user:login"))

        return self.get_response(request)
