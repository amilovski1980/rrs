"""Service : génération du "portail" d'une société selon son profil
(activités, régime, TVA). Idempotent : ne recrée pas si déjà généré."""

from accounting.models import ChartAccount, Journal

# Comptes de base du PCG, activés par profil.
BASE_ACCOUNTS = [
    ("101", "Capital"),
    ("106", "Report à nouveau"),
    ("110", "Compte de l'exploitant"),
    ("120", "Résultat de l'exercice"),
    ("164", "Emprunts"),
    ("213", "Matériel"),
    ("241", "Précompte immobilisé"),
    ("281", "Amortissements du matériel"),
    ("401", "Fournisseurs"),
    ("411", "Clients"),
    ("421", "Personnel - rémunérations dues"),
    ("431", "URSSAF"),
    ("445", "État - TVA"),
    ("464", "URSSAF - cotisations auto/micro social"),
    ("512", "Banque"),
    ("530", "Caisse"),
    ("611", "Sous-traitance"),
    ("613", "Locations"),
    ("616", "Assurances"),
    ("622", "Honoraires"),
    ("625", "Déplacements"),
    ("626", "Divers (petit outillage…)"),
    ("635", "Impôts"),
    ("641", "Salaires"),
    ("661", "Charges financières"),
    ("676", "Matériel hors VA (charges à dénouer)"),
    ("701", "Ventes de prestations"),
    ("706", "Prestations de services"),
    ("705", "Études et prestations"),
    ("713", "Stock de biens"),
    ("645", "Charges de formation pro / taxes formation"),
]
TVA_ACCOUNTS = [
    ("44566", "TVA déductible"),
    ("44571", "TVA collectée"),
]
SUBVENTION_ACCOUNTS = ["7161"]

# Journaux activés par régime
REEL_JOURNALS = [
    ("ACH", "Achats", "achats"),
    ("VEN", "Ventes", "ventes"),
    ("BQ", "Banque", "banque"),
    ("CA", "Caisse", "caisse"),
    ("OD", "Opérations diverses", "od"),
]
# Micro : saisie simplifiée (recettes/dépenses) — piggybacking banque+caisse.
MICRO_JOURNALES = [("BQ", "Banque", "banque"), ("VEN", "Ventes", "ventes")]


def generate_portal(company):
    """Active :
    - plan comptable complet si reel / simplifié si micro
    - journaux selon regime
    - ts par la suite : tva accounts si company.tva == reel
    """
    if company.journals.exists():
        return
    for code, name, jtype in (
        REEL_JOURNALS if company.regime == "reel_simple" else MICRO_JOURNALES
    ):
        Journal.objects.create(company=company, code=code, name=name, type=jtype)

    accounts = list(BASE_ACCOUNTS)
    if company.tva == "reel":
        accounts += TVA_ACCOUNTS
    for code, label in accounts:
        ChartAccount.objects.get_or_create(
            company=company, code=code, defaults={"label": label}
        )
