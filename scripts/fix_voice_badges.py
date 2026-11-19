# La voix Aminia est livree : retirer les derniers badges "Bientot" de la
# vitrine et de la documentation statique.
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def patch(relative, pairs):
    path = os.path.join(ROOT, relative)
    with io.open(path, encoding="utf-8") as handle:
        text = handle.read()
    for old, new in pairs:
        if old not in text:
            raise SystemExit("ANCRE ABSENTE dans %s : %s" % (relative, old[:60]))
        text = text.replace(old, new)
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    print("OK", relative)


patch(
    "config/templates/landing.html",
    [
        (
            '<h3>Agent vocal Aminia <span class="badge badge-blue">Bientôt</span></h3>',
            '<h3>Agent vocal Aminia <span class="badge badge-blue">Disponible</span></h3>',
        ),
        (
            "Aperçu : Aminia propose le bon compte et prépare l'écriture. Vous validez, elle ne décide jamais seule.",
            "Aminia vous écoute, propose le bon compte et prépare l'écriture. Vous validez, elle ne décide jamais seule.",
        ),
    ],
)

patch(
    "docs/index.html",
    [
        (
            "L'agent vocal en aperçu : l'intégration arrive prochainement.",
            "L'agent vocal est disponible : vous parlez, Aminia prépare, vous validez.",
        ),
        (
            "Démo publicitaire — l'agent vocal sera intégré prochainement.",
            "Démo animée — dans l'application, Aminia vous écoute et répond à la voix.",
        ),
        (
            '<h3>Agent vocal Aminia <span class="badge badge-blue">Bientôt</span></h3>',
            '<h3>Agent vocal Aminia <span class="badge badge-blue">Disponible</span></h3>',
        ),
        (
            "Aperçu : Aminia propose le bon compte et prépare l'écriture. Vous validez, elle ne décide jamais seule.",
            "Aminia vous écoute, propose le bon compte et prépare l'écriture. Vous validez, elle ne décide jamais seule.",
        ),
    ],
)

print("TERMINE")
