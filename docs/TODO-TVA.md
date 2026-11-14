# TODO — Module TVA & déclarations

Statut : **non démarré**. Ce document fige le périmètre avant implémentation.

## Objectif

Produire les déclarations de TVA (CA3 mensuelle/trimestrielle, CA12 annuelle)
depuis les écritures validées, avec un contrôle des bases et un export
PDF/CSV. Aucune écriture de TVA ne doit être saisie deux fois.

## 1. Modèles

- [ ] `VatDeclaration` : société, type (`CA3`, `CA12`), période début/fin,
      statut (`draft`, `validated`, `filed`), montants calculés (JSON ou champs
      Decimal), date de dépôt, référence, pièce jointe.
- [ ] Contrainte d'unicité `(company, type, period_start, period_end)`.
- [ ] `VatRateSummary` éventuel (base HT, taux, TVA) si l'on veut figer le
      détail par taux dans la déclaration.

## 2. Calcul (`accounting/vat.py` ou app `taxes/`)

- [ ] `vat_summary(company, start, end)` à partir des comptes :
      - `44571` TVA collectée ;
      - `44566` TVA déductible sur biens et services ;
      - `4452` / `4457` pour l'autoliquidation et les régularisations ;
      - comptes de produits `7*` et de charges `6*` pour les bases HT.
- [ ] Ventilation par taux (20 %, 10 %, 5,5 %, 2,1 %, exonéré).
- [ ] Gestion de la franchise en base : aucune TVA, mention adaptée.
- [ ] Autoliquidation à l'achat : débit `44566` / crédit `4452`, avec contrôle
      que la TVA collectée et déductible se neutralisent.
- [ ] Crédit de TVA reporté et TVA nette due.
- [ ] Rapprochement avec les journaux VEN et ACH (contrôle de cohérence).

## 3. Écrans

- [ ] `/tva/` : tableau de bord des périodes, prochaine échéance, historique.
- [ ] Sélecteur de période (mois/trimestre/année) et génération d'un brouillon.
- [ ] Détail d'une déclaration : bases par taux, TVA collectée, déductible,
      nette, crédit, contrôle d'équilibre.
- [ ] Export PDF et CSV de la déclaration.
- [ ] Échéancier CA3/CA12 selon le régime et la date de clôture.
- [ ] Verrouillage : une période déclarée ne doit plus être modifiable sans
      contre-passation.

## 4. Intégrations

- [ ] Ajouter le flag de forfait `vat` dans `billing/catalog.py` et les paliers.
- [ ] Entrée de menu « TVA » et verrou de forfait.
- [ ] Alimenter la Trésorerie avec la TVA nette due (prochaine échéance).
- [ ] Mettre à jour les prompts de l'agent Aminia (CA3/CA12, échéancier).

## 5. Tests et critères d'acceptation

- [ ] Cas standard : ventes 20 %, achats 20 %, TVA nette = collectée − déductible.
- [ ] Plusieurs taux sur une même période.
- [ ] Franchise en base : aucune TVA calculée.
- [ ] Autoliquidation : TVA collectée et déductible neutralisées.
- [ ] Crédit de TVA reporté.
- [ ] Période sans mouvement : déclaration à zéro.
- [ ] Export PDF/CSV conforme aux totaux affichés.
- [ ] Isolation stricte par société et contrôle d'accès aux déclarations.

## 6. Prérequis déjà en place

- [x] Écritures de ventes (`documents.services.post_sale`) avec `44571`.
- [x] Registre achats (`purchases`) avec `44566` et validation humaine.
- [x] Rapprochement bancaire (`banking`) pour fiabiliser les encaissements.
- [x] Trésorerie (`treasury`) pour intégrer la TVA due au prévisionnel.

## Hors périmètre v1

- Déclaration automatique vers un portail fiscal (API DGFiP).
- TVA intracommunautaire avancée (OSS/IOSS).
- Multi-devises.
