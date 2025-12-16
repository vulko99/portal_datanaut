# portal/urls.py
from django.urls import path
from . import views

app_name = "portal"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("contracts/", views.contract_list, name="contracts"),
    path("usage/", views.usage_overview, name="usage"),
]
