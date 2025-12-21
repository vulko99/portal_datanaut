# portal/views.py
from __future__ import annotations

import csv
import io
import re
from decimal import Decimal, InvalidOperation
from datetime import datetime, date

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Sum, Count
from django.http import HttpResponse, Http404
from django.shortcuts import render, redirect, get_object_or_404

from .models import (
    Vendor,
    Service,
    CostCenter,
    UserProfile,
    Contract,
    Invoice,
)
from .forms import ContractUploadForm, InvoiceUploadForm, VendorCreateForm

User = get_user_model()


# -------------------------
# Helpers: parsing / export
# -------------------------

_HEADER_SEP_RE = re.compile(r"[\s\-]+")


def _normalize_header(h: str) -> str:
    """
    Normalize column headers from CSV/XLSX:
    - strip BOM
    - lowercase
    - spaces/dashes -> underscore
    - remove other punctuation
    """
    h = (h or "").replace("\ufeff", "").strip().lower()
    h = _HEADER_SEP_RE.sub("_", h)
    h = re.sub(r"[^\w_]", "", h)
    return h.strip("_")


def _as_str(v) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _parse_date(value) -> date | None:
    """
    Accepts:
      - date / datetime (native from XLSX)
      - YYYY-MM-DD (preferred)
      - ISO datetime string (e.g. 2025-12-19 00:00:00)
      - DD/MM/YYYY, MM/DD/YYYY
    """
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    s = _as_str(value)
    if not s:
        return None

    # accept ISO datetime string too
    try:
        return datetime.fromisoformat(s).date()
    except Exception:
        pass

    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue

    raise ValueError(f"Invalid date format: {s}. Use YYYY-MM-DD.")


def _parse_decimal(value) -> Decimal | None:
    s = _as_str(value)
    if not s:
        return None
    s = s.replace(",", ".")
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        raise ValueError(f"Invalid decimal value: {s}")


