from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0008_weekly_principal_daily_profit"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="transaction",
            name="origin",
            field=models.CharField(
                choices=[
                    ("normal", "Normal Transaction"),
                    ("admin_manual", "Manual Transaction by Admin"),
                ],
                db_index=True,
                default="normal",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="transaction",
            name="created_by_admin",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="manual_transactions",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
