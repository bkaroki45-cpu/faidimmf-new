from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("user", "0004_passwordresetotp"),
    ]

    operations = [
        migrations.CreateModel(
            name="ReferralRelationship",
            fields=[],
            options={
                "verbose_name": "Referral",
                "verbose_name_plural": "Referrals",
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("user.customuser",),
        ),
    ]
