# portal/forms.py
from django import forms
from .models import Contract


class ContractUploadForm(forms.ModelForm):
    class Meta:
        model = Contract
        fields = [
            "vendor",
            "contract_name",
            "contract_id",
            "contract_type",
            "entity",
            "start_date",
            "end_date",
            "renewal_date",
            "annual_value",
            "currency",
            "status",
            "related_services",
            "owning_cost_center",
            "file",
        ]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "renewal_date": forms.DateInput(attrs={"type": "date"}),
        }
