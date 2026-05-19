from datetime import timedelta

from django.db import migrations


def backfill_maturity_dates(apps, schema_editor):
    InvestmentTracking = apps.get_model("finance", "InvestmentTracking")

    for investment in InvestmentTracking.objects.filter(maturity_date__isnull=True):
        if investment.invested_at:
            investment.maturity_date = investment.invested_at + timedelta(hours=24)
            investment.save(update_fields=["maturity_date"])


def clear_backfilled_maturity_dates(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0006_alter_investmenttracking_interest_rate"),
    ]

    operations = [
        migrations.RunPython(backfill_maturity_dates, clear_backfilled_maturity_dates),
    ]
