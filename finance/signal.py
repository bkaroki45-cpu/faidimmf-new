from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Transaction, CompanyAccount

@receiver(post_save, sender=Transaction)
def handle_transaction(sender, instance, created, **kwargs):

    if instance.status != "completed":
        return

    if created:
        CompanyAccount.post_transaction(instance)