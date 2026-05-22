from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from .models import Transaction, CompanyAccount
from .notifications import notify_transaction


@receiver(pre_save, sender=Transaction)
def remember_previous_status(sender, instance, **kwargs):
    if not instance.pk:
        instance._previous_status = None
        return

    instance._previous_status = (
        Transaction.objects.filter(pk=instance.pk)
        .values_list("status", flat=True)
        .first()
    )

@receiver(post_save, sender=Transaction)
def handle_transaction(sender, instance, created, **kwargs):

    previous_status = getattr(instance, "_previous_status", None)

    if instance.status == "completed" and created:
        CompanyAccount.post_transaction(instance)

    if created:
        event = "created"
    elif previous_status and previous_status != instance.status:
        event = "status_changed"
    else:
        return

    transaction.on_commit(lambda: notify_transaction(instance, event=event))
