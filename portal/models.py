# portal/models.py
from datetime import timedelta

from django.db import models
from django.contrib.auth import get_user_model
from django.urls import reverse

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

    # свободни полета за репортинг / сегментиране
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


# ---------- USER PROFILE (за бъдещия license request портал) ----------

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


# ---------- SERVICE (какво продава vendor-ът) ----------

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

    # допълнителни полета за портала
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

    def __str__(self) -> str:
        return f"{self.vendor.name} – {self.name}"


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
    # старото "title" – запазваме го като contract_name
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

    # Total annual contract value
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

    # --- NEW: Notice / Termination controls ---
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

    # Relationship към services – позволява split по услуги
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

    # Оригиналният качен файл (PDF/DOCX)
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

    # Кой клиент/потребител „вижда“ този контракт в портала
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
        """
        Returns:
          - notice_date if set (manual override)
          - else end_date - notice_period_days if possible
          - else None
        """
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

    # За multi-tenant портал – кой клиент да я вижда
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
        """
        Render a human-friendly billed period label for templates.
        Does not affect schema.
        """
        if self.period_start and self.period_end:
            return f"{self.period_start} → {self.period_end}"
        if self.period_start and not self.period_end:
            return f"From {self.period_start}"
        if self.period_end and not self.period_start:
            return f"Until {self.period_end}"
        return "—"

    @property
    def tax_label(self) -> str:
        """
        Render a human-friendly tax label for templates.
        Does not affect schema.
        """
        return str(self.tax_amount) if self.tax_amount is not None else "—"


# ---------- INVOICE LINE (където правим split към cost centers / users) ----------

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
