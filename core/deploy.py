"""Migrations au démarrage (Vercel) et rattrapage du schéma du back-office.

Le build Vercel lance `migrate`. S'il n'atteint pas la base, la fonction
serverless réessaie. Si l'historique Django dit « déjà appliqué » alors qu'il
manque une colonne (ou que les fichiers de migration n'étaient pas dans le
bundle), on ajoute les tables et colonnes décrites par les modèles. Ce sont
les colonnes lues par Forfaits, Abonnements, Paramètres, Intégrations,
Consignes et SMS — les pages qui répondaient 500.
"""
from __future__ import annotations

import logging
import os
from copy import deepcopy

from django.apps import apps
from django.conf import settings
from django.core.management import call_command
from django.db import connections
from django.db.migrations.recorder import MigrationRecorder

logger = logging.getLogger(__name__)

# Migrations additives du back-office. On les note comme appliquées seulement
# quand le schéma qu'elles décrivent est réellement là (migrate ou rattrapage).
KNOWN_MIGRATIONS = (
    ("accounts", "0002_pendingsignup"),
    ("admin_backoffice", "0002_backoffice_extensions"),
    ("billing", "0002_backoffice_extensions"),
)

# (table, colonne ou None si seule la table doit exister)
REQUIRED_SCHEMA = (
    ("admin_backoffice_siteconfiguration", "ai_system_prompt"),
    ("admin_backoffice_siteconfiguration", "admin_ai_prompt"),
    ("billing_plan", "ai_prompt"),
    ("billing_plan", "description"),
    ("billing_plan", "features"),
    ("billing_plan", "is_active"),
    ("billing_plan", "max_companies"),
    ("billing_plan", "max_invoices_month"),
    ("billing_plan", "max_ai_requests_month"),
    ("admin_backoffice_smsproviderconfig", None),
    ("admin_backoffice_smssettings", None),
    ("admin_backoffice_smstemplate", None),
    ("admin_backoffice_smsmessage", None),
    ("accounts_pendingsignup", None),
)

# Ordre : les clés étrangères de SmsMessage exigent le modèle SMS et User.
HEAL_LABELS = (
    "accounts.PendingSignup",
    "admin_backoffice.SiteConfiguration",
    "admin_backoffice.SmsProviderConfig",
    "admin_backoffice.SmsSettings",
    "admin_backoffice.SmsTemplate",
    "admin_backoffice.SmsMessage",
    "billing.Plan",
)

_state = {"ok": False}
_saved_database = None


def _direct_database_url() -> str:
    """Connexion directe (sans pooler) pour le DDL, si Vercel / Neon la fournit."""
    for key in ("DATABASE_URL_UNPOOLED", "POSTGRES_URL_NON_POOLING"):
        value = (os.environ.get(key) or "").strip()
        if value.startswith("postgres"):
            return value
    return ""


def _drop_connections() -> None:
    connections.close_all()
    try:
        del connections["default"]
    except (AttributeError, KeyError):
        pass


def _reset_connection() -> None:
    try:
        connections["default"].rollback()
    except Exception:
        logger.debug("rollback ignoré", exc_info=True)
    _drop_connections()


def _swap_to_direct() -> bool:
    global _saved_database
    url = _direct_database_url()
    current = (os.environ.get("DATABASE_URL") or "").strip()
    if not url or url == current:
        return False
    from config.dburl import database_from_url

    _saved_database = deepcopy(settings.DATABASES["default"])
    settings.DATABASES["default"] = database_from_url(url)
    _drop_connections()
    return True


def _restore_database() -> None:
    global _saved_database
    if _saved_database is None:
        return
    settings.DATABASES["default"] = _saved_database
    _saved_database = None
    _drop_connections()


def _column_names(table: str) -> set[str]:
    connection = connections["default"]
    with connection.cursor() as cursor:
        description = connection.introspection.get_table_description(cursor, table)
    return {column.name for column in description}


