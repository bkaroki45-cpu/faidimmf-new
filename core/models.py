from django.db import models

class Contact(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField()
    message = models.TextField()
    phone = models.CharField(max_length=20, blank=True)  # optional phone

    created_at = models.DateTimeField(auto_now_add=True)  # optional timestamp

    def __str__(self):
        # Show name and email
        return f"{self.name} - {self.email}- {self.message}"