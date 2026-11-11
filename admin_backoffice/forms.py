from django import forms
from .models import SiteConfiguration
from companies.models import Company
from billing.models import Plan, Subscription
from accounts.models import User

class SiteConfigurationForm(forms.ModelForm):
    class Meta:
        model = SiteConfiguration
        fields = '__all__'
        widgets = {
            'smtp_password': forms.PasswordInput(attrs={'class': 'form-control'}),
            'stripe_secret_key': forms.PasswordInput(attrs={'class': 'form-control'}),
            'llm_api_key': forms.PasswordInput(attrs={'class': 'form-control'}),
            'insee_api_key': forms.PasswordInput(attrs={'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if not isinstance(field.widget, forms.PasswordInput):
                field.widget.attrs.update({'class': 'form-control'})

class CompanyAdminForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = ['denomination', 'invoice_theme']
        widgets = {
            'denomination': forms.TextInput(attrs={'class': 'form-control'}),
            'invoice_theme': forms.Select(attrs={'class': 'form-control'}),
        }

class PlanAdminForm(forms.ModelForm):
    class Meta:
        model = Plan
        fields = ['name', 'price_eur']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'price_eur': forms.NumberInput(attrs={'class': 'form-control'}),
        }

class SubscriptionAdminForm(forms.ModelForm):
    class Meta:
        model = Subscription
        fields = ['user', 'plan', 'status', 'current_period_end']
        widgets = {
            'user': forms.Select(attrs={'class': 'form-control'}),
            'plan': forms.Select(attrs={'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'current_period_end': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }

class UserAdminForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['email', 'is_staff', 'is_superuser']
        widgets = {
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'is_staff': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_superuser': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
