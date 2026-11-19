# Verification rendu : badge d'urgence dans le selecteur (2 societes) + carte globale.
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from datetime import date

from companies.models import Company
from django.test import Client
from django.contrib.auth import get_user_model

user = get_user_model().objects.get(email="mobtest@demo.invalid")
company = Company.objects.filter(owner=user).first()
# une seconde societe du meme proprietaire, echeance urgente
other = Company.objects.filter(owner=user).count()
if other < 2:
    Company.objects.create(
        owner=user, siren="998877661", denomination="Deuxieme SARL",
        forme="SARL", regime="reel_simple", tva="reel",
        exercice_debut=date(2025, 11, 27),  # cloture le 27/11 -> 9 jours
    )

company.exercice_debut = date(2025, 11, 25)  # cloture le 25/11 -> 7 jours
company.save(update_fields=["exercice_debut"])

c = Client()
c.force_login(user)

page = c.get("/migration/lots/", follow=True) if False else c.get("/cockpit/global/", follow=True)
body = page.content.decode("utf-8", "replace")
print("cockpit global:", page.status_code, "| badge socie-urgent:", "socie-urgent" in body, "| dot:", "m-company-dot" in body)

page2 = c.get("/cockpit/", follow=True)
body2 = page2.content.decode("utf-8", "replace")
print("cockpit:", page2.status_code, "| menu dot:", "m-company-dot" in body2, "| strip:", "deadline-strip" in body2)
