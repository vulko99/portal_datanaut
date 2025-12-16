# landing/admin.py
from django.contrib import admin
from .models import ContactRequest


@admin.register(ContactRequest)
class ContactRequestAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "company",
        "role",
        "email",
        "persona",
        "status",
        "source",
        "created_at",
    )
    list_filter = ("persona", "status", "source", "created_at")
    search_fields = ("name", "company", "email", "role", "message")
    ordering = ("-created_at",)
