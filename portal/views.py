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
from django.db.models import Sum, Count, Q
from django.db.models.deletion import ProtectedError
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
            contract = form.save(owner=request.user, uploaded_by=request.user)
            messages.success(request, f"Contract '{contract.contract_name}' saved successfully.")
            return redirect("portal:contracts")
    else:
        form = ContractUploadForm()

    context = {"contracts": contracts, "form": form}
    return render(request, "portal/contracts.html", context)


@login_required
def contract_detail(request, pk):
    """
    Detail + inline edit / delete for a single contract.
    """
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

    vendors = Vendor.objects.all().order_by("name")
    cost_centers = CostCenter.objects.all().order_by("code")

    if request.method == "POST":
        action = _as_str(request.POST.get("action")) or "update"

        if action == "delete":
            name = contract.contract_name
            contract.delete()
            messages.success(request, f"Contract '{name}' was deleted.")
            return redirect("portal:contracts")

        # UPDATE
        errors: list[str] = []

        vendor_id = _as_str(request.POST.get("vendor_id"))
        contract_name = _as_str(request.POST.get("contract_name"))
        contract_id = _as_str(request.POST.get("contract_id"))
        contract_type = _as_str(request.POST.get("contract_type"))
        entity = _as_str(request.POST.get("entity"))
        cost_center_id = _as_str(request.POST.get("cost_center_id"))
        currency = _as_str(request.POST.get("currency"))
        status = _as_str(request.POST.get("status"))
        annual_value_raw = _as_str(request.POST.get("annual_value"))
        start_date_raw = _as_str(request.POST.get("start_date"))
        end_date_raw = _as_str(request.POST.get("end_date"))
        renewal_date_raw = _as_str(request.POST.get("renewal_date"))
        notice_period_raw = _as_str(request.POST.get("notice_period_days"))
        notice_date_raw = _as_str(request.POST.get("notice_date"))
        notes = _as_str(request.POST.get("notes"))

        if not contract_name:
            errors.append("Contract name is required.")

        vendor = None
        if not vendor_id:
            errors.append("Vendor is required.")
        else:
            vendor = Vendor.objects.filter(pk=vendor_id).first()
            if not vendor:
                errors.append("Selected vendor does not exist.")

        owning_cost_center = None
        if cost_center_id:
            owning_cost_center = CostCenter.objects.filter(pk=cost_center_id).first()
            if not owning_cost_center:
                errors.append("Selected cost centre does not exist.")

        annual_value = None
        if annual_value_raw:
            try:
                annual_value = _parse_decimal(annual_value_raw)
            except Exception as e:
                errors.append(str(e))

        start_date = None
        end_date = None
        renewal_date = None
        notice_date = None
        try:
            if start_date_raw:
                start_date = _parse_date(start_date_raw)
            if end_date_raw:
                end_date = _parse_date(end_date_raw)
            if renewal_date_raw:
                renewal_date = _parse_date(renewal_date_raw)
            if notice_date_raw:
                notice_date = _parse_date(notice_date_raw)
        except Exception as e:
            errors.append(str(e))

        notice_period_days = None
        if notice_period_raw:
            try:
                notice_period_days = _parse_int(notice_period_raw)
            except Exception as e:
                errors.append(str(e))

        # simple validation for notice vs end_date
        if notice_date and not end_date:
            errors.append("If a notice date is set, end date is required.")
        if notice_date and end_date and notice_date > end_date:
            errors.append("Notice date must be on or before contract end date.")

        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            contract.vendor = vendor
            contract.contract_name = contract_name
            contract.contract_id = contract_id
            contract.contract_type = contract_type
            contract.entity = entity
            contract.owning_cost_center = owning_cost_center
            contract.currency = currency
            contract.status = status or contract.status
            contract.annual_value = annual_value
            contract.start_date = start_date
            contract.end_date = end_date
            contract.renewal_date = renewal_date
            contract.notice_period_days = notice_period_days
            contract.notice_date = notice_date
            contract.notes = notes
            contract.save()

            messages.success(request, "Contract updated successfully.")
            return redirect("portal:contract_detail", pk=contract.pk)

    context = {
        "contract": contract,
        "invoices": invoices,
        "vendors": vendors,
        "cost_centers": cost_centers,
    }
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
            invoice = form.save(owner=request.user)
            messages.success(
                request,
                f"Invoice '{invoice.invoice_number}' saved for vendor {invoice.vendor.name}.",
            )
            if invoice.contract is None:
                messages.warning(request, "Invoice saved, but no matching contract was linked.")
            return redirect("portal:invoices")
    else:
        form = InvoiceUploadForm()

    context = {"invoices": invoices, "total_amount": total_amount, "form": form}
    return render(request, "portal/invoices.html", context)


