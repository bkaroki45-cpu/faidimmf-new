from django.contrib import admin
from .models import Contact

class ContactAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'message', 'created_at')  # fields shown in list
    search_fields = ('name', 'email', 'message')                # add search box
    list_filter = ('created_at',)                               # filter by date
    ordering = ('-created_at',)                                 # newest first


admin.site.register(Contact, ContactAdmin)
