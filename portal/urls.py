# portal/urls.py
from django.urls import path
from . import views

app_name = "portal"

urlpatterns = [
    # Overview
    path("", views.dashboard, name="dashboard"),

    # Inventory
    path("vendors/", views.vendor_list, name="vendors"),
    path("vendors/<int:pk>/", views.vendor_detail, name="vendor_detail"),

    path("services/", views.service_list, name="services"),

    path("contracts/", views.contract_list, name="contracts"),
    path("contracts/<int:pk>/", views.contract_detail, name="contract_detail"),

    path("invoices/", views.invoice_list, name="invoices"),
    path("invoices/<int:pk>/", views.invoice_detail, name="invoice_detail"),

    path("users/", views.users_list, name="users"),
    path("cost-centers/", views.cost_centers_list, name="cost_centers"),

    # Data Hub (Import/Export center)
    path("data-hub/", views.data_hub, name="data_hub"),
    path("data-hub/<str:entity>/import/", views.data_import, name="data_import"),
    path("data-hub/<str:entity>/export/", views.data_export, name="data_export"),
    path("data-hub/<str:entity>/template/", views.data_template, name="data_template"),

    # Other
    path("usage/", views.usage_overview, name="usage"),

    # Logout
    path("logout/", views.portal_logout, name="portal_logout"),
]
