from django.shortcuts import redirect
from functools import wraps
from django.contrib import messages
from .models import TransactionPIN


def profile_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):

        user = request.user
        if not user.phone and TransactionPIN:
            messages.error(request, "Please update your phone number first.")
            messages.error(request, "Please set your transaction PIN first.")
            return redirect("user:profile")

        if not user.phone:
            messages.error(request, "Please update your phone number first.")
            return redirect("user:profile")

        if not TransactionPIN.objects.filter(user=user).exists():
            messages.error(request, "Please set your transaction PIN first.")
            return redirect("user:profile")

        return view_func(request, *args, **kwargs)

    return wrapper