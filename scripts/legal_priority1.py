# Priorite 1 juridique : nuancer la conformite, corriger mentions legales,
# hebergement, voix bientot, page d'aide. Remplacements comptes et verifies.

def apply(path: str, pairs: list[tuple[str, str]]) -> None:
    text = open(path, encoding="utf-8", errors="replace").read()
    for old, new in pairs:
        if old in text:
            text = text.replace(old, new)
            print("OK   ", os.path.basename(path), "←", old[:52])
        else:
            print("SKIP ", os.path.basename(path), "←", old[:52], "(abs)")
    open(path, "w", encoding="utf-8").write(text)


import os

# 1. Vitrine claire + sombre : nuancer la conformite + hebergement
apply(
    os.path.join("config", "templates", "landing.html"),
    [
        (
            "Conforme facturation électronique 2026",
            "Plateforme agréée : connexion en cours",
        ),
        (
            "Factures conformes 2026",
            "Factures structurées, à la norme",
        ),
        (
            "Prêt pour la facturation électronique.",
            "Connexion à une plateforme agréée en cours.",
        ),
        (
            "Hébergement en France, cloisonnement strict par activité, aucune revente.",
            "Données hébergées en UE, cloisonnement strict par activité, aucune revente "
            "— diffusion du site par Vercel.",
        ),
    ],
)

apply(
    os.path.join("config", "templates", "dark", "landing.html"),
    [
        (
            "Factures conformes 2026",
            "Factures structurées, à la norme",
        ),
        (
            "Mentions, numérotation, TVA ou franchise. Prêt pour 2026.",
            "Mentions, numérotation, TVA ou franchise. Plateforme agréée : en cours.",
        ),
        (
            "Numérotation séquentielle sans trou, mentions obligatoires, TVA ou franchise en base. Prêt pour la facturation électronique.",
            "Numérotation séquentielle sans trou, mentions obrigatoires, TVA ou franchise en base "
            "— connexion plateforme agréée en cours.",
        ),
        (
            "Hébergement en France, chaque société est cloisonnée, aucune revente.",
            "Données hébergées en UE, chaque société est cloisonnée, aucune revente "
            "— diffusion du site par Vercel.",
        ),
    ],
)

# 2. Pieds de page : hebergement veritiable
apply(
    os.path.join("config", "templates", "base_public.html"),
    [
        (
            'aria-label="Hébergé en France"',
            'aria-label="Données en UE, diffusion Vercel"',
        ),
        (
            "Hébergé en France · RGPD · Données cloisonnées",
            "Données en UE · Diffusion Vercel · RGPD · Données cloisonnées",
        ),
    ],
)

apply(
    os.path.join("config", "templates", "dark", "base_public.html"),
    [
        (
            "Hébergé en France · RGPD · Données cloisonnées",
            "Données en UE · Diffusion Vercel · RGPD · Données cloisonnées",
        ),
    ],
)

# 3. Mentions legales / CGVU : numero de TVA + hebergeur Vercel
n_tva = "FR17100408517"
n_correct = "FR32951386127"
for relative in (
    os.path.join("config", "templates", "companies", "legal_notice.html"),
    os.path.join("config", "templates", "companies", "privacy_policy.html"),
    os.path.join("config", "templates", "companies", "terms_of_sale.html"),
    os.path.join("config", "templates", "companies", "terms_of_use.html"),
):
    text = open(relative, encoding="utf-8", errors="replace").read()
    count = text.count(n_tva)
    if count:
        text = text.replace(n_tva, n_correct)
        open(relative, "w", encoding="utf-8").write(text)
    print(count, "x TVA corrigée dans", os.path.basename(relative))

apply(
    os.path.join("config", "templates", "companies", "legal_notice.html"),
    [
        (
            'href="https://cloud.google.com" target="_blank" rel="noopener">https://cl',
            'href="https://vercel.com" target="_blank" rel="noopener">https://vercel.com',
        ),
        (
            "Les données de la plateforme sont hébergées dans l'Union européenne\n"
            "  (région europe-west1, Belgique).",
            "Le site est diffusé par Vercel Inc. (États-Unis). Les données sont "
            "hébergées dans l'Union européenne (Google Cloud, région europe-west1, Belgique).",
        ),
    ],
)

# 4. Page d'aide : texte reel a la place du placeholder
apply(
    os.path.join("config", "templates", "companies", "help.html"),
    [
        (
            "Contactez le support via l'adresse indiquée dans vos mentions légales,",
            "Support : <b>admin@roadrunner-solutions.fr</b> — réponse sous 24 à 48 h ouvrées. "
            "Urgences comptables : écrivez depuis l'email du compte.",
        ),
        (
            "[À compléter par le propriétaire de la société : horaires, téléphone, procédure d'escalade]",
            "Permanences : lundi au vendredi, 9 h – 18 h. Escalade : une réponse détaillée "
            "sous 3 jours ouvrés, un responsable du support vous rappelle ensuite.",
        ),
    ],
)

# 5. Voix Aminia : bientot disponible (catalogue + prix publics + blurbs)
apply(
    os.path.join("billing", "catalog.py"),
    [
        ("\"Tout le cockpit : voix Aminia, tickets de caisse, tous les modèles et sociétés illimités\"",
         "\"Tout le cockpit : voix Aminia (bientôt), tickets de caisse, tous les modèles et sociétés illimités\""),
        ('"Voix Aminia",\n            "Chat Aminia sans plafond"',
         '"Voix Aminia (bientôt disponible)",\n            "Chat Aminia sans plafond"'),
    ],
)

apply(
    os.path.join("billing", "public_pricing.py"),
    [("lines.append(\"Voix Aminia\")", "lines.append(\"Voix Aminia (bientôt disponible)\")")],
)

apply(
    os.path.join("core", "public_theme.py"),
    [(
        "Tout le cockpit, sans plafond. Voix Aminia, tickets, autant de sociétés que vous ouvrez.",
        "Tout le cockpit, sans plafond. Assistante Aminia, tickets, autant de sociétés que vous ouvrez.",
    )],
)
