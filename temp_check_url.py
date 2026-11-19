import os
import sys

os.chdir(".")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ["DJANGO_DEBUG"] = "1"
sys.path.insert(0, ".")

import django

django.setup()

from django.urls import resolve, reverse

url = reverse("invoice_verify_root", args=["11111111-1111-1111-1111-111111111111"])
print("reverse courte:", url)
res = resolve(url)
print("resolve view:", res.func.__name__)
res2 = resolve(url.replace("/v/", "/factures/v/"))
print("resolve longue interne:", res2.func.__name__)
