from django.core.management.base import BaseCommand

from core.demo import purge_demo_sandboxes, purge_extra_demo_companies


class Command(BaseCommand):
    help = (
        "Supprime les anciens comptes de démonstration jetables "
        "demo+...@demo.invalid et les sociétés parasites du compte démo fixe."
    )

    def handle(self, *args, **options):
        sandboxes = purge_demo_sandboxes()
        extras = purge_extra_demo_companies()
        self.stdout.write(
            self.style.SUCCESS(
                f"{sandboxes} ancien(s) compte(s) de démo et "
                f"{extras} société(s) parasite(s) supprimé(s)."
            )
        )
