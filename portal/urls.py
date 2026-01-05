# portal/urls.py
from django.urls import path
from . import views

app_name = "portal"

urlpatterns = [
    # Overview
    path("", views.dashboard, name="dashboard"),
    path("search/", views.global_search, name="global_search"),

    # Inventory
    path("vendors/", views.vendor_list, name="vendors"),
    path("vendors/<int:pk>/", views.vendor_detail, name="vendor_detail"),

    path("services/", views.service_list, name="services"),
    path("services/add/", views.service_create, name="service_create"),
    path("services/<int:pk>/", views.service_detail, name="service_detail"),
    path("services/<int:pk>/edit/", views.service_edit, name="service_edit"),

    path("contracts/", views.contract_list, name="contracts"),
    path("contracts/<int:pk>/", views.contract_detail, name="contract_detail"),

    path("invoices/", views.invoice_list, name="invoices"),
    path("invoices/<int:pk>/", views.invoice_detail, name="invoice_detail"),

    path("users/", views.users_list, name="users"),
    path("users/<int:pk>/", views.user_detail, name="user_detail"),

    path("cost-centers/", views.cost_centers_list, name="cost_centers"),

    # Permissions (NEW)
    path("permissions/", views.permissions, name="permissions"),

    # Usage + usage inventory
    path("usage/", views.usage_overview, name="usage"),
    path("usage/invoices/", views.usage_invoices, name="usage_invoices"),
    path("usage/contracts/", views.usage_contract, name="usage_contract"),
    path("usage/vendors/", views.usage_vendors, name="usage_vendors"),
    path("usage/users/", views.usage_users, name="usage_users"),

    # Data Hub
    path("data-hub/", views.data_hub, name="data_hub"),
    path("data-hub/<str:entity>/import/", views.data_import, name="data_import"),
    path("data-hub/<str:entity>/export/", views.data_export, name="data_export"),
    path("data-hub/<str:entity>/template/", views.data_template, name="data_template"),

    # Provisioning Hub (NEW)
    path("provisioning-hub/", views.provisioning_hub, name="provisioning_hub"),
    path("provisioning-hub/catalog/", views.provisioning_catalog, name="provisioning_catalog"),
    path("provisioning-hub/requests/", views.provisioning_my_requests, name="provisioning_my_requests"),
    path("provisioning-hub/approvals/", views.provisioning_approvals, name="provisioning_approvals"),
    path("provisioning-hub/request/<int:service_pk>/", views.provisioning_request_create, name="provisioning_request_create"),
    path("provisioning-hub/approvals/<int:pk>/decide/", views.provisioning_approval_decide, name="provisioning_approval_decide"),
path("provisioning-hub/catalog/request-bulk/", views.provisioning_catalog_request_bulk, name="provisioning_catalog_request_bulk"),
path("provisioning-hub/access/<int:service_pk>/remove/", views.provisioning_access_remove, name="provisioning_access_remove",),    
path("provisioning-hub/approvals/decide/", views.provisioning_approvals_decide_bulk, name="provisioning_approvals_decide_bulk",),    
path("provisioning-hub/acting/set/", views.provisioning_acting_set, name="provisioning_acting_set"), 
path("provisioning-hub/acting/clear/", views.provisioning_acting_clear, name="provisioning_acting_clear"), 

    # Reports
    path("reports/", views.report_center, name="reports"),

    # Logout
    path("logout/", views.portal_logout, name="portal_logout"),
]