def _parse_int(value) -> int | None:
    """
    Accepts: int, numeric string (e.g. '90', '90.0'), empty -> None
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value

    s = _as_str(value)
    if not s:
        return None

    # allow "90.0" from excel/csv
    try:
        return int(Decimal(s.replace(",", ".")))
    except Exception:
        raise ValueError(f"Invalid integer value: {s}")


def _detect_format(request, filename: str | None = None) -> str:
    fmt = (request.GET.get("format") or "").lower().strip()
    if fmt in ("csv", "xlsx"):
        return fmt

    if filename:
        fn = filename.lower()
        if fn.endswith(".xlsx"):
            return "xlsx"
        return "csv"

    return "csv"


def _read_csv(uploaded_file) -> list[dict]:
    raw = uploaded_file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1251", errors="replace")

    f = io.StringIO(text)
    reader = csv.DictReader(f)
    rows: list[dict] = []
    for r in reader:
        rows.append({_normalize_header(k): v for k, v in (r or {}).items()})
    return rows


def _read_xlsx(uploaded_file) -> list[dict]:
    try:
        import openpyxl
    except Exception as e:
        raise RuntimeError("openpyxl is required for XLSX import. Install it and retry.") from e

    wb = openpyxl.load_workbook(uploaded_file, data_only=True)
    ws = wb.active

    header: list[str] | None = None
    rows: list[dict] = []

    for row_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
        values = list(row)

        if header is None:
            if all(v is None or str(v).strip() == "" for v in values):
                continue
            header = [_normalize_header(_as_str(v)) for v in values]
            continue

        if all(v is None or str(v).strip() == "" for v in values):
            continue

        record: dict = {}
        for i, key in enumerate(header):
            if not key:
                continue
            # keep native values (date/datetime/number) for better parsing
            record[key] = "" if i >= len(values) or values[i] is None else values[i]
        rows.append(record)

    return rows


def _read_table(uploaded_file, fmt: str) -> list[dict]:
    if fmt == "xlsx":
        return _read_xlsx(uploaded_file)
    return _read_csv(uploaded_file)


def _workbook_response(filename: str, headers: list[str], rows: list[list[str]]) -> HttpResponse:
    try:
        import openpyxl
    except Exception as e:
        raise RuntimeError("openpyxl is required for XLSX export. Install it and retry.") from e

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(r)

    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)

    resp = HttpResponse(
        bio.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


def _csv_response(filename: str, headers: list[str], rows: list[list[str]]) -> HttpResponse:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(headers)
    for r in rows:
        writer.writerow(r)

    resp = HttpResponse(out.getvalue(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


# -------------------------
# Importers (per entity)
# -------------------------

def _require_columns(rows: list[dict], required: list[str]) -> None:
    if not rows:
        return
    cols = set(rows[0].keys())
    missing = [c for c in required if c not in cols]
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")


@transaction.atomic
def _import_vendors(rows: list[dict], request_user) -> dict:
    """
    Columns:
      name*, vendor_type, tags, primary_contact_name, primary_contact_email, website, notes
    Upsert by name (case-insensitive).
    """
    _require_columns(rows, ["name"])
    created = 0
    updated = 0

    for r in rows:
        name = _as_str(r.get("name"))
        if not name:
            continue

        defaults = {
            "vendor_type": _as_str(r.get("vendor_type")),
            "tags": _as_str(r.get("tags")),
            "primary_contact_name": _as_str(r.get("primary_contact_name")),
            "primary_contact_email": _as_str(r.get("primary_contact_email")),
            "website": _as_str(r.get("website")),
            "notes": _as_str(r.get("notes")),
        }

        obj = Vendor.objects.filter(name__iexact=name).first()
        if obj:
            for k, v in defaults.items():
                if v != "":
                    setattr(obj, k, v)
            obj.name = name
            obj.save()
            updated += 1
        else:
            Vendor.objects.create(name=name, **defaults)
            created += 1

    return {"created": created, "updated": updated}


@transaction.atomic
def _import_cost_centers(rows: list[dict], request_user) -> dict:
    """
    Columns:
      code*, name*, business_unit, region
    Upsert by code.
    """
    _require_columns(rows, ["code", "name"])
    created = 0
    updated = 0

    for r in rows:
        code = _as_str(r.get("code"))
        name = _as_str(r.get("name"))
        if not code or not name:
            continue

        defaults = {
            "name": name,
            "business_unit": _as_str(r.get("business_unit")),
            "region": _as_str(r.get("region")),
        }

        obj, was_created = CostCenter.objects.update_or_create(
            code=code,
            defaults=defaults,
        )
        if was_created:
            created += 1
        else:
            updated += 1

    return {"created": created, "updated": updated}


@transaction.atomic
def _import_services(rows: list[dict], request_user) -> dict:
    """
    Columns:
      vendor_name*, name*, category, service_code, default_currency, default_billing_frequency,
      owner_display, list_price, allocation_split
    Unique: (vendor, name)
    """
    _require_columns(rows, ["vendor_name", "name"])
    created = 0
    updated = 0

    for r in rows:
        vendor_name = _as_str(r.get("vendor_name"))
        name = _as_str(r.get("name"))
        if not vendor_name or not name:
            continue

        vendor = Vendor.objects.filter(name__iexact=vendor_name).first()
        if not vendor:
            raise ValueError(
                f"Vendor not found for service: {vendor_name} (service={name}). Import vendors first."
            )

        defaults = {
            "category": _as_str(r.get("category")),
            "service_code": _as_str(r.get("service_code")),
            "default_currency": _as_str(r.get("default_currency")),
            "default_billing_frequency": _as_str(r.get("default_billing_frequency")),
            "owner_display": _as_str(r.get("owner_display")),
            "allocation_split": _as_str(r.get("allocation_split")),
        }

        lp = r.get("list_price")
        if _as_str(lp):
            defaults["list_price"] = _parse_decimal(lp)

        obj = Service.objects.filter(vendor=vendor, name__iexact=name).first()
        if obj:
            obj.name = name
            for k, v in defaults.items():
                if v is not None and v != "":
                    setattr(obj, k, v)
            obj.save()
            updated += 1
        else:
            Service.objects.create(vendor=vendor, name=name, **defaults)
            created += 1

    return {"created": created, "updated": updated}


@transaction.atomic
def _import_contracts(rows: list[dict], request_user) -> dict:
    """
    Columns (minimal):
      vendor_name*, contract_name*, contract_id, contract_type, entity, annual_value, currency,
      start_date, end_date, renewal_date, notice_period_days, notice_date, status

    Owner/uploaded_by = request.user.
    Upsert heuristic:
      - if contract_id exists: (owner, vendor, contract_name, contract_id)
      - else: (owner, vendor, contract_name)
    """
    _require_columns(rows, ["vendor_name", "contract_name"])
    created = 0
    updated = 0

    for r in rows:
        vendor_name = _as_str(r.get("vendor_name"))
        contract_name = _as_str(r.get("contract_name"))
        if not vendor_name or not contract_name:
            continue

        vendor = Vendor.objects.filter(name__iexact=vendor_name).first()
        if not vendor:
            raise ValueError(
                f"Vendor not found for contract: {vendor_name} (contract={contract_name}). Import vendors first."
            )

        contract_id = _as_str(r.get("contract_id"))
        qs = Contract.objects.filter(owner=request_user, vendor=vendor, contract_name__iexact=contract_name)
        if contract_id:
            qs = qs.filter(contract_id__iexact=contract_id)

        obj = qs.first()

        defaults = {
            "vendor": vendor,
            "contract_name": contract_name,
            "contract_id": contract_id,
            "contract_type": _as_str(r.get("contract_type")),
            "entity": _as_str(r.get("entity")),
            "currency": _as_str(r.get("currency")),
            "status": _as_str(r.get("status")),
            "uploaded_by": request_user,
        }

        av = r.get("annual_value")
        if _as_str(av):
            defaults["annual_value"] = _parse_decimal(av)

        for field in ("start_date", "end_date", "renewal_date"):
            v = r.get(field)
            if _as_str(v):
                defaults[field] = _parse_date(v)

        # --- NEW: notice fields ---
        npd = r.get("notice_period_days")
        nd = r.get("notice_date")

        if _as_str(npd):
            notice_period_days = _parse_int(npd)
            if notice_period_days not in (30, 60, 90, 120):
                raise ValueError(
                    f"Invalid notice_period_days '{_as_str(npd)}' for contract '{contract_name}'. Allowed: 30, 60, 90, 120."
                )
            defaults["notice_period_days"] = notice_period_days

        if _as_str(nd):
            defaults["notice_date"] = _parse_date(nd)

        # Validation rules:
        # - if notice_date present, requires end_date
        # - notice_date must be <= end_date
        end_dt = defaults.get("end_date") or (obj.end_date if obj else None)
        notice_dt = defaults.get("notice_date") if "notice_date" in defaults else (obj.notice_date if obj else None)

        if notice_dt and not end_dt:
            raise ValueError(
                f"Contract '{contract_name}': notice_date is set but end_date is missing."
            )
        if notice_dt and end_dt and notice_dt > end_dt:
            raise ValueError(
                f"Contract '{contract_name}': notice_date ({notice_dt}) must be on/before end_date ({end_dt})."
            )

        if obj:
            for k, v in defaults.items():
                if v is not None and v != "":
                    setattr(obj, k, v)
            obj.save()
            updated += 1
        else:
            Contract.objects.create(owner=request_user, **defaults)
            created += 1

    return {"created": created, "updated": updated}


@transaction.atomic
def _import_invoices(rows: list[dict], request_user) -> dict:
    """
    Columns (minimal):
      vendor_name*, invoice_number*, invoice_date*, currency*, total_amount*
      contract_name (optional), tax_amount, period_start, period_end, notes

    Owner = request.user.
    Upsert heuristic: (owner, vendor, invoice_number)
    """
    _require_columns(rows, ["vendor_name", "invoice_number", "invoice_date", "currency", "total_amount"])
    created = 0
    updated = 0

    for r in rows:
        vendor_name = _as_str(r.get("vendor_name"))
        invoice_number = _as_str(r.get("invoice_number"))
        invoice_date = r.get("invoice_date")
        currency = _as_str(r.get("currency"))
        total_amount = r.get("total_amount")

        if not vendor_name or not invoice_number:
            continue

        vendor = Vendor.objects.filter(name__iexact=vendor_name).first()
        if not vendor:
            raise ValueError(
                f"Vendor not found for invoice: {vendor_name} (invoice={invoice_number}). Import vendors first."
            )

        contract = None
        contract_name = _as_str(r.get("contract_name"))
        if contract_name:
            contract = Contract.objects.filter(
                owner=request_user, vendor=vendor, contract_name__iexact=contract_name
            ).first()
            if not contract:
                contract = Contract.objects.filter(owner=request_user, contract_name__iexact=contract_name).first()

        defaults = {
            "invoice_date": _parse_date(invoice_date),
            "currency": currency,
            "total_amount": _parse_decimal(total_amount) or Decimal("0"),
            "notes": _as_str(r.get("notes")),
            "contract": contract,
        }

        ta = r.get("tax_amount")
        if _as_str(ta):
            defaults["tax_amount"] = _parse_decimal(ta)

        for field in ("period_start", "period_end"):
            v = r.get(field)
            if _as_str(v):
                defaults[field] = _parse_date(v)

        obj = Invoice.objects.filter(owner=request_user, vendor=vendor, invoice_number__iexact=invoice_number).first()
        if obj:
            for k, v in defaults.items():
                if v is not None and v != "":
                    setattr(obj, k, v)
            obj.invoice_number = invoice_number
            obj.save()
            updated += 1
        else:
            Invoice.objects.create(
                owner=request_user,
                vendor=vendor,
                invoice_number=invoice_number,
                **defaults,
            )
            created += 1

    return {"created": created, "updated": updated}


DATA_ENTITIES = {
    "vendors": {
        "label": "Vendors",
        "template_headers": [
            "name", "vendor_type", "tags", "primary_contact_name",
            "primary_contact_email", "website", "notes",
        ],
        "importer": _import_vendors,
        "exporter": lambda user: [
            [
                v.name,
                v.vendor_type or "",
                v.tags or "",
                v.primary_contact_name or "",
                v.primary_contact_email or "",
                v.website or "",
                v.notes or "",
            ]
            for v in Vendor.objects.all().order_by("name")
        ],
    },
    "cost-centers": {
        "label": "Cost centers",
        "template_headers": ["code", "name", "business_unit", "region"],
        "importer": _import_cost_centers,
        "exporter": lambda user: [
            [c.code, c.name, c.business_unit or "", c.region or ""]
            for c in CostCenter.objects.all().order_by("code")
        ],
    },
    "services": {
        "label": "Services",
        "template_headers": [
            "vendor_name", "name", "category", "service_code",
            "default_currency", "default_billing_frequency",
            "owner_display", "list_price", "allocation_split",
        ],
        "importer": _import_services,
        "exporter": lambda user: [
            [
                s.vendor.name,
                s.name,
                s.category or "",
                s.service_code or "",
                s.default_currency or "",
                s.default_billing_frequency or "",
                s.owner_display or "",
                _as_str(s.list_price) if s.list_price is not None else "",
                s.allocation_split or "",
            ]
            for s in Service.objects.select_related("vendor").order_by("vendor__name", "name")
        ],
    },
    "contracts": {
        "label": "Contracts",
        "template_headers": [
            "vendor_name", "contract_name", "contract_id", "contract_type", "entity",
            "annual_value", "currency", "start_date", "end_date", "renewal_date",
            "notice_period_days", "notice_date",
            "status",
        ],
        "importer": _import_contracts,
        "exporter": lambda user: [
            [
                c.vendor.name,
                c.contract_name,
                c.contract_id or "",
                c.contract_type or "",
                c.entity or "",
                _as_str(c.annual_value) if c.annual_value is not None else "",
                c.currency or "",
                _as_str(c.start_date) if c.start_date else "",
                _as_str(c.end_date) if c.end_date else "",
                _as_str(c.renewal_date) if c.renewal_date else "",
                _as_str(c.notice_period_days) if getattr(c, "notice_period_days", None) else "",
                _as_str(c.notice_date) if getattr(c, "notice_date", None) else "",
                c.status or "",
            ]
            for c in Contract.objects.filter(owner=user).select_related("vendor").order_by("-created_at")
        ],
    },
    "invoices": {
        "label": "Invoices",
        "template_headers": [
            "vendor_name", "contract_name", "invoice_number", "invoice_date", "currency",
            "total_amount", "tax_amount", "period_start", "period_end", "notes",
        ],
        "importer": _import_invoices,
        "exporter": lambda user: [
            [
                i.vendor.name,
                i.contract.contract_name if i.contract else "",
                i.invoice_number,
                _as_str(i.invoice_date),
                i.currency,
                _as_str(i.total_amount),
                _as_str(i.tax_amount) if i.tax_amount is not None else "",
                _as_str(i.period_start) if i.period_start else "",
                _as_str(i.period_end) if i.period_end else "",
                i.notes or "",
            ]
            for i in Invoice.objects.filter(owner=user).select_related("vendor", "contract").order_by("-invoice_date", "-id")
        ],
    },
}


def _get_entity_or_404(entity: str) -> dict:
    cfg = DATA_ENTITIES.get(entity)
    if not cfg:
        raise Http404("Unknown Data Hub entity.")
    return cfg


# ----------
# DASHBOARD
# ----------

@login_required
def dashboard(request):
    contracts = Contract.objects.filter(owner=request.user)
    invoices = Invoice.objects.filter(owner=request.user)

    total_spend = contracts.aggregate(total=Sum("annual_value"))["total"] or 0
    active_contracts = contracts.count()
    upcoming_renewals = contracts.filter(renewal_date__isnull=False).count()

    invoice_total = invoices.aggregate(total=Sum("total_amount"))["total"] or 0
    vendors_count = Vendor.objects.filter(contracts__owner=request.user).distinct().count()

    context = {
        "total_spend": total_spend,
        "active_contracts": active_contracts,
        "upcoming_renewals": upcoming_renewals,
        "invoice_total": invoice_total,
        "vendors_count": vendors_count,
    }
    return render(request, "portal/dashboard.html", context)


# ----------
# CONTRACTS
# ----------

@login_required
def contract_list(request):
    contracts = (
        Contract.objects.filter(owner=request.user)
        .select_related("vendor", "owning_cost_center")
        .order_by("-start_date", "-created_at")
    )

    if request.method == "POST":
        form = ContractUploadForm(request.POST, request.FILES)
        if form.is_valid():
            form.save(owner=request.user, uploaded_by=request.user)
            return redirect("portal:contracts")
    else:
        form = ContractUploadForm()

    context = {"contracts": contracts, "form": form}
    return render(request, "portal/contracts.html", context)


@login_required
def contract_detail(request, pk):
    contract = get_object_or_404(
        Contract.objects.select_related("vendor", "owning_cost_center", "owner"),
        pk=pk,
        owner=request.user,
    )

    invoices = (
        contract.invoices.all()
        .select_related("vendor")
        .order_by("-invoice_date", "-id")
    )

    context = {"contract": contract, "invoices": invoices}
    return render(request, "portal/contract_detail.html", context)


# ----------
# INVOICING
# ----------

@login_required
def invoice_list(request):
    invoices = (
        Invoice.objects.filter(owner=request.user)
        .select_related("vendor", "contract")
        .order_by("-invoice_date", "-id")
    )
    total_amount = invoices.aggregate(total=Sum("total_amount"))["total"] or 0

    if request.method == "POST":
        form = InvoiceUploadForm(request.POST, request.FILES)
        if form.is_valid():
            form.save(owner=request.user)
            return redirect("portal:invoices")
    else:
        form = InvoiceUploadForm()

    context = {"invoices": invoices, "total_amount": total_amount, "form": form}
    return render(request, "portal/invoices.html", context)


@login_required
def invoice_detail(request, pk):
    invoice = get_object_or_404(
        Invoice.objects.select_related("vendor", "contract", "owner"),
        pk=pk,
        owner=request.user,
    )

    lines = (
        invoice.lines.select_related("service", "cost_center", "user", "service__vendor")
        .order_by("id")
    )

    allocation_by_cost_center = (
        lines.values("cost_center__code", "cost_center__name")
        .annotate(total=Sum("line_amount"))
        .order_by("cost_center__code")
    )

    service_breakdown = (
        lines.values("service__vendor__name", "service__name")
        .annotate(total=Sum("line_amount"))
        .order_by("service__vendor__name", "service__name")
    )

    context = {
        "invoice": invoice,
        "lines": lines,
        "allocation_by_cost_center": allocation_by_cost_center,
        "service_breakdown": service_breakdown,
    }
    return render(request, "portal/invoice_detail.html", context)


# ----------
# VENDORS
# ----------

@login_required
def vendor_list(request):
    if request.method == "POST":
        form = VendorCreateForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("portal:vendors")
    else:
        form = VendorCreateForm()

    vendors = (
        Vendor.objects.all()
        .annotate(contract_count=Count("contracts", distinct=True))
        .annotate(invoice_count=Count("invoices", distinct=True))
        .order_by("name")
    )

    context = {"vendors": vendors, "form": form}
    return render(request, "portal/vendors.html", context)


@login_required
def vendor_detail(request, pk):
    vendor = get_object_or_404(Vendor, pk=pk)

    contracts = (
        Contract.objects.filter(owner=request.user, vendor=vendor)
        .select_related("owning_cost_center")
        .order_by("-start_date", "-created_at")
    )

    invoices = (
        Invoice.objects.filter(owner=request.user, vendor=vendor)
        .select_related("contract")
        .order_by("-invoice_date", "-id")
    )

    services = Service.objects.filter(vendor=vendor).order_by("name")

    total_contract_value = contracts.aggregate(total=Sum("annual_value"))["total"] or 0
    total_invoiced = invoices.aggregate(total=Sum("total_amount"))["total"] or 0

    context = {
        "vendor": vendor,
        "contracts": contracts,
        "invoices": invoices,
        "services": services,
        "total_contract_value": total_contract_value,
        "total_invoiced": total_invoiced,
    }
    return render(request, "portal/vendor_detail.html", context)


# ----------
# SERVICES
# ----------

@login_required
def service_list(request):
    services = Service.objects.select_related("vendor").order_by("vendor__name", "name")
    return render(request, "portal/services.html", {"services": services})


@login_required
def service_detail(request, pk: int):
    """
    Additive: service detail page.
    No ownership filter (services are global in your current model usage).
    """
    service = get_object_or_404(Service.objects.select_related("vendor"), pk=pk)

    context = {
        "service": service,
    }
    return render(request, "portal/service_detail.html", context)


@login_required
def service_create(request):
    """
    Additive: create service via portal without touching admin.
    Uses a simple POST parser so we don't need to change your existing forms.py right now.
    """
    vendors = Vendor.objects.all().order_by("name")

    if request.method == "POST":
        vendor_id = _as_str(request.POST.get("vendor_id"))
        name = _as_str(request.POST.get("name"))
        category = _as_str(request.POST.get("category"))
        service_code = _as_str(request.POST.get("service_code"))
        default_currency = _as_str(request.POST.get("default_currency"))
        default_billing_frequency = _as_str(request.POST.get("default_billing_frequency"))
        owner_display = _as_str(request.POST.get("owner_display"))
        allocation_split = _as_str(request.POST.get("allocation_split"))
        list_price_raw = _as_str(request.POST.get("list_price"))

        errors: list[str] = []

        vendor = None
        if not vendor_id:
            errors.append("Vendor is required.")
        else:
            vendor = Vendor.objects.filter(pk=vendor_id).first()
            if not vendor:
                errors.append("Selected vendor does not exist.")

        if not name:
            errors.append("Service name is required.")

        list_price = None
        if list_price_raw:
            try:
                list_price = _parse_decimal(list_price_raw)
            except Exception as e:
                errors.append(str(e))

        # Uniqueness heuristic (matches importer behavior): (vendor, name case-insensitive)
        if vendor and name:
            exists = Service.objects.filter(vendor=vendor, name__iexact=name).exists()
            if exists:
                errors.append("A service with this name already exists for the selected vendor.")

        if errors:
            for e in errors:
                messages.error(request, e)

            return render(
                request,
                "portal/service_form.html",
                {
                    "mode": "create",
                    "vendors": vendors,
                    "form_data": {
                        "vendor_id": vendor_id,
                        "name": name,
                        "category": category,
                        "service_code": service_code,
                        "default_currency": default_currency,
                        "default_billing_frequency": default_billing_frequency,
                        "owner_display": owner_display,
                        "allocation_split": allocation_split,
                        "list_price": list_price_raw,
                    },
                },
            )

        service = Service.objects.create(
            vendor=vendor,
            name=name,
            category=category or "",
            service_code=service_code or "",
            default_currency=default_currency or "",
            default_billing_frequency=default_billing_frequency or "",
            owner_display=owner_display or "",
            allocation_split=allocation_split or "",
            list_price=list_price,
        )

        messages.success(request, "Service created successfully.")
        return redirect("portal:service_detail", pk=service.pk)

    return render(
        request,
        "portal/service_form.html",
        {
            "mode": "create",
            "vendors": vendors,
            "form_data": {},
        },
    )


@login_required
def service_edit(request, pk: int):
    """
    Additive: edit service via portal.
    """
    service = get_object_or_404(Service.objects.select_related("vendor"), pk=pk)
    vendors = Vendor.objects.all().order_by("name")

    if request.method == "POST":
        vendor_id = _as_str(request.POST.get("vendor_id"))
        name = _as_str(request.POST.get("name"))
        category = _as_str(request.POST.get("category"))
        service_code = _as_str(request.POST.get("service_code"))
        default_currency = _as_str(request.POST.get("default_currency"))
        default_billing_frequency = _as_str(request.POST.get("default_billing_frequency"))
        owner_display = _as_str(request.POST.get("owner_display"))
        allocation_split = _as_str(request.POST.get("allocation_split"))
        list_price_raw = _as_str(request.POST.get("list_price"))

        errors: list[str] = []

        vendor = None
        if not vendor_id:
            errors.append("Vendor is required.")
        else:
            vendor = Vendor.objects.filter(pk=vendor_id).first()
            if not vendor:
                errors.append("Selected vendor does not exist.")

        if not name:
            errors.append("Service name is required.")

        list_price = None
        if list_price_raw:
            try:
                list_price = _parse_decimal(list_price_raw)
            except Exception as e:
                errors.append(str(e))

        # Uniqueness check (vendor, name) excluding current
        if vendor and name:
            exists = Service.objects.filter(vendor=vendor, name__iexact=name).exclude(pk=service.pk).exists()
            if exists:
                errors.append("A service with this name already exists for the selected vendor.")

        if errors:
            for e in errors:
                messages.error(request, e)

            return render(
                request,
                "portal/service_form.html",
                {
                    "mode": "edit",
                    "service": service,
                    "vendors": vendors,
                    "form_data": {
                        "vendor_id": vendor_id,
                        "name": name,
                        "category": category,
                        "service_code": service_code,
                        "default_currency": default_currency,
                        "default_billing_frequency": default_billing_frequency,
                        "owner_display": owner_display,
                        "allocation_split": allocation_split,
                        "list_price": list_price_raw,
                    },
                },
            )

        # Apply updates
        service.vendor = vendor
        service.name = name
        service.category = category or ""
        service.service_code = service_code or ""
        service.default_currency = default_currency or ""
        service.default_billing_frequency = default_billing_frequency or ""
        service.owner_display = owner_display or ""
        service.allocation_split = allocation_split or ""
        service.list_price = list_price
        service.save()

        messages.success(request, "Service updated successfully.")
        return redirect("portal:service_detail", pk=service.pk)

    # GET: prefill with existing
    form_data = {
        "vendor_id": str(service.vendor_id) if service.vendor_id else "",
        "name": service.name or "",
        "category": service.category or "",
        "service_code": getattr(service, "service_code", "") or "",
        "default_currency": getattr(service, "default_currency", "") or "",
        "default_billing_frequency": getattr(service, "default_billing_frequency", "") or "",
        "owner_display": getattr(service, "owner_display", "") or "",
        "allocation_split": getattr(service, "allocation_split", "") or "",
        "list_price": _as_str(service.list_price) if service.list_price is not None else "",
    }

    return render(
        request,
        "portal/service_form.html",
        {
            "mode": "edit",
            "service": service,
            "vendors": vendors,
            "form_data": form_data,
        },
    )


# ----------
# COST CENTERS
# ----------

@login_required
def cost_centers_list(request):
    cost_centers = (
        CostCenter.objects.all()
        .annotate(contract_count=Count("contracts", distinct=True))
        .annotate(line_count=Count("invoice_lines", distinct=True))
        .order_by("code")
    )
    return render(request, "portal/cost_centers.html", {"cost_centers": cost_centers})


# ----------
# USERS
# ----------

@login_required
def users_list(request):
    users_qs = User.objects.all().order_by("username")

    for u in users_qs:
        UserProfile.objects.get_or_create(user=u)

    users_qs = (
        User.objects.select_related("profile", "profile__cost_center", "profile__manager")
        .order_by("username")
    )
    return render(request, "portal/users.html", {"users": users_qs})


# ----------
# DATA HUB
# ----------

@login_required
def data_hub(request):
    items = []
    for key, cfg in DATA_ENTITIES.items():
        if key == "vendors":
            count = Vendor.objects.count()
        elif key == "cost-centers":
            count = CostCenter.objects.count()
        elif key == "services":
            count = Service.objects.count()
        elif key == "contracts":
            count = Contract.objects.filter(owner=request.user).count()
        elif key == "invoices":
            count = Invoice.objects.filter(owner=request.user).count()
        else:
            count = 0

        items.append({"key": key, "label": cfg["label"], "count": count})

    return render(request, "portal/data_hub.html", {"items": items})


@login_required
def data_import(request, entity: str):
    cfg = _get_entity_or_404(entity)

    if request.method == "POST":
        upload = request.FILES.get("file")
        if not upload:
            messages.error(request, "Please choose a CSV or XLSX file to upload.")
            return redirect("portal:data_import", entity=entity)

        fmt = _detect_format(request, upload.name)

        try:
            rows = _read_table(upload, fmt)
            if not rows:
                messages.warning(request, "The uploaded file has no data rows.")
                return redirect("portal:data_import", entity=entity)

            result = cfg["importer"](rows, request.user)
            messages.success(
                request,
                f"{cfg['label']}: import completed. Created: {result.get('created', 0)}, updated: {result.get('updated', 0)}."
            )
            return redirect("portal:data_hub")

        except Exception as e:
            messages.error(request, f"{cfg['label']}: import failed. {e}")
            return redirect("portal:data_import", entity=entity)

    return render(
        request,
        "portal/data_import.html",
        {
            "entity": entity,
            "label": cfg["label"],
            "template_headers": cfg["template_headers"],
        },
    )


@login_required
def data_export(request, entity: str):
    cfg = _get_entity_or_404(entity)
    fmt = _detect_format(request)

    headers = cfg["template_headers"]
    rows = cfg["exporter"](request.user)

    filename_base = f"datanaut_{entity}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
    if fmt == "xlsx":
        return _workbook_response(f"{filename_base}.xlsx", headers, rows)
    return _csv_response(f"{filename_base}.csv", headers, rows)


@login_required
def data_template(request, entity: str):
    cfg = _get_entity_or_404(entity)
    fmt = _detect_format(request)

    headers = cfg["template_headers"]
    rows: list[list[str]] = []

    filename_base = f"template_{entity}"
    if fmt == "xlsx":
        return _workbook_response(f"{filename_base}.xlsx", headers, rows)
    return _csv_response(f"{filename_base}.csv", headers, rows)


# ----------
# USAGE (placeholder)
# ----------

@login_required
def usage_overview(request):
    return render(request, "portal/usage.html")


# ----------
# LOGOUT HELPER
# ----------

def portal_logout(request):
    logout(request)
    return redirect("login")
