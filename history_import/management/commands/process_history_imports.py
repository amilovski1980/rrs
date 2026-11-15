"""Worker d'analyse des imports historiques.

À planifier toutes les 1 à 5 minutes :
    python manage.py process_history_imports
Le module est aussi reprenable depuis l'écran du lot (analyse par lots de 3).
"""

from django.core.management.base import BaseCommand

from history_import.models import ImportBatch
from history_import.services import batch_stats, process_batch


class Command(BaseCommand):
    help = "Analyse les documents d'import d'historique encore en attente."

    def add_arguments(self, parser):
        parser.add_argument("--batch", help="UUID d'un lot précis.")
        parser.add_argument("--limit", type=int, default=20, help="Documents par lot.")

    def handle(self, *args, **options):
        batches = ImportBatch.objects.filter(
            documents__status__in=["queued", "processing"]
        ).distinct()
        if options.get("batch"):
            batches = batches.filter(pk=options["batch"])
        total = 0
        for batch in batches:
            before = batch.documents.filter(
                status__in=["queued", "processing"]
            ).count()
            stats = process_batch(
                batch, limit=max(options.get("limit", 20), 1)
            )
            total += max(before - stats["pending"], 0)
            self.stdout.write(
                f"[{batch.company.denomination}] {batch}: "
                f"{stats['pending']} en attente, {stats['ready']} prêts, "
                f"{stats['review']} à vérifier."
            )
        self.stdout.write(self.style.SUCCESS(f"{total} document(s) traité(s)."))
