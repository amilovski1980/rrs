"""Suggestions de libellés de produits/services selon le métier de la société."""
from __future__ import annotations

GENERIC = [
    {"label": "Main d'œuvre", "description": "Main d'œuvre facturée au temps passé."},
    {"label": "Prestation de service", "description": "Prestation réalisée pour le client."},
    {"label": "Fourniture", "description": "Fourniture de matériaux ou de matériel."},
    {"label": "Déplacement", "description": "Déplacement et préparation du chantier."},
    {"label": "Forfait", "description": "Prestation facturée au forfait."},
    {"label": "Conseil", "description": "Accompagnement et conseil."},
    {"label": "Installation", "description": "Installation et mise en service."},
    {"label": "Entretien", "description": "Entretien et vérification."},
    {"label": "Réparation", "description": "Réparation et remise en état."},
    {"label": "Location de matériel", "description": "Location de matériel pour le chantier."},
]

BY_TRADE = {
    "transport": [
        {"label": "Transport de marchandises", "description": "Transport de marchandises."},
        {"label": "Transport de matériel", "description": "Transport de matériel et d'outillage."},
        {"label": "Livraison à domicile", "description": "Livraison chez le client."},
        {"label": "Livraison sur chantier", "description": "Livraison directe sur le chantier."},
        {"label": "Location de véhicule utilitaire", "description": "Location d'un véhicule utilitaire."},
        {"label": "Emballage et manutention", "description": "Emballage, chargement et déchargement."},
        {"label": "Logistique et stockage", "description": "Stockage et organisation logistique."},
        {"label": "Transport urgent", "description": "Transport prioritaire et livraison express."},
    ],
    "btp": [
        {"label": "Pose de fenêtre", "description": "Fourniture et pose de fenêtre."},
        {"label": "Fourniture et pose de fenêtre PVC", "description": "Fenêtre PVC double vitrage fournie et posée."},
        {"label": "Pose de porte", "description": "Fourniture et pose de porte."},
        {"label": "Fabrication sur mesure", "description": "Fabrication d'un ouvrage sur mesure."},
        {"label": "Travaux de rénovation", "description": "Travaux de rénovation intérieure."},
        {"label": "Isolation", "description": "Isolation thermique ou phonique."},
        {"label": "Terrassement", "description": "Terrassement et préparation du terrain."},
        {"label": "Petits travaux", "description": "Petits travaux d'aménagement et de finition."},
        {"label": "Déplacement chantier", "description": "Déplacement et préparation du chantier."},
    ],
    "plomberie": [
        {"label": "Dépannage plomberie", "description": "Intervention de dépannage plomberie."},
        {"label": "Installation sanitaire", "description": "Installation d'équipements sanitaires."},
        {"label": "Remplacement chauffe-eau", "description": "Dépose et remplacement du chauffe-eau."},
        {"label": "Débouchage canalisation", "description": "Débouchage de canalisation."},
        {"label": "Recherche de fuite", "description": "Recherche et réparation de fuite."},
        {"label": "Pose de robinetterie", "description": "Pose et remplacement de robinetterie."},
        {"label": "Main d'œuvre plomberie", "description": "Main d'œuvre plomberie."},
    ],
    "electricite": [
        {"label": "Installation électrique", "description": "Installation électrique complète."},
        {"label": "Mise aux normes électriques", "description": "Mise en conformité de l'installation."},
        {"label": "Dépannage électrique", "description": "Recherche de panne et dépannage."},
        {"label": "Pose de tableau électrique", "description": "Installation ou remplacement du tableau."},
        {"label": "Éclairage", "description": "Pose et remplacement de luminaires."},
        {"label": "Prise et interrupteur", "description": "Pose de prises et d'interrupteurs."},
        {"label": "Main d'œuvre électricité", "description": "Main d'œuvre électricité."},
    ],
    "coiffure": [
        {"label": "Coupe femme", "description": "Coupe et coiffage femme."},
        {"label": "Coupe homme", "description": "Coupe homme."},
        {"label": "Coupe enfant", "description": "Coupe enfant."},
        {"label": "Coloration", "description": "Coloration des cheveux."},
        {"label": "Balayage", "description": "Balayage et mèches."},
        {"label": "Shampooing", "description": "Shampooing et soin."},
        {"label": "Brushing", "description": "Brushing et mise en forme."},
        {"label": "Soin capillaire", "description": "Soin des cheveux et du cuir chevelu."},
        {"label": "Barbe", "description": "Taille de barbe."},
    ],
    "resto": [
        {"label": "Menu du jour", "description": "Menu complet du jour."},
        {"label": "Plat du jour", "description": "Plat préparé du jour."},
        {"label": "Entrée", "description": "Entrée du menu."},
        {"label": "Dessert", "description": "Dessert du menu."},
        {"label": "Boisson", "description": "Boisson servie au restaurant."},
        {"label": "Formule midi", "description": "Formule complète du midi."},
        {"label": "Repas à emporter", "description": "Repas préparé à emporter."},
        {"label": "Livraison repas", "description": "Livraison de repas."},
    ],
    "garage": [
        {"label": "Vidange", "description": "Vidange moteur et remplacement du filtre."},
        {"label": "Révision véhicule", "description": "Révision complète du véhicule."},
        {"label": "Remplacement plaquettes de frein", "description": "Remplacement des plaquettes de frein."},
        {"label": "Diagnostic électronique", "description": "Diagnostic électronique du véhicule."},
        {"label": "Montage pneus", "description": "Montage et équilibrage de pneus."},
        {"label": "Contrôle technique", "description": "Préparation au contrôle technique."},
        {"label": "Carrosserie", "description": "Réparation de carrosserie."},
        {"label": "Main d'œuvre atelier", "description": "Main d'œuvre atelier."},
    ],
}

