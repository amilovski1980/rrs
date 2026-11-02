from decimal import Decimal

from django import forms
from django.forms import (
    inlineformset_factory,
    BaseInlineFormSet,
    ModelChoiceField,
)

from .models import ChartAccount, EntryLine, Journal, JournalEntry

class LineForm(forms.ModelForm):
    class Meta:
        model = EntryLine
        fields = ("account", "debit", "credit")


class BalancingFormSet(BaseInlineFormSet):
    """Formset d'écriture : reject si debit != credit."""

    def add_fields(self, form, index):
        super().add_fields(form, index)
        form.fields["debit"].required = False
        form.fields["credit"].required = False

    def clean(self):
        super().clean()
        total_d = Decimal("0.00")
        total_c = Decimal("0.00")
        used = False
        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get("DELETE"):
                continue
            account = form.cleaned_data.get("account")
            if account is None:
                continue
            d = form.cleaned_data.get("debit") or Decimal("0.00")
            c = form.cleaned_data.get("credit") or Decimal("0.00")
            if d > 0 and c > 0:
                raise forms.ValidationError(
                    "Une ligne ne peut pas être à la fois débit et crédit."
                )
            total_d += d
            total_c += c
            used = True
        if not used:
            raise forms.ValidationError("Au moins une ligne est requise.")
        if total_d != total_c:
            raise forms.ValidationError(
                f"Écriture non équilibrée : débit {total_d} € ≠ crédit {total_c} €."
            )


EntryLineFormSet = inlineformset_factory(
    JournalEntry,
    EntryLine,
    form=LineForm,
    formset=BalancingFormSet,
    fields=("account", "debit", "credit"),
    extra=4,
    max_num=10,
)


class EntryForm(forms.ModelForm):
    class Meta:
        model = JournalEntry
        fields = ("journal", "date", "label", "reference")

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if company:
            self.fields["journal"].queryset = Journal.objects.filter(company=company)


def set_line_choices(formset, company):
    accounts = ChartAccount.objects.filter(company=company)
    for f in formset.forms:
        f.fields["account"].queryset = accounts
