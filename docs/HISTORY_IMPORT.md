# Import intelligent d'historique — RRS Sandy

## Périmètre V1

Module mobile-first `/migration/` permettant de déposer plusieurs photos, PDF,
XML ou une archive ZIP de factures historiques, de les analyser, de corriger les
exceptions et de les archiver dans les modules existants.

**Règle absolue : aucune écriture comptable n'est créée par ce module.**
Les factures historiques sont archivées (`status="archived"`,
`source="historical_import"`). Une reprise comptable reste un chantier distinct.

## Architecture

```
history_import/
├── models.py              # ImportBatch, ImportDocument, ImportAuditEvent
├── services.py            # upload, ZIP, extraction, classification, doublons, import
├── forms.py               # upload multiple + correction document
├── views.py / urls.py     # /migration/
├── management/commands/process_history_imports.py
├── templates/history_import/
│   ├── upload.html
│   ├── batch.html
│   └── document.html
└── tests.py
```

### Réutilisation

- `mailsync.parsers` : Factur-X, UBL, CII, PDF texte.
- `documents.receipt_ocr` : OCR des photos et PDF scannés.
- `documents.Invoice` / `documents.Client` : factures de vente et clients.
- `purchases.PurchaseInvoice` / `mailsync.Supplier` : factures fournisseurs.
- `billing.access.feature_on` : réservé au forfait ultime (`full`).
- `FileField` privé + vue de téléchargement contrôlée par société.

## Cycle de vie

1. **Upload** : un lot (`ImportBatch`) reçoit un ou plusieurs fichiers.
   Les ZIP sont extraits en mémoire, sans écriture disque arbitraire.
2. **File d'attente** : chaque document est `queued`. Le premier lot est traité
   en partie à l'upload, puis l'écran du lot reprend automatiquement par petits
   paquets (3 documents par requête) ; `process_history_imports` peut aussi être
   planifié en cron.
3. **Analyse** : extraction texte/XML/OCR, classification vente/achat/avoir/
   ticket/autre, détection des incohérences.
4. **Validation collective** : onglets Prêts / À vérifier / Doublons / Importés.
   Les documents prêts sont importés en lot ; les exceptions sont corrigées une
   par une.
5. **Import** : création d'une facture de vente ou d'achat archivée, ou simple
   archivage du document. Aucun `JournalEntry` n'est créé.

## Statuts

- `queued` : en attente d'analyse.
- `processing` : analyse en cours.
- `ready` : prêt à importer.
- `review` : anomalie à corriger.
- `duplicate` : doublon (fichier identique ou facture déjà présente).
- `imported` : archivé dans le module concerné.
- `error` : analyse impossible (OCR, fichier corrompu).
- `rejected` : exclu par l'utilisateur.

## Doublons

- Empreinte SHA-256 du fichier, par société.
- Même type + numéro + montant TTC dans le lot.
- Facture existante de la société avec le même numéro (vente ou achat).
- Jamais d'écrasement : un doublon reste consultable mais n'est pas importé.

## Sécurité

- Téléchargements contrôlés par `company` et par forfait.
- Extensions autorisées, taille max par fichier et par lot.
- ZIP : chemins absolus/`..` refusés, archives chiffrées refusées, limites de
  nombre et de taille décompressée.
- Fichiers privés : pas d'accès direct au media, vue `document_file` protégée.
- CSRF sur tous les POST, audit de chaque étape.
- Pas de clé API ni de secret dans les journaux.

## Commandes

```bash
# Analyse en arrière-plan (cron toutes les 1 à 5 minutes)
python manage.py process_history_imports

# Un lot précis, nombre de documents par exécution
python manage.py process_history_imports --batch <uuid> --limit 20
```

Sur Render, ajouter un Cron Job avec la commande ci-dessus. L'analyse est aussi
reprise automatiquement à l'ouverture du lot.

## Limites V1

- CSV/XLSX : V2.
- Rapprochement des paiements historiques : V2.
- Reprise de balance/FEC : V3.
- OCR dépend de Tesseract côté serveur ; sans Tesseract, le document reste
  consultable et corrigeable manuellement.
- HEIC/HEIF : accepté à l'upload, mais l'OCR peut nécessiter une conversion JPG
  selon le serveur.
- Les factures archivées n'influencent ni la trésorerie ni le grand livre.

## Déploiement / retour arrière

1. `python manage.py migrate` (migrations `history_import`, `documents`,
   `purchases`, `mailsync`).
2. `collectstatic` pour `history-import.js`.
3. Vérifier la variable `GOOGLE...` non nécessaire ici ; le forfait `full`
   active la fonctionnalité.
4. Retour arrière : désactiver l'entrée de menu / le flag `history_import`
   dans le forfait, retirer l'URL `/migration/`. Les tables et archives peuvent
   rester en place ; aucune écriture comptable n'a été générée.

## Tests

```bash
python manage.py test history_import
```

Les tests couvrent : import vente, import achat, absence d'écriture comptable,
doublon de fichier, archive ZIP malveillante, upload multiple, isolation société,
rendu du lot.
