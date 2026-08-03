"""
Second pass over the demonstration dataset.

Three defects show up on screen and each of them undermines the demo for a
different reason:

  * "Healthy usage 0%" reads as a broken metric rather than a finding. The
    cause is that synthetic users have never logged in, so every licence is
    classified dormant. The honest fix is to give the users realistic login
    history, not to soften the dormancy rule.

  * Vendor and service categories were assigned at random, so SWIFT appears
    under "analytics" and Markit under "research". Anyone in this market spots
    that immediately.

  * A misspelling ("Reffea", "Refinitif") survived from the original import.

Usage:
    python manage.py fix_demo_data --dry-run
    python manage.py fix_demo_data
"""

import random
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from portal.models import Vendor, Service

User = get_user_model()


# Correct categories for the vendors used in the demo set.
VENDOR_TYPES = {
    "Bloomberg": "market_data",
    "Refinitiv": "market_data",
    "LSEG": "market_data",
    "ICE Data Services": "market_data",
    "Nasdaq": "market_data",
    "Euronext": "market_data",
    "Deutsche Börse": "market_data",
    "CME Group": "market_data",
    "Cboe Global Markets": "market_data",
    "Bolsa de Madrid": "market_data",
    "SIX Financial Information": "market_data",
    "FactSet": "market_data",
    "BMLL Technologies": "market_data",
    "Quodd": "market_data",

    "S&P Global": "reference_data",
    "Moody's Analytics": "reference_data",
    "Fitch Solutions": "reference_data",
    "Markit": "reference_data",
    "IHS Markit": "reference_data",
    "Morningstar": "reference_data",
    "Rimes": "reference_data",
    "NeoXam": "reference_data",
    "Dow Jones": "reference_data",
    "Reuters News": "reference_data",

    "MSCI": "indexes",
    "FTSE Russell": "indexes",

    "SWIFT": "connectivity",
    "DTCC": "connectivity",
    "TP ICAP": "connectivity",
    "Tradeweb": "connectivity",
    "Exegy": "connectivity",
    "Xignite": "connectivity",
    "MarketAxess": "connectivity",
    "ITG": "connectivity",

    "Broadridge": "other",
    "SS&C": "other",
    "Enfusion": "other",
    "Charles River": "other",
    "Adaptive": "other",
    "OneTick": "other",
    "Kx Systems": "other",
    "Bloomberg PORT": "other",

    "Argus Media": "reference_data",
    "Platts": "reference_data",
    "ICIS": "reference_data",
    "EPEX SPOT": "market_data",
    "Nord Pool": "market_data",
    "EEX": "market_data",
    "Montel": "market_data",
    "EnAppSys": "market_data",
    "Genscape": "market_data",
    "Wood Mackenzie": "reference_data",
}

# Service category follows the vendor's nature.
SERVICE_CATEGORY_BY_VENDOR_TYPE = {
    "market_data": ["data_feed", "terminal"],
    "reference_data": ["data_feed", "analytics"],
    "indexes": ["index_license"],
    "connectivity": ["connectivity"],
    "other": ["analytics", "other"],
}

TYPOS = {
    "Reffea": "Refinitiv",
    "Refinitif": "Refinitiv",
    "Refinitv": "Refinitiv",
    "Bloomberd": "Bloomberg",
}


class Command(BaseCommand):
    help = "Fix healthy-usage metric, vendor/service categories and name typos in demo data."

    def add_arguments(self, p):
        p.add_argument("--dry-run", action="store_true")
        p.add_argument(
            "--dormant-share",
            type=float,
            default=0.28,
            help="Share of users left without a recent login, so dormancy findings survive. Default 0.28",
        )

    def handle(self, *a, **o):
        dry = o["dry_run"]
        dormant_share = o["dormant_share"]
        if dry:
            self.stdout.write(self.style.WARNING("DRY RUN — nothing will be written.\n"))

        with transaction.atomic():
            self._typos(dry)
            self._vendor_types(dry)
            self._service_categories(dry)
            self._logins(dormant_share, dry)
            if dry:
                transaction.set_rollback(True)

        self.stdout.write(self.style.SUCCESS(
            "\nDry run complete — re-run without --dry-run to apply." if dry else "\nDone."))

    # ------------------------------------------------------------------ typos
    def _typos(self, dry):
        n = 0
        for v in Vendor.objects.all():
            name = v.name or ""
            fixed = name
            for bad, good in TYPOS.items():
                if bad.lower() in fixed.lower():
                    fixed = fixed.replace(bad, good)
            if fixed != name:
                self.stdout.write(f"  {name:26} -> {fixed}")
                if not dry:
                    v.name = fixed
                    v.save(update_fields=["name"])
                n += 1
        self.stdout.write(f"Typos        : {n} vendor names corrected")

    # ----------------------------------------------------------- vendor types
    def _vendor_types(self, dry):
        n = 0
        for v in Vendor.objects.all().order_by("name"):
            want = VENDOR_TYPES.get((v.name or "").strip())
            if not want or getattr(v, "vendor_type", None) == want:
                continue
            if n < 15:
                self.stdout.write(f"  {v.name:26} {getattr(v, 'vendor_type', '?'):16} -> {want}")
            if not dry:
                v.vendor_type = want
                v.save(update_fields=["vendor_type"])
            n += 1
        if n > 15:
            self.stdout.write(f"  … and {n - 15} more")
        self.stdout.write(f"Vendor types : {n} corrected")

    # -------------------------------------------------------- service classes
    def _service_categories(self, dry):
        rng = random.Random(4242)
        n = 0
        for s in Service.objects.select_related("vendor").all().order_by("id"):
            vtype = getattr(s.vendor, "vendor_type", None) if s.vendor else None
            options = SERVICE_CATEGORY_BY_VENDOR_TYPE.get(vtype)
            if not options:
                continue
            want = options[0] if len(options) == 1 else rng.choice(options)
            if getattr(s, "category", None) == want:
                continue
            if not dry:
                s.category = want
                s.save(update_fields=["category"])
            n += 1
        self.stdout.write(f"Services     : {n} categories aligned to their vendor")

    # ---------------------------------------------------------------- logins
    def _logins(self, dormant_share, dry):
        """
        Give most users a plausible recent login and leave a deliberate minority
        dormant. Without this every seat counts as unused and the headline
        metric reads 0% healthy, which looks like a bug rather than a finding.
        """
        rng = random.Random(99)
        now = timezone.now()
        users = list(User.objects.all().order_by("id"))
        if not users:
            self.stdout.write("Logins       : no users found")
            return

        active = dormant = never = 0
        for u in users:
            r = rng.random()
            if r < dormant_share * 0.35:
                # never logged in — the strongest decommissioning candidate
                new_login = None
                never += 1
            elif r < dormant_share:
                # stale: beyond the 60–90 day dormancy window
                new_login = now - timedelta(days=rng.randint(95, 400))
                dormant += 1
            else:
                # healthy: seen within the last few weeks
                new_login = now - timedelta(days=rng.randint(0, 45),
                                            hours=rng.randint(0, 23))
                active += 1
            if not dry:
                u.last_login = new_login
                u.save(update_fields=["last_login"])

        total = len(users)
        healthy_pct = round(100 * active / total)
        self.stdout.write(
            f"Logins       : {total} users — {active} active, {dormant} stale, {never} never"
        )
        self.stdout.write(
            f"               expected healthy usage ≈ {healthy_pct}% "
            f"(was 0%, because no demo user had ever logged in)"
        )
