# portal/kpi.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

from django.db.models import Sum, Count
from django.utils import timezone

from .models import (
    InvoiceLine,
    Service,
    ServiceAssignment,
)


@dataclass(frozen=True)
class DashboardKpis:
    dormant_exposure: Decimal = Decimal("0")
    duplicate_exposure: Decimal = Decimal("0")
    est_optimisation_pct: Optional[Decimal] = None
    est_optimisation_amount: Optional[Decimal] = None


def _safe_decimal(v) -> Decimal:
    if v is None:
        return Decimal("0")
    if isinstance(v, Decimal):
        return v
    try:
        return Decimal(str(v))
    except Exception:
        return Decimal("0")


def compute_dashboard_kpis(*, owner, total_spend_12m: Decimal) -> Dict[str, Any]:
    """
    Enterprise-safe KPI computation for dashboard.

    Works even when:
      - InvoiceLine is empty
      - Service.list_price is empty

    Falls back to indicative model:
      - avg_cost_per_assignment = total_spend_12m / total_assignments
      - dormant_exposure = dormant_assignments * avg_cost_per_assignment * dormant_factor
      - duplicate_exposure = overlap_assignments * avg_cost_per_assignment * duplicate_factor
    """
    total_spend_12m = _safe_decimal(total_spend_12m)

    # If there is zero spend, we can still show zeros safely
    if total_spend_12m <= 0:
        return {
            "kpi_dormant_exposure": Decimal("0"),
            "kpi_duplicate_exposure": Decimal("0"),
            "kpi_est_optimisation_pct": None,
            "kpi_est_optimisation_amount": None,
        }

    dormant = _compute_dormant_exposure(owner=owner, total_spend_12m=total_spend_12m)
    duplicate = _compute_duplicate_coverage_exposure(owner=owner, total_spend_12m=total_spend_12m)

    num = _safe_decimal(dormant) + _safe_decimal(duplicate)

    est_pct = None
    est_amount = None
    if num > 0 and total_spend_12m > 0:
        est_amount = num
        est_pct = (num / total_spend_12m) * Decimal("100")

    return {
        "kpi_dormant_exposure": dormant,
        "kpi_duplicate_exposure": duplicate,
        "kpi_est_optimisation_pct": est_pct,
        "kpi_est_optimisation_amount": est_amount,
    }


# -----------------------------
# Helpers for fallback model
# -----------------------------

def _avg_cost_per_assignment(*, total_spend_12m: Decimal) -> Decimal:
    """
    Average annual cost per ServiceAssignment across the dataset.
    This is a robust fallback when list_price / invoice lines are not available.
    """
    total_assignments = ServiceAssignment.objects.count()
    if total_assignments <= 0:
        return Decimal("0")
    return total_spend_12m / Decimal(str(total_assignments))


def _service_cost_map_from_list_price_or_lines(*, owner) -> Dict[int, Decimal]:
    """
    Best-effort baseline cost per service assignment:
      - Service.list_price (assumed annual per licence) if present
      - else InvoiceLine spend over 12m / assignment count (per service)
    """
    today = timezone.now().date()
    start_12m = today - timedelta(days=365)

    costs: Dict[int, Decimal] = {}

    # 1) list_price wins
    for s in Service.objects.all():
        if s.list_price is not None and s.list_price > 0:
            costs[s.id] = _safe_decimal(s.list_price)

    # 2) fallback from InvoiceLine allocations (if lines exist)
    # NOTE: InvoiceLine doesn't have owner directly; owner is on invoice.
    alloc = (
        InvoiceLine.objects
        .filter(invoice__owner=owner, invoice__invoice_date__gte=start_12m)
        .exclude(service_id__isnull=True)
        .values("service_id")
        .annotate(total=Sum("line_amount"))
    )
    alloc_map = {row["service_id"]: _safe_decimal(row["total"]) for row in alloc if row["service_id"]}

    assn = (
        ServiceAssignment.objects
        .values("service_id")
        .annotate(cnt=Count("id"))
    )
    assn_map = {row["service_id"]: int(row["cnt"] or 0) for row in assn if row["service_id"]}

    for service_id, total in alloc_map.items():
        if service_id in costs:
            continue
        cnt = assn_map.get(service_id, 0)
        if cnt > 0 and total > 0:
            costs[service_id] = total / Decimal(str(cnt))

    return costs


# -----------------------------
# KPI 1: Dormant exposure
# -----------------------------