def schema_ready() -> bool:
    """True si les colonnes et tables du back-office étendu sont présentes."""
    try:
        connection = connections["default"]
        tables = set(connection.introspection.table_names())
        for table, column in REQUIRED_SCHEMA:
            if table not in tables:
                logger.error("Schéma incomplet : table %s absente", table)
                return False
            if column and column not in _column_names(table):
                logger.error("Schéma incomplet : colonne %s.%s absente", table, column)
                return False
    except Exception:
        logger.exception("Vérification du schéma impossible")
        return False
    return True


def _ensure_model(editor, model, existing: set[str]) -> None:
    table = model._meta.db_table
    if table not in existing:
        editor.create_model(model)
        existing.add(table)
        return
    have = _column_names(table)
    for field in model._meta.local_fields:
        column = getattr(field, "column", None)
        if column and column not in have:
            _add_column(editor, model, field)
            have.add(column)


def _add_column(editor, model, field) -> None:
    """ALTER TABLE ADD COLUMN, sans retirer le DEFAULT (SQLite ne sait pas).

    Le schema editor de SQLite reconstruit toute la table pour un JSONField
    et échoue si d'autres colonnes manquent encore. Un ADD COLUMN suffit
    pour Postgres (production) comme pour SQLite.
    """
    definition, params = editor.column_sql(model, field, include_default=True)
    if not definition:
        return
    suffix = field.db_type_suffix(connection=editor.connection)
    if suffix:
        definition += f" {suffix}"
    db_params = field.db_parameters(connection=editor.connection)
    if db_params.get("check"):
        definition += " " + editor.sql_check_constraint % db_params
    sql = editor.sql_create_column % {
        "table": editor.quote_name(model._meta.db_table),
        "column": editor.quote_name(field.column),
        "definition": definition,
    }
    editor.execute(sql, params or None)


def _drop_sqlite_rebuild_leftovers() -> None:
    connection = connections["default"]
    if connection.vendor != "sqlite":
        return
    leftovers = [
        name for name in connection.introspection.table_names() if name.startswith("new__")
    ]
    if not leftovers:
        return
    with connection.cursor() as cursor:
        for name in leftovers:
            cursor.execute(f'DROP TABLE IF EXISTS "{name}"')


def _heal_schema() -> None:
    """Crée les tables et colonnes manquantes à partir des modèles."""
    _reset_connection()
    _drop_sqlite_rebuild_leftovers()
    for label in HEAL_LABELS:
        model = apps.get_model(label)
        try:
            connection = connections["default"]
            existing = set(connection.introspection.table_names())
            with connection.schema_editor(atomic=False) as editor:
                _ensure_model(editor, model, existing)
        except Exception:
            logger.exception("Rattrapage du schéma impossible pour %s", label)
            _reset_connection()


def _mark_known_applied() -> None:
    connection = connections["default"]
    recorder = MigrationRecorder(connection)
    applied = recorder.applied_migrations()
    for app_label, name in KNOWN_MIGRATIONS:
        if (app_label, name) not in applied:
            recorder.record_applied(app_label, name)


def assurer_migrations(*, force: bool = False) -> bool:
    """Applique les migrations, puis rattrape le schéma s'il est encore en retard.

    Retourne True quand les pages du back-office peuvent lire leurs colonnes.
    Un échec ne lève pas : l'appelant réessaie à la requête suivante.
    """
    if _state["ok"] and not force:
        return True
    swapped = _swap_to_direct()
    try:
        _reset_connection()
        try:
            call_command("migrate", interactive=False, verbosity=1)
        except Exception:
            logger.exception("migrate a échoué")
        if not schema_ready():
            _heal_schema()
        if schema_ready():
            try:
                _mark_known_applied()
            except Exception:
                logger.exception("Historique des migrations non mis à jour")
        ok = schema_ready()
        _state["ok"] = ok
        print("[migrations] base à jour" if ok else "[migrations] schéma incomplet", flush=True)
        return ok
    finally:
        if swapped:
            _restore_database()
        else:
            _drop_connections()
