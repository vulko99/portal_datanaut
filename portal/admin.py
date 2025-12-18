# portal/admin.py
from django.contrib import admin

from .models import (
    Vendor,
    Service,
    CostCenter,
    Contract,
    Invoice,
    InvoiceLine,
)


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ("name", "vendor_type", "primary_contact_name", "primary_contact_email")
    search_fields = ("name", "vendor_type", "primary_contact_name", "primary_contact_email")
    list_filter = ("vendor_type",)


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("name", "vendor", "category", "service_code", "default_currency", "default_billing_frequency")
    list_filter = ("vendor", "category", "default_billing_frequency")
    search_fields = ("name", "service_code", "vendor__name")


@admin.register(CostCenter)
class CostCenterAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "business_unit", "region", "default_approver")
    search_fields = ("code", "name", "business_unit", "region")
    list_filter = ("business_unit", "region")


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    # ВАЖНО: няма 'title' – вече е 'contract_name'
    list_display = (
        "contract_name",
        "vendor",
        "contract_id",
        "contract_type",
        "status",
        "annual_value",
        "currency",
        "start_date",
        "end_date",
        "renewal_date",
        "owning_cost_center",
        "owner",
    )
    list_filter = ("vendor", "status", "contract_type", "currency")
    search_fields = ("contract_name", "contract_id", "vendor__name", "entity")
    autocomplete_fields = ("vendor", "owning_cost_center", "owner", "uploaded_by", "related_services")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    # Тук също – използваме 'total_amount', не 'amount'
    list_display = (
        "invoice_number",
        "vendor",
        "contract",
        "invoice_date",
        "total_amount",
        "currency",
        "period_start",
        "period_end",
    )
    list_filter = ("vendor", "currency", "invoice_date")
    search_fields = ("invoice_number", "vendor__name", "contract__contract_name")
    autocomplete_fields = ("vendor", "contract")
    readonly_fields = ("created_at",)


@admin.register(InvoiceLine)
class InvoiceLineAdmin(admin.ModelAdmin):
    list_display = (
        "invoice",
        "service",
        "description",
        "quantity",
        "unit_price",
        "line_amount",
        "currency",
        "cost_center",
        "user",
    )
    list_filter = ("currency", "cost_center", "service")
    search_fields = ("description", "invoice__invoice_number", "service__name", "user__username")
    autocomplete_fields = ("invoice", "service", "cost_center", "user")
