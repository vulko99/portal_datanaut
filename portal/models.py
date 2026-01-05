# portal/models.py
from datetime import timedelta

from django.db import models
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from django.db.models import Q  # <-- ADD

User = get_user_model()


# ---------- VENDOR ----------

class Vendor(models.Model):
    MARKET_DATA = "market_data"
    REFERENCE_DATA = "reference_data"
    INDEXES = "indexes"
    CONNECTIVITY = "connectivity"
    OTHER = "other"

    VENDOR_TYPE_CHOICES = [
        (MARKET_DATA, "Market data"),
        (REFERENCE_DATA, "Reference data"),
        (INDEXES, "Indexes"),
        (CONNECTIVITY, "Connectivity"),
        (OTHER, "Other"),
    ]

    name = models.CharField(max_length=255)

    # soft-close flag (True = Active, False = Closed)
    # Used by views/templates for "Show Closed" behaviour.
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Soft status flag. True = Active, False = Closed (hidden unless Show Closed is enabled).",
    )

    vendor_type = models.CharField(
        max_length=50,
        choices=VENDOR_TYPE_CHOICES,
        blank=True,
    )
    primary_contact_name = models.CharField(
        max_length=255,
        blank=True,
    )
    primary_contact_email = models.EmailField(
        blank=True,
    )
    website = models.URLField(
        blank=True,
    )
    notes = models.TextField(
        blank=True,
        help_text="Internal notes for this vendor",
    )
    tags = models.CharField(
        max_length=255,
        blank=True,
        help_text="Comma-separated tags (e.g. market data, EMEA, Tier1)",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("portal:vendor_detail", kwargs={"pk": self.pk})


# ---------- COST CENTER ----------

class CostCenter(models.Model):
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=255)

    business_unit = models.CharField(max_length=255, blank=True)
    region = models.CharField(max_length=255, blank=True)

    default_approver = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_cost_centers",
        help_text="Default approver for spend / licenses on this cost center.",
    )

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} – {self.name}"


# ---------- USER PROFILE ----------

class UserProfile(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    full_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Override if different from first_name + last_name.",
    )
    cost_center = models.ForeignKey(
        CostCenter,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="users",
    )
    manager = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="team_members",
        help_text="Direct manager of this user.",
    )
    location = models.CharField(
        max_length=255,
        blank=True,
        help_text="Office / city / region.",
    )
    legal_entity = models.CharField(
        max_length=255,
        blank=True,
        help_text="Legal entity this user belongs to.",
    )
    phone_number = models.CharField(
        max_length=50,
        blank=True,
        help_text="Work phone, extension or mobile.",
    )

    def __str__(self) -> str:
        return self.full_name or self.user.get_username()


# ---------- SERVICE ----------

class Service(models.Model):
    DATA_FEED = "data_feed"
    TERMINAL = "terminal"
    ANALYTICS = "analytics"
    INDEX_LICENSE = "index_license"
    CONNECTIVITY = "connectivity"
    OTHER = "other"

    CATEGORY_CHOICES = [
        (DATA_FEED, "Data feed"),
        (TERMINAL, "Terminal"),
        (ANALYTICS, "Analytics"),
        (INDEX_LICENSE, "Index license"),
        (CONNECTIVITY, "Connectivity"),
        (OTHER, "Other"),
    ]

    BILLING_MONTHLY = "monthly"
    BILLING_QUARTERLY = "quarterly"
    BILLING_YEARLY = "yearly"

    BILLING_FREQUENCY_CHOICES = [
        (BILLING_MONTHLY, "Monthly"),
        (BILLING_QUARTERLY, "Quarterly"),
        (BILLING_YEARLY, "Yearly"),
    ]

    vendor = models.ForeignKey(
        Vendor,
        on_delete=models.CASCADE,
        related_name="services",
    )
    name = models.CharField(max_length=255)

    # NEW: service soft-close flag (True = Active, False = Closed)
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Soft status flag. True = Active, False = Closed (hidden unless Show Closed is enabled).",
    )

    category = models.CharField(
        max_length=50,
        choices=CATEGORY_CHOICES,
        blank=True,
    )
    service_code = models.CharField(
        max_length=100,
        blank=True,
        help_text="Vendor SKU / product code, if available.",
    )
    default_currency = models.CharField(
        max_length=3,
        blank=True,
        help_text="ISO currency code, e.g. USD, EUR, GBP.",
    )
    default_billing_frequency = models.CharField(
        max_length=20,
        choices=BILLING_FREQUENCY_CHOICES,
        blank=True,
    )

    owner_display = models.CharField(
        max_length=255,
        blank=True,
        help_text="Business owner / accountable person for this service.",
    )
    list_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Indicative annual price or unit price for this service.",
    )
    allocation_split = models.CharField(
        max_length=255,
        blank=True,
        help_text="High-level split, e.g. 60% Trading / 40% Research.",
    )
    primary_contract = models.ForeignKey(
        "Contract",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="primary_services",
        help_text="Primary contract under which this service is provided.",
    )

    class Meta:
        ordering = ["vendor__name", "name"]
        unique_together = [("vendor", "name")]

        indexes = [
            models.Index(fields=["vendor", "is_active", "name"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.vendor.name} – {self.name}"


# ---------- PERMISSIONS / ASSIGNMENTS (NEW) ----------

class ServiceAssignment(models.Model):
    """
    Assign portal users to services (license/entitlement style).
    This is intentionally simple for UAT; later we can scope by Portal/Tenant.
    """
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="service_assignments",
    )
    service = models.ForeignKey(
        Service,
        on_delete=models.CASCADE,
        related_name="user_assignments",
    )
    assigned_at = models.DateTimeField(default=timezone.now, db_index=True)

    assigned_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="service_assignments_made",
        help_text="Actor who made the assignment (optional).",
    )

    class Meta:
        unique_together = [("user", "service")]
        indexes = [
            models.Index(fields=["service", "user"]),
            models.Index(fields=["user", "service"]),
            models.Index(fields=["assigned_at"]),
        ]
        ordering = ["-assigned_at", "-id"]

    def __str__(self) -> str:
        return f"{self.user} → {self.service}"


