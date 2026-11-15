import os
import django

# Ensure testserver is allowed for the test client
os.environ.setdefault('ALLOWED_HOSTS', 'localhost,127.0.0.1,testserver')

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.conf import settings
settings.ALLOWED_HOSTS.append('testserver')

from django.test import Client
client = Client()
response = client.get('/agent-config')
print('Status:', response.status_code)
print('Content:', response.content.decode())
