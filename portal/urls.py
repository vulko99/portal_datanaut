from django.urls import path
from . import views

app_name = "portal"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),

    path("vendors/", views.vendor_list, name="vendors"),
    path("services/", views.service_list, name="services"),

    path("contracts/", views.contract_list, name="contracts"),
    path("invoices/", views.invoice_list, name="invoices"),

    path("users/", views.user_list, name="users"),
    path("cost-centers/", views.cost_centers_list, name="cost_centers"),

    path("usage/", views.usage, name="usage"),
]
