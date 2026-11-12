# Road Runner Solutions

Cockpit comptable multi-activités pour bâtisseurs et dirigeants de TPE françaises.

Saisie par SIREN (API Sirene INSEE), fiche légale à valider, portail comptable généré
selon l'activité et le régime fiscal, écritures équilibrées, grand livre, balance et
échéancier TVA. Interface institutionnelle modernisée inspirée de santepubliquefrance.fr :
bleu profond, accent rose, typographie Roboto Condensed, micro-animations.

## Fonctionnalités

- Entrée : recherche par nom, SIREN ou SIRET (annuaire public
  recherche-entreprises.api.gouv.fr), confirmation de la fiche, email et téléphone,
  puis cockpit vide de cette société. La vérification email/SMS est une étape,
  contournée tant que `SIGNUP_VERIFICATION_ENABLED` n'est pas activé.
- Retour : `/compte/` pour un email déjà connu. Démo séparée : `/compte/demo/`.
- Ajout d'une autre société (compte déjà ouvert) : `/ajouter/`.
- Auth sans mot de passe (lien magique SHA-256, 30 min, usage unique) lorsque
  `SIGNUP_VERIFICATION_ENABLED=1`.
- Portail comptable par société : comptes PCG, journaux ACH / VEN / BQ / CA / OD.
- Écritures en `Decimal`, rejet si débit ≠ crédit ou ligne débit + crédit.
- Grand livre et balance consolidés, isolation stricte par société.
- Factures : numérotation séquentielle sans trou (verrou transactionnel).
- Agent vocal **Aminia** et assistant IA auto-hébergé : brouillons soumis à validation humaine.
- Abonnements Stripe (Micro 29 €, Réel 49 €, Pro 79 €), essai 14 jours.

## Stack

- Python 3.11 / Django 5.2, templates serveur (aucun build front).
- PostgreSQL en production, SQLite en développement.
- WhiteNoise + Gunicorn, déploiement Render (`render.yaml`).
- API Sirene INSEE 3.11 (`X-INSEE-Api-Key-Integration`).
- Aminia via Qwen auto-hébergé avec vLLM (API OpenAI-compatible).

## Démarrage

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env          # puis renseigner les clés
python manage.py migrate
python manage.py runserver
```

En développement, avec `SIGNUP_VERIFICATION_ENABLED=1`, l'email part dans
`email_outbox/` (si `DJANGO_DEBUG=1`) et le lien s'affiche sur la page de
vérification. Avec la valeur par défaut `0`, aucun email n'est envoyé : le
cockpit s'ouvre tout de suite.

```bash
# .env — laisser à 0 pour le parcours direct, passer à 1 pour exiger le lien email
SIGNUP_VERIFICATION_ENABLED=0
```

## API Sirene INSEE

1. Créer une application sur https://portail-api.insee.fr et souscrire à l'API Sirene.
2. Copier la clé d'API dans `.env` : `INSEE_API_KEY=...`.
3. `lookup_siren()` interroge le siège via `/siret`, avec repli sur `/siren`.
4. Sans clé, l'application reste utilisable en saisie manuelle.

## Tests

```bash
python -X utf8 tests_smoke_compta.py     # compta, équilibre, isolation tenant
python -X utf8 tests_insee_flow.py       # normalisation + parcours SIREN
```

## Présentation Aminia

`presentation-aminia.html` : deck de 12 slides sur l'agent vocal (constat, expérience,
architecture, personnalité, confiance, impact, feuille de route). Ouvrir dans un
navigateur, naviguer avec `←` / `→`, exporter en PDF avec `P` (paysage 1280×720).
Version prête à partager : `presentation-aminia.pdf` (12 pages, 1280×720).

## Déploiement

Render : créer un Blueprint depuis `render.yaml`, renseigner `INSEE_API_KEY`
(et les autres secrets) dans le dashboard. `build.sh` exécute installation,
`collectstatic` et `migrate`.

Vercel n'héberge pas Django : utiliser Render pour le backend.

## Site public gratuit (GitHub Pages / Vercel)

`docs/` contient une version statique de la page d'accueil (Aminia, logo, deck),
sans dépendance à Django, prête à publier gratuitement.

- **GitHub Pages** : publier le dépôt depuis VSCode, puis `Settings → Pages →
  Build and deployment → Source: GitHub Actions`. Le workflow
  `.github/workflows/pages.yml` déploie `docs/` à chaque push sur `main`.
  Variante sans Actions : `Source: Deploy from a branch` → `main` / `docs`.
- **Vercel** : `npx vercel login` puis `npx vercel docs --prod` (ou importer le
  dépôt et définir Root Directory = `docs`). `docs/vercel.json` active les URLs
  propres.

`docs/index.html` est un export de la landing Django ; `docs/presentation-aminia.html`
est le deck ; le logo est dans `docs/assets/logo.png`. Le backend Django reste sur
Render : GitHub Pages et Vercel ne servent que la page publique.

## Structure

- `accounts/` : utilisateur sans mot de passe, lien magique, crochet SMS.
- `companies/` : société, recherche annuaire, inscription, onboarding, cockpit.
- `accounting/` : plan comptable, journaux, écritures, grand livre, balance.
- `documents/` : factures et numérotation.
- `integrations/` : INSEE Sirene, INPI.
- `ai/` : client Qwen, brouillons d'écritures.
- `billing/` : plans, abonnements, webhooks Stripe.
- `core/` : isolation multi-tenant.
- `static/css/app.css` : design system inspiré de Santé publique France, modernisé.
- `docs/` : site public statique (landing Aminia, logo, deck) pour GitHub Pages / Vercel.

> Le dossier local et le package Django s'appellent encore `mamed` ; la marque
> produit est **Road Runner Solutions**.