@login_required
def invoice_detail(request, pk):
    """
    Detail + inline edit / delete for single invoice.
    """
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

    vendors = Vendor.objects.all().order_by("name")
    contracts = Contract.objects.filter(owner=request.user).select_related("vendor").order_by("vendor__name", "contract_name")

    if request.method == "POST":
        action = _as_str(request.POST.get("action")) or "update"

        if action == "delete":
            number = invoice.invoice_number
            invoice.delete()
            messages.success(request, f"Invoice '{number}' was deleted.")
            return redirect("portal:invoices")

        errors: list[str] = []

        vendor_id = _as_str(request.POST.get("vendor_id"))
        contract_id = _as_str(request.POST.get("contract_id"))
        invoice_number = _as_str(request.POST.get("invoice_number"))
        invoice_date_raw = _as_str(request.POST.get("invoice_date"))
        currency = _as_str(request.POST.get("currency"))
        total_amount_raw = _as_str(request.POST.get("total_amount"))
        tax_amount_raw = _as_str(request.POST.get("tax_amount"))
        period_start_raw = _as_str(request.POST.get("period_start"))
        period_end_raw = _as_str(request.POST.get("period_end"))
        notes = _as_str(request.POST.get("notes"))

        if not invoice_number:
            errors.append("Invoice number is required.")

        vendor = None
        if not vendor_id:
            errors.append("Vendor is required.")
        else:
            vendor = Vendor.objects.filter(pk=vendor_id).first()
            if not vendor:
                errors.append("Selected vendor does not exist.")

        contract = None
        if contract_id:
            contract = Contract.objects.filter(owner=request.user, pk=contract_id).first()
            if not contract:
                errors.append("Selected contract does not exist.")

        try:
            invoice_date = _parse_date(invoice_date_raw) if invoice_date_raw else None
        except Exception as e:
            errors.append(str(e))

        total_amount = None
        if total_amount_raw:
            try:
                total_amount = _parse_decimal(total_amount_raw)
            except Exception as e:
                errors.append(str(e))

        tax_amount = None
        if tax_amount_raw:
            try:
                tax_amount = _parse_decimal(tax_amount_raw)
            except Exception as e:
                errors.append(str(e))

        try:
            period_start = _parse_date(period_start_raw) if period_start_raw else None
            period_end = _parse_date(period_end_raw) if period_end_raw else None
        except Exception as e:
            errors.append(str(e))

        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            invoice.vendor = vendor
            invoice.contract = contract
            invoice.invoice_number = invoice_number
            if invoice_date:
                invoice.invoice_date = invoice_date
            invoice.currency = currency or invoice.currency
            if total_amount is not None:
                invoice.total_amount = total_amount
            invoice.tax_amount = tax_amount
            invoice.period_start = period_start
            invoice.period_end = period_end
            invoice.notes = notes

            upload_file = request.FILES.get("file")
            if upload_file:
                invoice.file = upload_file

            invoice.save()
            messages.success(request, "Invoice updated successfully.")
            return redirect("portal:invoice_detail", pk=invoice.pk)

    context = {
        "invoice": invoice,
        "lines": lines,
        "allocation_by_cost_center": allocation_by_cost_center,
        "service_breakdown": service_breakdown,
        "vendors": vendors,
        "contracts": contracts,
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
            vendor = form.save()
            messages.success(request, f"Vendor '{vendor.name}' created successfully.")
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
    """
    Detail + inline edit / delete for vendor.
    """
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

    if request.method == "POST":
        action = _as_str(request.POST.get("action")) or "update"

        if action == "delete":
            name = vendor.name
            try:
                vendor.delete()
                messages.success(request, f"Vendor '{name}' was deleted.")
                return redirect("portal:vendors")
            except ProtectedError:
                messages.error(
                    request,
                    "This vendor cannot be deleted because there are related contracts or invoices.",
                )

        else:
            errors: list[str] = []

            name = _as_str(request.POST.get("name"))
            vendor_type = _as_str(request.POST.get("vendor_type"))
            primary_contact_name = _as_str(request.POST.get("primary_contact_name"))
            primary_contact_email = _as_str(request.POST.get("primary_contact_email"))
            website = _as_str(request.POST.get("website"))
            tags = _as_str(request.POST.get("tags"))
            notes = _as_str(request.POST.get("notes"))

            if not name:
                errors.append("Vendor name is required.")

            valid_types = {choice[0] for choice in Vendor.VENDOR_TYPE_CHOICES}
            if vendor_type and vendor_type not in valid_types:
                errors.append("Invalid vendor type.")

            if errors:
                for e in errors:
                    messages.error(request, e)
            else:
                vendor.name = name
                vendor.vendor_type = vendor_type
                vendor.primary_contact_name = primary_contact_name
                vendor.primary_contact_email = primary_contact_email
                vendor.website = website
                vendor.tags = tags
                vendor.notes = notes
                vendor.save()

                messages.success(request, "Vendor updated successfully.")
                return redirect("portal:vendor_detail", pk=vendor.pk)

    context = {
        "vendor": vendor,
        "contracts": contracts,
        "invoices": invoices,
        "services": services,
        "total_contract_value": total_contract_value,
        "total_invoiced": total_invoiced,
        "vendor_type_choices": Vendor.VENDOR_TYPE_CHOICES,
    }
    return render(request, "portal/vendor_detail.html", context)


# ----------
# SERVICES
# ----------

@login_required
def service_list(request):
    vendors = Vendor.objects.all().order_by("name")
    add_form_data: dict = {}
    add_form_has_errors = False

    if request.method == "POST":
        vendor_id = _as_str(request.POST.get("vendor_id"))
        name = _as_str(request.POST.get("name") or request.POST.get("service_name"))
        category = _as_str(request.POST.get("category"))
        billing_frequency = _as_str(request.POST.get("billing_frequency"))
        default_currency = _as_str(request.POST.get("default_currency"))
        service_code = _as_str(request.POST.get("service_code"))
        owner_display = _as_str(request.POST.get("service_owner") or request.POST.get("owner_display"))
        allocation_split = _as_str(request.POST.get("allocation_split"))
        list_price_raw = _as_str(request.POST.get("list_price"))
        contract_ref = _as_str(request.POST.get("contract_ref"))

        add_form_data = {
            "vendor_id": vendor_id,
            "name": name,
            "category": category,
            "billing_frequency": billing_frequency,
            "default_currency": default_currency,
            "service_code": service_code,
            "owner_display": owner_display,
            "allocation_split": allocation_split,
            "list_price": list_price_raw,
            "contract_ref": contract_ref,
        }

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

        primary_contract = None
        contract_not_found = False
        if contract_ref and vendor:
            contract_filters = Q(contract_name__iexact=contract_ref) | Q(contract_id__iexact=contract_ref)
            try:
                ref_pk = int(contract_ref)
                contract_filters |= Q(pk=ref_pk)
            except (TypeError, ValueError):
                pass

            primary_contract = (
                Contract.objects.filter(owner=request.user, vendor=vendor)
                .filter(contract_filters)
                .first()
            )

            if primary_contract is None:
                contract_not_found = True

        if vendor and name:
            exists = Service.objects.filter(vendor=vendor, name__iexact=name).exists()
            if exists:
                errors.append("A service with this name already exists for the selected vendor.")

        if errors:
            add_form_has_errors = True
            for e in errors:
                messages.error(request, e)
        else:
            Service.objects.create(
                vendor=vendor,
                name=name,
                category=category or "",
                service_code=service_code or "",
                default_currency=default_currency or "",
                default_billing_frequency=billing_frequency or "",
                owner_display=owner_display or "",
                allocation_split=allocation_split or "",
                list_price=list_price,
                primary_contract=primary_contract,
            )
            messages.success(request, "Service created successfully.")
            if contract_not_found:
                messages.warning(request, "Service saved, but no matching contract was linked.")
            return redirect("portal:services")

    services = (
        Service.objects.select_related("vendor", "primary_contract")
        .order_by("vendor__name", "name")
    )
    context = {
        "services": services,
        "vendors": vendors,
        "add_form_data": add_form_data,
        "add_form_has_errors": add_form_has_errors,
    }
    return render(request, "portal/services.html", context)


@login_required
def service_detail(request, pk: int):
    """
    Service detail + inline edit / delete.
    Services are global across portal.
    """
    service = get_object_or_404(Service.objects.select_related("vendor", "primary_contract"), pk=pk)

    vendors = Vendor.objects.all().order_by("name")
    contracts = Contract.objects.filter(owner=request.user, vendor=service.vendor).order_by("contract_name")

    related_contracts = (
        service.contracts.filter(owner=request.user)
        .select_related("vendor")
        .order_by("vendor__name", "contract_name")
    )
    invoice_lines = (
        service.invoice_lines.select_related("invoice", "invoice__vendor")
        .order_by("-invoice__invoice_date", "-invoice__id")[:10]
    )

    if request.method == "POST":
        action = _as_str(request.POST.get("action")) or "update"

        if action == "delete":
            name = str(service)
            service.delete()
            messages.success(request, f"Service '{name}' was deleted.")
            return redirect("portal:services")

        errors: list[str] = []

        vendor_id = _as_str(request.POST.get("vendor_id"))
        name = _as_str(request.POST.get("name"))
        category = _as_str(request.POST.get("category"))
        billing_frequency = _as_str(request.POST.get("billing_frequency"))
        default_currency = _as_str(request.POST.get("default_currency"))
        service_code = _as_str(request.POST.get("service_code"))
        owner_display = _as_str(request.POST.get("owner_display"))
        allocation_split = _as_str(request.POST.get("allocation_split"))
        list_price_raw = _as_str(request.POST.get("list_price"))
        primary_contract_id = _as_str(request.POST.get("primary_contract_id"))

        if not name:
            errors.append("Service name is required.")

        vendor = None
        if not vendor_id:
            errors.append("Vendor is required.")
        else:
            vendor = Vendor.objects.filter(pk=vendor_id).first()
            if not vendor:
                errors.append("Selected vendor does not exist.")

        list_price = None
        if list_price_raw:
            try:
                list_price = _parse_decimal(list_price_raw)
            except Exception as e:
                errors.append(str(e))

        primary_contract = None
        if primary_contract_id:
            primary_contract = Contract.objects.filter(owner=request.user, pk=primary_contract_id).first()
            if not primary_contract:
                errors.append("Selected primary contract does not exist.")

        # uniqueness check per vendor + name
        if vendor and name:
            exists = (
                Service.objects.filter(vendor=vendor, name__iexact=name)
                .exclude(pk=service.pk)
                .exists()
            )
            if exists:
                errors.append("A service with this name already exists for the selected vendor.")

        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            service.vendor = vendor
            service.name = name
            service.category = category or ""
            service.default_billing_frequency = billing_frequency or ""
            service.default_currency = default_currency or ""
            service.service_code = service_code or ""
            service.owner_display = owner_display or ""
            service.allocation_split = allocation_split or ""
            service.list_price = list_price
            service.primary_contract = primary_contract
            service.save()

            messages.success(request, "Service updated successfully.")
            return redirect("portal:service_detail", pk=service.pk)

    context = {
        "service": service,
        "vendors": vendors,
        "contracts": contracts,
        "related_contracts": related_contracts,
        "invoice_lines": invoice_lines,
    }
    return render(request, "portal/service_detail.html", context)


@login_required
def service_create(request):
    """
    Create service via portal.
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

        # Uniqueness heuristic: (vendor, name case-insensitive)
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
    Legacy endpoint – keeping it in case ти трябва,
    но детайлната страница вече покрива edit.
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


@login_required
def user_detail(request, pk: int):
    """
    Detail + inline edit / delete за отделен user.
    """
    user_obj = get_object_or_404(
        User.objects.select_related("profile", "profile__cost_center", "profile__manager"),
        pk=pk,
    )
    profile, _ = UserProfile.objects.get_or_create(user=user_obj)

    cost_centers = CostCenter.objects.all().order_by("code")
    managers = User.objects.exclude(pk=user_obj.pk).order_by("username")

    if request.method == "POST":
        action = _as_str(request.POST.get("action")) or "update"

        if action == "delete":
            if user_obj == request.user:
                messages.error(request, "You cannot delete the currently logged-in user.")
            else:
                username = user_obj.username
                user_obj.delete()
                messages.success(request, f"User '{username}' was deleted.")
            return redirect("portal:users")

        # UPDATE
        errors: list[str] = []

        username = _as_str(request.POST.get("username"))
        email = _as_str(request.POST.get("email"))
        first_name = _as_str(request.POST.get("first_name"))
        last_name = _as_str(request.POST.get("last_name"))
        is_active_flag = request.POST.get("is_active") == "on"

        full_name = _as_str(request.POST.get("full_name"))
        cost_center_id = _as_str(request.POST.get("cost_center_id"))
        manager_id = _as_str(request.POST.get("manager_id"))
        location = _as_str(request.POST.get("location"))
        legal_entity = _as_str(request.POST.get("legal_entity"))
        phone_number = _as_str(request.POST.get("phone_number"))

        if not username:
            errors.append("Username is required.")
        else:
            if (
                User.objects.exclude(pk=user_obj.pk)
                .filter(username__iexact=username)
                .exists()
            ):
                errors.append("Another user with this username already exists.")

        if email:
            if (
                User.objects.exclude(pk=user_obj.pk)
                .filter(email__iexact=email)
                .exists()
            ):
                errors.append("Another user with this email already exists.")

        cost_center = None
        if cost_center_id:
            cost_center = CostCenter.objects.filter(pk=cost_center_id).first()
            if not cost_center:
                errors.append("Selected cost centre does not exist.")

        manager = None
        if manager_id:
            manager = User.objects.filter(pk=manager_id).first()
            if not manager:
                errors.append("Selected manager does not exist.")

        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            user_obj.username = username
            user_obj.email = email
            user_obj.first_name = first_name
            user_obj.last_name = last_name
            user_obj.is_active = is_active_flag
            user_obj.save()

            profile.full_name = full_name
            profile.cost_center = cost_center
            profile.manager = manager
            profile.location = location
            profile.legal_entity = legal_entity
            profile.phone_number = phone_number
            profile.save()

            messages.success(request, "User updated successfully.")
            return redirect("portal:user_detail", pk=user_obj.pk)

    return render(
        request,
        "portal/user_detail.html",
        {
            "user_obj": user_obj,
            "cost_centers": cost_centers,
            "managers": managers,
        },
    )

# ----------
# SEARCH (global)
# ----------

@login_required
def global_search(request):
    """
    Global search across vendors, services, contracts, invoices and users.
    """
    query = _as_str(request.GET.get("q"))

    vendors = []
    services = []
    contracts = []
    invoices = []
    users = []

    if query:
        vendors = (
            Vendor.objects.filter(
                Q(name__icontains=query)
                | Q(tags__icontains=query)
                | Q(primary_contact_name__icontains=query)
                | Q(primary_contact_email__icontains=query)
            )
            .order_by("name")[:25]
        )

        services = (
            Service.objects.select_related("vendor")
            .filter(
                Q(name__icontains=query)
                | Q(category__icontains=query)
                | Q(service_code__icontains=query)
                | Q(vendor__name__icontains=query)
            )
            .order_by("vendor__name", "name")[:25]
        )

        contracts = (
            Contract.objects.select_related("vendor", "owning_cost_center")
            .filter(owner=request.user)
            .filter(
                Q(contract_name__icontains=query)
                | Q(contract_id__icontains=query)
                | Q(vendor__name__icontains=query)
            )
            .order_by("-start_date", "-created_at")[:25]
        )

        invoices = (
            Invoice.objects.select_related("vendor", "contract")
            .filter(owner=request.user)
            .filter(
                Q(invoice_number__icontains=query)
                | Q(vendor__name__icontains=query)
                | Q(contract__contract_name__icontains=query)
            )
            .order_by("-invoice_date", "-id")[:25]
        )

        users = (
            User.objects.select_related("profile", "profile__cost_center")
            .filter(
                Q(username__icontains=query)
                | Q(first_name__icontains=query)
                | Q(last_name__icontains=query)
                | Q(email__icontains=query)
                | Q(profile__full_name__icontains=query)
            )
            .order_by("username")[:25]
        )

    has_results = bool(query and (vendors or services or contracts or invoices or users))

    return render(
        request,
        "portal/search_results.html",
        {
            "query": query,
            "vendors": vendors,
            "services": services,
            "contracts": contracts,
            "invoices": invoices,
            "users": users,
            "has_results": has_results,
        },
    )

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
# USAGE
# ----------

@login_required
def usage_overview(request):
    # демо екрана с сигналите, dormant users и overlapping products
    return render(request, "portal/usage.html")


@login_required
def usage_invoices(request):
    """
    Invoice inventory в Usage – показва същата таблица като Invoices list,
    но менюто вляво е Usage inventory.
    """
    return invoice_list(request)


@login_required
def usage_contracts(request):
    """
    Contract inventory в Usage.
    """
    return contract_list(request)


@login_required
def usage_vendors(request):
    """
    Vendor inventory в Usage.
    """
    return vendor_list(request)


@login_required
def usage_users(request):
    """
    User inventory в Usage.
    """
    return users_list(request)

# ----------
# USAGE INVENTORY VIEWS
# ----------

@login_required
def usage_invoices(request):
    """
    Simple invoice inventory table for Usage section.
    """
    invoices = (
        Invoice.objects.filter(owner=request.user)
        .select_related("vendor")
        .order_by("-invoice_date", "-id")
    )
    return render(request, "portal/usage_invoices.html", {"invoices": invoices})


@login_required
def usage_contract(request):
    """
    Contract inventory table for Usage section.
    """
    contracts = (
        Contract.objects.filter(owner=request.user)
        .select_related("vendor")
        .order_by("-start_date", "-created_at")
    )
    return render(request, "portal/usage_contract.html", {"contracts": contracts})


@login_required
def usage_vendors(request):
    """
    Vendor inventory view, showing linkage към договори и фактури.
    """
    vendors = (
        Vendor.objects
        .annotate(
            contract_count=Count(
                "contracts",
                filter=Q(contracts__owner=request.user),
                distinct=True,
            ),
            invoice_count=Count(
                "invoices",
                filter=Q(invoices__owner=request.user),
                distinct=True,
            ),
        )
        .order_by("name")
    )
    return render(request, "portal/usage_vendors.html", {"vendors": vendors})


@login_required
def usage_users(request):
    """
    User inventory – базова таблица с всички потребители.
    """
    # гарантираме, че всеки има профил
    users_qs = get_user_model().objects.all().order_by("username")
    for u in users_qs:
        UserProfile.objects.get_or_create(user=u)

    users_qs = (
        get_user_model().objects
        .select_related("profile", "profile__cost_center")
        .order_by("username")
    )
    return render(request, "portal/usage_users.html", {"users": users_qs})

# ----------
# LOGOUT HELPER
# ----------

def portal_logout(request):
    logout(request)
    return redirect("login")
