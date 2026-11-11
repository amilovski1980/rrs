from django import forms
from .models import SiteConfiguration
from companies.models import Company, CompanyProfile
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
        fields = ['name', 'invoice_theme']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'invoice_theme': forms.Select(attrs={'class': 'form-control'}),
        }

class PlanAdminForm(forms.ModelForm):
    class Meta:
        model = Plan
        fields = ['name', 'price_eur', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'price_eur': forms.NumberInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

class SubscriptionAdminForm(forms.ModelForm):
    class Meta:
        model = Subscription
        fields = ['company', 'plan', 'status', 'start_date', 'end_date']
        widgets = {
            'company': forms.Select(attrs={'class': 'form-control'}),
            'plan': forms.Select(attrs={'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'start_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'end_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }

class UserAdminForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['email', 'first_name', 'last_name', 'is_staff', 'is_superuser']
        widgets = {
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'is_staff': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_superuser': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
