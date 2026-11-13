from django import forms

from documents.models import Client

from .models import Contact


class ContactForm(forms.ModelForm):
    class Meta:
        model = Contact
        fields = (
            "first_name",
            "last_name",
            "organization",
            "client",
            "department",
            "job_title",
            "email",
            "phone",
            "is_primary",
            "notes",
        )
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company
        self.fields["first_name"].label = "Prénom"
        self.fields["last_name"].label = "Nom"
        self.fields["organization"].label = "Société / organisation"
        self.fields["organization"].required = False
        self.fields["client"].label = "Fiche client (optionnel)"
        self.fields["client"].required = False
        self.fields["department"].label = "Département"
        self.fields["job_title"].label = "Fonction"
        self.fields["job_title"].required = False
        self.fields["email"].label = "E-mail"
        self.fields["email"].widget.input_type = "email"
        self.fields["email"].widget.attrs.update(
            {"autocomplete": "email", "inputmode": "email"}
        )
        self.fields["phone"].label = "Téléphone"
        self.fields["phone"].widget.input_type = "tel"
        self.fields["phone"].widget.attrs.update(
            {"autocomplete": "tel", "inputmode": "tel"}
        )
        self.fields["is_primary"].label = "Contact principal"
        self.fields["notes"].label = "Notes"
        self.fields["notes"].required = False
        if company is not None:
            self.fields["client"].queryset = Client.objects.filter(company=company)
        else:
            self.fields["client"].queryset = Client.objects.none()

    def clean(self):
        cleaned = super().clean()
        client = cleaned.get("client")
        organization = (cleaned.get("organization") or "").strip()
        if client is not None and not organization:
            cleaned["organization"] = client.name
        return cleaned
