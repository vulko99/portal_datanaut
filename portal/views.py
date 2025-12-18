from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.shortcuts import render
from django.db.models import Count

from .models import Vendor, Service, Contract, Invoice, CostCenter, UserProfile

User = get_user_model()


@login_required
def dashboard(request):
    # “demo numbers” за инвеститорски вид; по-късно ще ги вържем към реални агрегати
    context = {
        "kpis": [
            {"label": "Total market data & tech spend", "value": "4.3m", "hint": "+3.8% vs previous 12 months"},
            {"label": "Identified savings", "value": "0.9m", "hint": "27 active initiatives"},
            {"label": "Contracts in scope", "value": "38", "hint": "12 vendors · 7 entities"},
            {"label": "Renewals next 90 days", "value": "6", "hint": "Prioritise high-value negotiations"},
        ],
        "quick_links": [
            {"label": "Review upcoming renewals and large contracts", "url_name": "contracts"},
            {"label": "Check desks with underused / duplicate licences", "url_name": "usage"},
            {"label": "Review latest invoices (placeholder)", "url_name": "invoices"},
        ],
    }
    return render(request, "portal/dashboard.html", context)


@login_required
def vendor_list(request):
    vendors = Vendor.objects.all().order_by("name")
    return render(request, "portal/vendors.html", {"vendors": vendors})


@login_required
def service_list(request):
    services = Service.objects.select_related("vendor").order_by("vendor__name", "name")
    return render(request, "portal/services.html", {"services": services})


@login_required
def contract_list(request):
    # показваме само контрактите на текущия user (owner)
    contracts = (
        Contract.objects.filter(owner=request.user)
        .select_related("vendor", "owning_cost_center")
        .prefetch_related("related_services")
        .order_by("-created_at")
    )
    return render(request, "portal/contracts.html", {"contracts": contracts})


@login_required
def invoice_list(request):
    invoices = (
        Invoice.objects.filter(owner=request.user)
        .select_related("vendor", "contract")
        .order_by("-invoice_date", "-id")
    )
    return render(request, "portal/invoices.html", {"invoices": invoices})


@login_required
def user_list(request):
    users = (
        User.objects.all()
        .select_related()
        .order_by("username")
    )
    profiles = {p.user_id: p for p in UserProfile.objects.select_related("cost_center").all()}
    return render(request, "portal/users.html", {"users": users, "profiles": profiles})


@login_required
def cost_centers_list(request):
    cost_centers = (
        CostCenter.objects.all()
        .annotate(user_count=Count("users"))
        .select_related("default_approver")
        .order_by("code")
    )
    return render(request, "portal/cost_centers.html", {"cost_centers": cost_centers})


@login_required
def usage(request):
    # остава демо; по-късно ще го вържем към реални entitlements/usage exports
    return render(request, "portal/usage.html")
