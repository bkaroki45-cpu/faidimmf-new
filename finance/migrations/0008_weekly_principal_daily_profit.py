from datetime import timedelta
from decimal import Decimal

from django.db import migrations, models


def update_active_investments(apps, schema_editor):
    InvestmentTracking = apps.get_model("finance", "InvestmentTracking")

    for investment in InvestmentTracking.objects.filter(is_redeemed=False):
        investment.interest_rate = Decimal("0.025")
        if investment.invested_at:
            investment.maturity_date = investment.invested_at + timedelta(days=7)
        investment.save(update_fields=["interest_rate", "maturity_date"])


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0007_backfill_investment_maturity_dates"),
    ]

    operations = [
        migrations.AlterField(
            model_name="investmenttracking",
            name="interest_rate",
            field=models.DecimalField(
                decimal_places=4,
                default=Decimal("0.025"),
                max_digits=5,
            ),
        ),
        migrations.RunPython(update_active_investments, migrations.RunPython.noop),
    ]