# ---------- PROVISIONING REQUEST (NEW) ----------

class ProvisioningRequest(models.Model):
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    requester = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="provisioning_requests",
    )
    service = models.ForeignKey(
        Service,
        on_delete=models.PROTECT,
        related_name="provisioning_requests",
    )

    reason = models.TextField(blank=True, default="")

    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    decided_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="provisioning_decisions",
    )
    decision_note = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            # Only 1 pending request per (requester, service)
            models.UniqueConstraint(
                fields=["requester", "service"],
                condition=Q(status="pending"),
                name="uniq_pending_provisioning_request_per_service",
            )
        ]

    def __str__(self) -> str:
        svc = getattr(self.service, "name", "Service")
        return f"{self.requester} → {svc} ({self.status})"

created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="provisioning_requests_created",
        help_text="Who submitted the request (could be manager acting on behalf).",
    )

# ---------- CONTRACT ----------

class Contract(models.Model):
    TYPE_MASTER = "master"
    TYPE_ORDER_FORM = "order_form"
    TYPE_AMENDMENT = "amendment"
    TYPE_OTHER = "other"

    CONTRACT_TYPE_CHOICES = [
        (TYPE_MASTER, "Master"),
        (TYPE_ORDER_FORM, "Order form"),
        (TYPE_AMENDMENT, "Amendment"),
        (TYPE_OTHER, "Other"),
    ]

    STATUS_ACTIVE = "active"
    STATUS_EXPIRED = "expired"
    STATUS_PENDING = "pending"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_EXPIRED, "Expired"),
        (STATUS_PENDING, "Pending"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    NOTICE_30 = 30
    NOTICE_60 = 60
    NOTICE_90 = 90
    NOTICE_120 = 120

    NOTICE_PERIOD_CHOICES = [
        (NOTICE_30, "30 days"),
        (NOTICE_60, "60 days"),
        (NOTICE_90, "90 days"),
        (NOTICE_120, "120 days"),
    ]

    vendor = models.ForeignKey(
        Vendor,
        on_delete=models.PROTECT,
        related_name="contracts",
    )
    contract_name = models.CharField(
        max_length=255,
        help_text="Contract name or internal reference.",
    )
    contract_id = models.CharField(
        max_length=100,
        blank=True,
        help_text="Vendor contract ID / number, if applicable.",
    )
    contract_type = models.CharField(
        max_length=50,
        choices=CONTRACT_TYPE_CHOICES,
        blank=True,
    )

    entity = models.CharField(
        max_length=255,
        blank=True,
        help_text="Legal entity / desk / cost centre.",
    )

    annual_value = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Total annual contract value in contract currency.",
    )
    currency = models.CharField(
        max_length=3,
        blank=True,
        help_text="Currency of the annual contract value, e.g. USD, EUR.",
    )

    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    renewal_date = models.DateField(null=True, blank=True)

    notice_period_days = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        choices=NOTICE_PERIOD_CHOICES,
        help_text="Notice period in days (e.g. 30/60/90/120). Used to calculate notice date.",
    )
    notice_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date by which notice must be given. If blank, it can be derived from end_date - notice_period_days.",
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_ACTIVE,
    )

    related_services = models.ManyToManyField(
        Service,
        blank=True,
        related_name="contracts",
    )

    owning_cost_center = models.ForeignKey(
        CostCenter,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contracts",
        help_text="Which cost center owns this contract overall.",
    )

    file = models.FileField(
        upload_to="contracts/",
        help_text="Signed contract document",
        blank=True,
        null=True,
    )

    notes = models.TextField(
        blank=True,
        help_text="Internal notes / scope / renewal terms.",
    )

    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_contracts",
    )

    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="contracts",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.contract_name

    def get_absolute_url(self) -> str:
        return reverse("portal:contract_detail", kwargs={"pk": self.pk})

    @property
    def effective_notice_date(self):
        if self.notice_date:
            return self.notice_date
        if self.end_date and self.notice_period_days:
            return self.end_date - timedelta(days=int(self.notice_period_days))
        return None


