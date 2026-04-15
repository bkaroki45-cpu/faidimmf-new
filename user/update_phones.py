import os
import django

# Set Django settings module
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mmf.settings")  # change if your settings file is different
django.setup()

from user.models import CustomUser

# Fill empty phone fields with unique temporary values
users = CustomUser.objects.filter(phone__isnull=True)
for i, user in enumerate(users, start=1):
    user.phone = f"temp_unique_phone_{i}"
    user.save()

print("All null phones updated with temporary unique values.")