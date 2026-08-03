"""Rename placeholder demo records into realistic names."""
import re
from django.core.management.base import BaseCommand
from django.db import transaction
from portal.models import Vendor, CostCenter, Contract

VENDORS = [
    "Bloomberg", "Refinitiv", "LSEG", "ICE Data Services", "S&P Global",
    "Moody's Analytics", "MSCI", "FTSE Russell", "Markit", "SIX Financial Information",
    "Nasdaq", "Tradeweb", "Morningstar", "FactSet", "Euronext", "Deutsche Börse",
    "CME Group", "TP ICAP", "Exegy", "Quodd", "Xignite", "BMLL Technologies",
    "Rimes", "NeoXam", "Bolsa de Madrid", "Cboe Global Markets", "ITG",
    "Bloomberg PORT", "Fitch Solutions", "DTCC", "SWIFT", "Broadridge",
    "SS&C", "Enfusion", "Charles River", "Adaptive", "OneTick", "Kx Systems",
    "Dow Jones", "Reuters News", "Argus Media", "Platts", "ICIS",
    "EPEX SPOT", "Nord Pool", "EEX", "Montel", "EnAppSys", "Genscape", "Wood Mackenzie",
]

# Keep the existing business unit, replace the numbered desk with a real one.
DESKS_BY_UNIT = {
    "Markets":            ["Rates", "Credit", "FX", "Equities", "Commodities", "Cash Equities",
                           "Structured Products", "Money Markets", "Derivatives", "Futures"],
    "Finance":            ["Treasury", "Financial Control", "Product Control", "Tax",
                           "Regulatory Reporting", "Planning & Analysis", "Capital Management"],
    "Risk":               ["Market Risk", "Credit Risk", "Operational Risk", "Liquidity Risk",
                           "Model Validation", "Stress Testing"],
    "Operations":         ["Settlements", "Reconciliations", "Corporate Actions",
                           "Client Onboarding", "Collateral", "Trade Support"],
    "Asset Management":   ["Portfolio Management", "Research", "Multi-Asset", "Fixed Income",
                           "Equity Strategies", "Client Reporting"],
    "Investment Banking": ["ECM", "DCM", "M&A Advisory", "Leveraged Finance",
                           "Coverage", "Syndicate"],
}

ENTITY_MAP = {
    "group":      "{g} Group",
    "bank":       "{g} Bank AG",
    "securities": "{g} Securities Ltd",
    "asset":      "{g} Asset Management",
    "capital":    "{g} Capital GmbH",
    "markets":    "{g} Markets SA",
    "treasury":   "{g} Treasury BV",
}
ENTITY_FALLBACK = ["{g} Group", "{g} Bank AG", "{g} Securities Ltd",
                   "{g} Asset Management", "{g} Capital GmbH"]

PH_VENDOR = re.compile(r"^\s*vendor\s*[-_ ]?\d+\s*$", re.I)
PH_ENTITY = re.compile(r"^\s*example\b", re.I)
PH_DESK = re.compile(r"^\s*(?P<unit>.+?)\s*[–-]\s*desk\s*\d+\s*$", re.I)


class Command(BaseCommand):
    help = "Rename placeholder demo data (Vendor 17, Example Group, Desk 21)."

    def add_arguments(self, p):
        p.add_argument("--group", default="Meridian")
        p.add_argument("--dry-run", action="store_true")

    def handle(self, *a, **o):
        group, dry = o["group"], o["dry_run"]
        if dry:
            self.stdout.write(self.style.WARNING("DRY RUN — nothing will be written.\n"))

        with transaction.atomic():
            self._vendors(dry)
            self._entities(group, dry)
            self._cost_centres(dry)
            self._contracts(dry)
            if dry:
                transaction.set_rollback(True)

        self.stdout.write(self.style.SUCCESS(
            "\nDry run complete — re-run without --dry-run to apply." if dry else "\nDone."))

    def _vendors(self, dry):
        ph = [v for v in Vendor.objects.order_by("id") if PH_VENDOR.match(v.name or "")]
        taken = set(Vendor.objects.exclude(id__in=[v.id for v in ph])
                    .values_list("name", flat=True))
        pool = [n for n in VENDORS if n not in taken]
        done = 0
        for v, new in zip(ph, pool):
            self.stdout.write(f"  {v.name:22} -> {new}")
            if not dry:
                v.name = new
                v.save(update_fields=["name"])
            done += 1
        left = len(ph) - done
        self.stdout.write(f"Vendors      : {done} renamed"
                          + (f"  [!] {left} still placeholder — extend VENDORS" if left else ""))

    def _entities(self, group, dry):
        cph = [c for c in Contract.objects.order_by("id") if PH_ENTITY.match(c.entity or "")]
        distinct = []
        for c in cph:
            if c.entity not in distinct:
                distinct.append(c.entity)

        mapping, used = {}, 0
        for old in distinct:
            low = old.lower()
            hit = next((tpl for key, tpl in ENTITY_MAP.items() if key in low), None)
            if hit is None:
                hit = ENTITY_FALLBACK[used % len(ENTITY_FALLBACK)]
                used += 1
            mapping[old] = hit.format(g=group)
            self.stdout.write(f"  {old:22} -> {mapping[old]}")

        if not dry:
            for c in cph:
                c.entity = mapping[c.entity]
                c.save(update_fields=["entity"])
        self.stdout.write(f"Entities     : {len(distinct)} labels across {len(cph)} contracts")

    def _cost_centres(self, dry):
        counters, n = {}, 0
        for cc in CostCenter.objects.order_by("code"):
            m = PH_DESK.match(cc.name or "")
            if not m:
                continue
            unit = m.group("unit").strip()
            desks = DESKS_BY_UNIT.get(unit)
            if not desks:
                desks = [d for lst in DESKS_BY_UNIT.values() for d in lst]
            i = counters.get(unit, 0)
            counters[unit] = i + 1
            desk = desks[i % len(desks)]
            new = f"{unit} – {desk}" if i < len(desks) else f"{unit} – {desk} {i // len(desks) + 1}"
            self.stdout.write(f"  {cc.code} {cc.name:30} -> {new}")
            if not dry:
                cc.name = new
                cc.save(update_fields=["name"])
            n += 1
        self.stdout.write(f"Cost centres : {n} renamed")

    def _contracts(self, dry):
        n = 0
        for c in Contract.objects.select_related("vendor").order_by("id"):
            m = re.match(r"^(.*?)\s+core licence\s+(\d+)\s*$", c.contract_name or "", re.I)
            if not m or not c.vendor:
                continue
            new = f"{c.vendor.name} core licence {m.group(2)}"
            if new != c.contract_name:
                if not dry:
                    c.contract_name = new
                    c.save(update_fields=["contract_name"])
                n += 1
        self.stdout.write(f"Contracts    : {n} names refreshed")