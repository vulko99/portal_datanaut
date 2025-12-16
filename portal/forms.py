# portal/forms.py
from django import forms

from .models import Contract, Vendor


class ContractUploadForm(forms.ModelForm):
    # свободен текст за името на доставчика
    vendor_name = forms.CharField(
        max_length=255,
        required=True,
        label="Vendor",
        help_text="Vendor name as it appears on the contract.",
        widget=forms.TextInput(
            attrs={
                "class": "form-control form-control-sm bg-dark text-light border-secondary",
            }
        ),
    )

    class Meta:
        model = Contract
        fields = ["title", "start_date", "end_date", "annual_value", "file"]

        widgets = {
            "title": forms.TextInput(
                attrs={
                    "class": "form-control form-control-sm bg-dark text-light border-secondary",
                }
            ),
            "start_date": forms.DateInput(
                attrs={
                    "type": "date",
                    "class": "form-control form-control-sm bg-dark text-light border-secondary",
                }
            ),
            "end_date": forms.DateInput(
                attrs={
                    "type": "date",
                    "class": "form-control form-control-sm bg-dark text-light border-secondary",
                }
            ),
            "annual_value": forms.NumberInput(
                attrs={
                    "class": "form-control form-control-sm bg-dark text-light border-secondary",
                }
            ),
            "file": forms.ClearableFileInput(
                attrs={
                    "class": "form-control form-control-sm bg-dark text-light border-secondary",
                }
            ),
        }

    def save(self, owner=None, uploaded_by=None, commit=True):
        # Намираме или създаваме Vendor по име
        vendor_name = self.cleaned_data["vendor_name"].strip()
        vendor, _ = Vendor.objects.get_or_create(name=vendor_name)

        contract = super().save(commit=False)
        contract.vendor = vendor

        if owner is not None:
            contract.owner = owner
        if uploaded_by is not None:
            contract.uploaded_by = uploaded_by

        if commit:
            contract.save()

        return contract
