"""Worker de polling : ``python manage.py mail_sync``.

À planifier toutes les 5 à 15 minutes (Render Cron Job, cron système...).
La fréquence propre à chaque société (15/30/60 min) est respectée par
``claim_for_sync`` : un cron plus fréquent ne force rien.

Exemples :
    python manage.py mail_sync
    python manage.py mail_sync --societe 123456789
    python manage.py mail_sync --force
"""

import uuid

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from mailsync.models import MailboxConfig
from mailsync.services import claim_for_sync, is_due, sync_mailbox


class Command(BaseCommand):
    help = (
        "Interroge les boîtes e-mail connectées et crée les brouillons de "
        "factures fournisseurs (anti-doublon par message_id)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--societe",
            help="Filtrer sur l'UUID d'une société ou son SIREN (9 chiffres).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Ignorer la fréquence configurée et synchroniser tout de suite.",
        )

    def handle(self, *args, **options):
        configs = MailboxConfig.objects.select_related("company").filter(
            is_active=True
        )
        identifiant = (options.get("societe") or "").strip()
        if identifiant:
            if identifiant.isdigit() and len(identifiant) == 9:
                configs = configs.filter(company__siren=identifiant)
            else:
                try:
                    company_id = uuid.UUID(identifiant)
                except ValueError as exc:
                    raise CommandError(
                        "--societe attend un UUID ou un SIREN à 9 chiffres."
                    ) from exc
                configs = configs.filter(company_id=company_id)

        force = options["force"]
        executed = 0
        for config in configs:
            if not force and not is_due(config):
                continue
            if not claim_for_sync(config, force=force):
                # Un autre cron a réservé la société entre-temps.
                continue
            result = sync_mailbox(config)
            executed += 1
            line = f"[{config.company.denomination}] {result.summary()}"
            if result.detail:
                line += f" — {result.detail}"
            if result.errors and not result.imported:
                self.stderr.write(line)
            else:
                self.stdout.write(line)

        if not executed:
            stamped = timezone.localtime().strftime("%H:%M")
            self.stdout.write(f"[{stamped}] Aucune boîte e-mail due.")
