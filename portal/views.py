# portal/views.py
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import render, redirect
from django.views.decorators.http import require_GET

from .models import Contract
from .forms import ContractUploadForm


@login_required
def dashboard(request):
    """
    Основно табло – агрегира базови метрики за договорите на текущия потребител.
    """
    contracts = Contract.objects.filter(owner=request.user)

    total_spend = contracts.aggregate(total=Sum("annual_value"))["total"] or 0
    active_contracts = contracts.count()
    upcoming_renewals = contracts.filter(renewal_date__isnull=False).count()

    context = {
        "total_spend": total_spend,
        "active_contracts": active_contracts,
        "upcoming_renewals": upcoming_renewals,
    }
    return render(request, "portal/dashboard.html", context)


@login_required
def contract_list(request):
    """
    Списък с договори + форма за качване на нов договор.
    Работи само в контекста на текущия потребител (owner=request.user).
    """
    contracts = (
        Contract.objects.filter(owner=request.user)
        .select_related("vendor")
        .order_by("-created_at")
    )

    if request.method == "POST":
        form = ContractUploadForm(request.POST, request.FILES)
        if form.is_valid():
            # вграденият save() в формата приема owner и uploaded_by
            form.save(owner=request.user, uploaded_by=request.user)
            # redirect за да избегнем повторно качване при refresh
            return redirect("portal:contracts")
    else:
        form = ContractUploadForm()

    context = {
        "contracts": contracts,
        "form": form,
    }
    return render(request, "portal/contracts.html", context)


@login_required
def usage_overview(request):
    """
    Placeholder за usage / dashboards – към момента е статична страница.
    """
    return render(request, "portal/usage.html")


@require_GET
def portal_logout(request):
    """
    Явно дефиниран logout за портала.
    Чисти сесията и връща потребителя към login страницата на портала.
    """
    logout(request)
    return redirect("login")  # name="login" => /<lang>/portal/login/
