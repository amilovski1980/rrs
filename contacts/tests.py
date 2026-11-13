from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from companies.models import Company
from documents.models import Client

from .models import Contact


def _company(owner, siren, name):
    return Company.objects.create(
        owner=owner,
        siren=siren,
        denomination=name,
        forme="SARL",
        regime="reel_simple",
        tva="reel",
        exercice_debut=date(2026, 1, 1),
    )


class ContactModuleTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user("contacts@example.fr", password="password123")
        self.other = User.objects.create_user("other@example.fr", password="password123")
        self.company = _company(self.user, "812345679", "Atelier Contacts")
        self.other_company = _company(self.other, "912345679", "Autre Atelier")
        self.client_company = Client.objects.create(
            company=self.company, name="Cadres Industries", siren="552100554",
            email="client@example.fr",
        )
        Client.objects.create(
            company=self.other_company, name="Client privé", siren="552100555",
        )
        self.http = self.client
        self.http.force_login(self.user)

    def _create(self, first="Alice", last="Durand", **extra):
        data = {
            "first_name": first,
            "last_name": last,
            "organization": "",
            "client": self.client_company.id,
            "department": "service_client",
            "job_title": "Responsable achats",
            "email": "alice@example.fr",
            "phone": "01 23 45 67 89",
            "notes": "",
        }
        data.update(extra)
        return self.http.post(reverse("contact_create"), data, follow=True)

    def test_create_contact_from_client_fills_organization(self):
        response = self._create()
        self.assertEqual(response.status_code, 200)
        contact = Contact.objects.get(company=self.company, last_name="Durand")
        self.assertEqual(contact.first_name, "Alice")
        self.assertEqual(contact.organization, "Cadres Industries")
        self.assertEqual(contact.client, self.client_company)
        self.assertEqual(contact.department, "service_client")
        self.assertContains(response, "Alice Durand")
        self.assertContains(response, "Cadres Industries")

    def test_primary_contact_is_unique_per_client(self):
        first = Contact.objects.create(
            company=self.company,
            client=self.client_company,
            first_name="Premier",
            last_name="Contact",
            is_primary=True,
        )
        self._create(is_primary="on")
        first.refresh_from_db()
        self.assertFalse(first.is_primary)
        self.assertEqual(
            Contact.objects.filter(
                company=self.company, client=self.client_company, is_primary=True
            ).count(),
            1,
        )

    def test_list_search_department_and_dark_version(self):
        self._create()
        self._create(
            first="Paul", last="Fournisseur", department="fournisseur",
            email="paul@example.fr", client="",
        )
        filtered = self.http.get(
            reverse("contacts"), {"q": "Paul", "department": "fournisseur"}
        )
        self.assertEqual(filtered.status_code, 200)
        self.assertContains(filtered, "Paul Fournisseur")
        self.assertNotContains(filtered, "Alice Durand")

        dark = self.http.get("/dark/contacts/")
        self.assertEqual(dark.status_code, 200)
        self.assertContains(dark, "Contacts")
        self.assertContains(dark, "dark-app.css")
        self.assertContains(dark, 'data-theme="dark"')
        self.assertContains(dark, "Alice Durand")

    def test_other_tenant_contact_is_not_reachable(self):
        hidden = Contact.objects.create(
            company=self.other_company,
            first_name="Secret",
            last_name="Contact",
            department="direction",
        )
        self.assertEqual(self.http.get(reverse("contacts")).status_code, 200)
        self.assertEqual(
            self.http.get(reverse("contact_detail", args=[hidden.id])).status_code, 404
        )
        self.assertEqual(
            self.http.get(reverse("contact_edit", args=[hidden.id])).status_code, 404
        )
        self.assertEqual(
            self.http.post(reverse("contact_delete", args=[hidden.id])).status_code, 404
        )
        self.assertTrue(Contact.objects.filter(pk=hidden.pk).exists())

    def test_form_only_offers_clients_of_the_company(self):
        page = self.http.get(reverse("contact_create"))
        self.assertContains(page, "Cadres Industries")
        self.assertNotContains(page, "Client privé")
