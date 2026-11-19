from django import forms
from .models import Asset


class AssetForm(forms.ModelForm):
    class Meta:
        model = Asset
        fields = (
            "name",
            "description",
            "acquisition_date",
            "cost",
            "depreciation_rate",
            "useful_life_years",
        )
        widgets = {
            "acquisition_date": forms.DateInput(attrs={"type": "date"}),
        }
