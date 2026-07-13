from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0009_transaction_manual_origin"),
    ]

    operations = [
        migrations.AddField(
            model_name="investmenttracking",
            name="term_days",
            field=models.PositiveIntegerField(
                choices=[
                    (7, "Weekly"),
                    (30, "Monthly"),
                    (90, "3 Months"),
                    (180, "6 Months"),
                    (270, "9 Months"),
                    (365, "Annually"),
                ],
                default=7,
            ),
        ),
    ]
