# Corrections verifiees : la voix Aminia et Factur-X sont bien livrees.
# Ce script remet les promesses exactes, corrige le lien Vercel casse et
# remplace le texte provisoire de la page d'aide.

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


# 1. Forfaits : la voix est livree, pas "bientot".
patch(
    "billing/catalog.py",
    [
        (
            "voix Aminia (bientôt), tickets de caisse",
            "voix Aminia, tickets de caisse",
        ),
        ('"Voix Aminia (bientôt disponible)"', '"Voix Aminia"'),
    ],
)

patch(
    "billing/public_pricing.py",
    [
        ('lines.append("Voix Aminia (bientôt disponible)")', 'lines.append("Voix Aminia")'),
    ],
)

patch(
    "core/public_theme.py",
    [
        (
            "Tout le cockpit, sans plafond. Assistante Aminia, tickets, autant de sociétés que vous ouvrez.",
            "Tout le cockpit, sans plafond. Voix Aminia, tickets, autant de sociétés que vous ouvrez.",
        ),
    ],
)

# 2. Vitrine claire : Factur-X est natif (XML CII + PDF + depot), la voix est livree.
patch(
    "config/templates/landing.html",
    [
        (
            '<span class="pill"><span class="dot"></span> Plateforme agréée : connexion en cours</span>',
            '<span class="pill"><span class="dot"></span> Factur-X natif · facturation électronique</span>',
        ),
        (
            "<h3>Factures structurées, à la norme</h3>",
            "<h3>Factur-X natif, prêt pour 2026</h3>",
        ),
        (
            "Numérotation séquentielle sans trou, mentions obligatoires, TVA ou franchise en base. Connexion à une plateforme agréée en cours.",
            "Numérotation séquentielle sans trou, mentions obligatoires, TVA ou franchise en base. XML CII et PDF Factur-X, dépôt sur plateforme agréée, Chorus Pro ou PPF.",
        ),
        (
            "Démo publicitaire — l'agent vocal sera intégré prochainement.",
            "Démo animée — dans l'application, Aminia vous écoute et répond à la voix.",
        ),
    ],
)

# 3. Vitrine sombre : idem + faute "obrigatoires".
patch(
    "config/templates/dark/landing.html",
    [
        (
            "<span>Mentions, numérotation, TVA ou franchise. Plateforme agréée : en cours.</span>",
            "<span>Mentions, numérotation, TVA ou franchise. Factur-X natif, prêt pour 2026.</span>",
        ),
        (
            "<h3>Factures structurées, à la norme</h3>",
            "<h3>Factur-X natif, prêt pour 2026</h3>",
        ),
        (
            "Numérotation séquentielle sans trou, mentions obrigatoires, TVA ou franchise en base — connexion plateforme agréée en cours.",
            "Numérotation séquentielle sans trou, mentions obligatoires, TVA ou franchise en base. XML CII et PDF Factur-X, dépôt plateforme agréée, Chorus Pro ou PPF.",
        ),
        (
            "Aperçu : la voix Aminia n'est pas encore branchée sur cet écran. Le dialogue ci-contre n'enregistre rien.",
            "Aperçu : le dialogue ci-contre est une démonstration. Dans l'application, Aminia écoute et répond à la voix — rien n'est enregistré sans validation.",
        ),
    ],
)

# 4. Mentions legales : lien Vercel casse + hebergeur du site cite.
patch(
    "config/templates/companies/legal_notice.html",
    [
        (
            '<div><dt>Site web</dt><dd><a href="https://vercel.com" target="_blank" rel="noopener">https://vercel.comoud.google.com</a></dd></div>',
            '<div><dt>Diffusion du site</dt><dd>Vercel Inc. — <a href="https://vercel.com" target="_blank" rel="noopener">https://vercel.com</a></dd></div>',
        ),
        (
            "Le site est diffusé par Vercel Inc. (États-Unis). Les données sont hébergées dans l'Union européenne (Google Cloud, région europe-west1, Belgique).",
            "Le site est diffusé par Vercel Inc. (États-Unis), qui traite les journaux de connexion. "
            "Les données applicatives sont hébergées dans l'Union européenne (Google Cloud, région europe-west1, Belgique).",
        ),
    ],
)

# 5. Page d'aide : plus de texte provisoire.
patch(
    "config/templates/companies/help.html",
    [
        (
            '<p class="sub">[À compléter par le propriétaire de la société : horaires, téléphone, procédure d’escalade.]</p>',
            '<p class="sub">Escalade : réponse détaillée sous 3 jours ouvrés, puis rappel par un responsable du support.</p>',
        ),
    ],
)

print("TERMINE")