TRADE_KEYWORDS = {
    "transport": ("transport", "logistique", "livraison", "déménagement", "demenagement"),
    "btp": ("btp", "menuiserie", "construction", "maçonnerie", "maconnerie", "charpente", "toiture"),
    "plomberie": ("plomberie", "plombier", "sanitaire", "chauffage"),
    "electricite": ("electricite", "électricité", "electricien", "électricien"),
    "coiffure": ("coiffure", "coiffeur", "barbier"),
    "resto": ("resto", "restauration", "restaurant", "traiteur", "café", "cafe"),
    "garage": ("garage", "automobile", "mécanicien", "mecanicien", "carrosserie"),
}

NAF_TRADE = {
    "43": "btp",
    "49": "transport",
    "45": "garage",
    "56": "resto",
}


def _trades_for(company) -> list[str]:
    values = [str(value or "").lower() for value in (company.activites or [])]
    text = " ".join(values + [company.denomination or "", company.code_naf or ""]).lower()
    trades = []
    for trade, keywords in TRADE_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            trades.append(trade)
    naf = "".join(char for char in (company.code_naf or "") if char.isdigit())
    if len(naf) >= 2:
        trade = NAF_TRADE.get(naf[:2])
        if trade and trade not in trades:
            trades.append(trade)
    return trades


def product_suggestions(company) -> list[dict]:
    """Liste dédupliquée de suggestions adaptées au métier de la société."""
    items = []
    seen = set()

    def add(item):
        label = (item.get("label") or "").strip()
        key = label.casefold()
        if not label or key in seen:
            return
        seen.add(key)
        items.append(
            {
                "label": label,
                "description": (item.get("description") or "")[:255],
            }
        )

    for trade in _trades_for(company):
        for item in BY_TRADE.get(trade, []):
            add(item)
    for product in company.products.filter(active=True).order_by("label")[:40]:
        add({"label": product.label, "description": product.description})
    for item in GENERIC:
        add(item)
    return items