def _compute_dormant_exposure(*, owner, total_spend_12m: Decimal) -> Decimal:
    """
    Dormant exposure model (robust):
      - If InvoiceLine exists: dormant = users with assignments but no InvoiceLine in last 90d
        exposure = sum(cost per assigned service)
      - If not: fallback to indicative model on assignments:
        dormant_exposure = total_assignments * dormant_factor * avg_cost_per_assignment

    dormant_factor default = 0.12 (12% of assigned population / exposure proxy)
    You can tune it later based on real usage tracking.
    """
    today = timezone.now().date()
    cutoff = today - timedelta(days=90)

    # If we have InvoiceLines, try the more specific logic
    lines_exist = InvoiceLine.objects.filter(invoice__owner=owner).exists()
    if lines_exist:
        # assigned users
        assigned_user_ids = list(
            ServiceAssignment.objects
            .filter(user__is_active=True)
            .values_list("user_id", flat=True)
            .distinct()
        )
        if not assigned_user_ids:
            return Decimal("0")

        active_recent_user_ids = set(
            InvoiceLine.objects
            .filter(invoice__owner=owner, invoice__invoice_date__gte=cutoff, user_id__in=assigned_user_ids)
            .exclude(user_id__isnull=True)
            .values_list("user_id", flat=True)
            .distinct()
        )

        dormant_user_ids = [uid for uid in assigned_user_ids if uid not in active_recent_user_ids]
        if not dormant_user_ids:
            return Decimal("0")

        service_cost = _service_cost_map_from_list_price_or_lines(owner=owner)
        total = Decimal("0")

        assignments = (
            ServiceAssignment.objects
            .filter(user_id__in=dormant_user_ids)
            .select_related("service")
        )

        avg_cost = _avg_cost_per_assignment(total_spend_12m=total_spend_12m)

        for a in assignments:
            sid = a.service_id
            c = service_cost.get(sid)
            # if we can't price the service, fall back to avg assignment cost
            total += c if (c is not None and c > 0) else avg_cost

        return total

    # Fallback: purely indicative from assignment base
    total_assignments = ServiceAssignment.objects.count()
    if total_assignments <= 0:
        return Decimal("0")

    avg_cost = _avg_cost_per_assignment(total_spend_12m=total_spend_12m)
    dormant_factor = Decimal("0.12")  # 12% indicative
    return (Decimal(str(total_assignments)) * avg_cost * dormant_factor)


# -----------------------------
# KPI 2: Duplicate coverage exposure
# -----------------------------

def _compute_duplicate_coverage_exposure(*, owner, total_spend_12m: Decimal) -> Decimal:
    """
    Duplicate coverage exposure model:
      - Detect overlaps at cost_center + category level:
        if a cost center has assignments for >1 vendor within same service.category => overlap
      - Exposure estimated from "extra vendors" baseline costs.
      - If we can't price per service, fallback to avg assignment cost.

    duplicate_factor is applied as a conservative redundancy multiplier (default 0.35).
    """
    service_cost = _service_cost_map_from_list_price_or_lines(owner=owner)
    avg_cost = _avg_cost_per_assignment(total_spend_12m=total_spend_12m)

    assignments = (
        ServiceAssignment.objects
        .select_related("service__vendor", "user__profile__cost_center", "service")
    )

    # cc -> category -> vendor -> list(service_id)
    bucket: Dict[int, Dict[str, Dict[int, list[int]]]] = {}

    for a in assignments:
        profile = getattr(a.user, "profile", None)
        cc = getattr(profile, "cost_center", None) if profile else None
        if cc is None:
            continue

        svc = a.service
        if svc is None or svc.vendor is None:
            continue

        cc_id = cc.id
        category = (svc.category or "other").strip() or "other"
        vendor_id = svc.vendor_id
        service_id = svc.id

        bucket.setdefault(cc_id, {}).setdefault(category, {}).setdefault(vendor_id, []).append(service_id)

    total_dup_base = Decimal("0")

    for cc_id, by_cat in bucket.items():
        for category, by_vendor in by_cat.items():
            if len(by_vendor) <= 1:
                continue

            # price each vendor inside this cc/category
            vendor_costs: list[Tuple[int, Decimal]] = []
            for vid, service_ids in by_vendor.items():
                v_total = Decimal("0")
                for sid in service_ids:
                    c = service_cost.get(sid)
                    v_total += c if (c is not None and c > 0) else avg_cost
                vendor_costs.append((vid, v_total))

            vendor_costs.sort(key=lambda x: x[1], reverse=True)

            # keep top as "primary", count rest as duplicate base
            for vid, v_total in vendor_costs[1:]:
                total_dup_base += v_total

    # Apply conservative redundancy factor (not everything is fully redundant)
    duplicate_factor = Decimal("0.35")
    return total_dup_base * duplicate_factor
