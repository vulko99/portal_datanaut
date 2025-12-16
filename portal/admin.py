from django.contrib import admin
from .models import Vendor, Contract


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "vendor",
        "entity",
        "annual_value",
        "renewal_date",
        "uploaded_by",
        "created_at",
    )
    list_filter = ("vendor", "renewal_date", "entity")
    search_fields = ("title", "vendor__name", "entity")
