# Test UI du lot : bouton IA + POST batch_agent avec provider hors service.
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.test import Client
from django.contrib import messages as dj_messages

from companies.models import Company
from django.contrib.auth import get_user_model
from history_import.models import ImportBatch

user = get_user_model().objects.filter(email="mobtest@demo.invalid").first()
company = Company.objects.filter(owner=user).first()
batch = ImportBatch.objects.filter(company=company, label__contains="TEST agent").first()
if not batch:
    print("aucun lot de test - relancez probe_agent_import")
    raise SystemExit

client = Client()
client.force_login(user)

page = client.get(
    f"/monhistorique/lots/{batch.pk}/?societe={company.pk}"
    if False
    else f"/migration/lots/{batch.pk}/?societe={company.pk}"
)
body = page.content.decode("utf-8", "replace")
print("page:", page.status_code, "| bouton Analyse IA:", "Analyse IA" in body,
      "| url agent:", "history_import" not in body and "/agent/" in body)

post = client.post(
    f"/migration/lots/{batch.pk}/agent/?societe={company.pk}", follow=True
)
msgs = [m.message for m in dj_messages.get_messages(post.wsgi_request)]
print("POST:", post.status_code, "| messages:", [str(m)[:120] for m in msgs])

document = batch.documents.first()
document.refresh_from_db()
print("doc final:", document.status, "| kind:", document.kind)
