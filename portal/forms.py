# portal/forms.py
from django import forms

from .models import Contract, Invoice, Vendor


class DateInput(forms.DateInput):
    input_type = "date"


def _bootstrapize_fields(form: forms.Form) -> None:
    """
    Apply consistent Bootstrap classes to all fields in a form,
    without changing templates/design structure.
    """
    for name, field in form.fields.items():
        w = field.widget

        existing = w.attrs.get("class", "").strip()

        if isinstance(w, (forms.Select, forms.SelectMultiple)):
            base = "form-select form-select-sm"
        else:
            base = "form-control form-control-sm"

        w.attrs["class"] = (existing + " " + base).strip()

        if isinstance(w, forms.TextInput) and not w.attrs.get("placeholder"):
            w.attrs["placeholder"] = ""
        if isinstance(w, forms.NumberInput) and not w.attrs.get("placeholder"):
            w.attrs["placeholder"] = ""


# ---------- CONTRACT UPLOAD ----------

class ContractUploadForm(forms.ModelForm):
    class Meta:
        model = Contract
        fields = [
            "vendor",
            "contract_name",
            "contract_id",
            "contract_type",
            "entity",
            "annual_value",
            "currency",
            "start_date",
            "end_date",
            "renewal_date",
            # NEW:
            "notice_period_days",
            "notice_date",
            "file",
        ]
        widgets = {
            "start_date": DateInput(),
            "end_date": DateInput(),
            "renewal_date": DateInput(),
            # NEW:
            "notice_date": DateInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrapize_fields(self)

        # Optional UX: keep empty option for notice_period_days (since field is nullable)
        if "notice_period_days" in self.fields:
            self.fields["notice_period_days"].required = False

        if "notice_date" in self.fields:
            self.fields["notice_date"].required = False

    def clean(self):
        cleaned = super().clean()

        end_date = cleaned.get("end_date")
        notice_period_days = cleaned.get("notice_period_days")
        notice_date = cleaned.get("notice_date")

        # Rule: if notice_date is set, must have end_date
        if notice_date and not end_date:
            self.add_error("notice_date", "Notice date requires End date to be set.")

        # Rule: notice_date must be <= end_date
        if notice_date and end_date and notice_date > end_date:
            self.add_error("notice_date", "Notice date must be on or before End date.")

        # Optional: if both are present, allow manual override (no error)
        # Optional: if notice_period_days set but end_date missing -> no hard error (user may fill later)
        # If you want to enforce end_date when notice_period_days is selected, uncomment:
        # if notice_period_days and not end_date:
        #     self.add_error("end_date", "End date is required when Notice period is set.")

        return cleaned

    def save(self, owner, uploaded_by, commit=True):
        obj = super().save(commit=False)
        obj.owner = owner
        obj.uploaded_by = uploaded_by
        if commit:
            obj.save()
            self.save_m2m()
        return obj


# ---------- INVOICE UPLOAD ----------

class InvoiceUploadForm(forms.ModelForm):
    class Meta:
        model = Invoice
        fields = [
            "vendor",
            "contract",
            "invoice_number",
            "invoice_date",
            "currency",
            "total_amount",
            "tax_amount",
            "period_start",
            "period_end",
            "file",
        ]
        widgets = {
            "invoice_date": DateInput(),
            "period_start": DateInput(),
            "period_end": DateInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrapize_fields(self)

        # Helpful placeholders (keeps design; only UX)
        self.fields["invoice_number"].widget.attrs.setdefault("placeholder", "Invoice number…")
        self.fields["currency"].widget.attrs.setdefault("placeholder", "e.g. USD, EUR, GBP")
        self.fields["total_amount"].widget.attrs.setdefault("placeholder", "0.00")
        self.fields["tax_amount"].widget.attrs.setdefault("placeholder", "0.00")

    def save(self, owner, commit=True):
        obj = super().save(commit=False)
        obj.owner = owner
        if commit:
            obj.save()
            self.save_m2m()
        return obj


# ---------- VENDOR CREATE (PORTAL) ----------

class VendorCreateForm(forms.ModelForm):
    class Meta:
        model = Vendor
        fields = [
            "name",
            "vendor_type",
            "tags",
            "primary_contact_name",
            "primary_contact_email",
            "website",
            "notes",
        ]
        widgets = {
            "name": forms.TextInput(attrs={
                "class": "form-control form-control-sm",
                "placeholder": "e.g. Bloomberg, Refinitiv…",
            }),
            "vendor_type": forms.Select(attrs={
                "class": "form-select form-select-sm",
            }),
            "tags": forms.TextInput(attrs={
                "class": "form-control form-control-sm",
                "placeholder": "Comma-separated (e.g. Tier1, FX, EMEA)",
            }),
            "primary_contact_name": forms.TextInput(attrs={
                "class": "form-control form-control-sm",
                "placeholder": "Name…",
            }),
            "primary_contact_email": forms.EmailInput(attrs={
                "class": "form-control form-control-sm",
                "placeholder": "email@company.com",
            }),
            "website": forms.URLInput(attrs={
                "class": "form-control form-control-sm",
                "placeholder": "https://vendor.com",
            }),
            "notes": forms.Textarea(attrs={
                "class": "form-control form-control-sm",
                "placeholder": "Commercial focus, coverage, strategic notes…",
                "rows": 2,
            }),
        }