# ---------- INVOICE ----------

class Invoice(models.Model):
    vendor = models.ForeignKey(
        Vendor,
        on_delete=models.PROTECT,
        related_name="invoices",
    )
    contract = models.ForeignKey(
        Contract,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoices",
        help_text="If this invoice relates to a specific contract.",
    )

    invoice_number = models.CharField(max_length=100)
    invoice_date = models.DateField()

    currency = models.CharField(
        max_length=3,
        help_text="Invoice currency, e.g. USD, EUR.",
    )
    total_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        help_text="Total amount as received on the invoice.",
    )
    tax_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Tax / VAT amount (optional).",
    )

    period_start = models.DateField(
        null=True,
        blank=True,
        help_text="Start date of the billed period, if applicable.",
    )
    period_end = models.DateField(
        null=True,
        blank=True,
        help_text="End date of the billed period, if applicable.",
    )

    file = models.FileField(
        upload_to="invoices/",
        null=True,
        blank=True,
        help_text="Uploaded PDF of the invoice.",
    )

    notes = models.TextField(
        blank=True,
        help_text="Additional notes to Finance / GL / tax.",
    )

    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="invoices",
        help_text="Which portal user this invoice belongs to.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-invoice_date", "-id"]
        unique_together = [("vendor", "invoice_number")]

    def __str__(self) -> str:
        return f"{self.vendor.name} – {self.invoice_number}"

    def get_absolute_url(self) -> str:
        return reverse("portal:invoice_detail", kwargs={"pk": self.pk})

    @property
    def period_label(self) -> str:
        if self.period_start and self.period_end:
            return f"{self.period_start} → {self.period_end}"
        if self.period_start and not self.period_end:
            return f"From {self.period_start}"
        if self.period_end and not self.period_start:
            return f"Until {self.period_end}"
        return "—"

    @property
    def tax_label(self) -> str:
        return str(self.tax_amount) if self.tax_amount is not None else "—"


# ---------- INVOICE LINE ----------

class InvoiceLine(models.Model):
    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name="lines",
    )
    service = models.ForeignKey(
        Service,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoice_lines",
    )

    description = models.CharField(
        max_length=255,
        help_text="Description as it appears on the invoice.",
    )

    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=1,
    )
    unit_price = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="Price per unit in line currency.",
    )
    line_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        help_text="Total amount for this line.",
    )

    currency = models.CharField(
        max_length=3,
        blank=True,
        help_text="Line currency if different from invoice currency.",
    )

    cost_center = models.ForeignKey(
        CostCenter,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoice_lines",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="license_invoice_lines",
        help_text="End user for personal licenses, if applicable.",
    )

    class Meta:
        ordering = ["invoice_id", "id"]

    def __str__(self) -> str:
        return f"Line {self.id} – {self.description}"


# ---------- AUDIT EVENT ----------

class AuditEvent(models.Model):
    """
    Audit log model aligned with:
      - current views.py (_audit_log_event uses object_type/object_id + actor + actor_display + occurred_at + description)
      - current vendor_detail.html (optionally renders ev.action)
    """

    ACTION_CREATE = "create"
    ACTION_UPDATE = "update"
    ACTION_DELETE = "delete"

    ACTION_CHOICES = [
        (ACTION_CREATE, "Create"),
        (ACTION_UPDATE, "Update"),
        (ACTION_DELETE, "Delete"),
    ]

    object_type = models.CharField(max_length=50, db_index=True)     # e.g. "Vendor"
    object_id = models.PositiveIntegerField(db_index=True)          # pk of the object
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)

    action = models.CharField(
        max_length=20,
        choices=ACTION_CHOICES,
        null=True,
        blank=True,
        db_index=True,
        help_text="Optional structured action for UI filtering (create/update/delete).",
    )

    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    actor_display = models.CharField(
        max_length=255,
        blank=True,
        help_text="Snapshot of actor name/email at the time of change.",
    )

    description = models.TextField()

    class Meta:
        ordering = ["-occurred_at", "-id"]
        indexes = [
            models.Index(fields=["object_type", "object_id", "occurred_at"]),
            models.Index(fields=["object_type", "object_id"]),
            models.Index(fields=["occurred_at"]),
        ]

    def __str__(self) -> str:
        who = self.actor_display or (self.actor.username if self.actor else "system")
        return f"{self.object_type}#{self.object_id} · {self.occurred_at:%Y-%m-%d %H:%M} · {who}"
