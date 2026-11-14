"""Façade domaine du fournisseur.

Le modèle physique est encore ``mailsync.Supplier`` (créé avec le connecteur
e-mail). Ce proxy donne au fournisseur sa propre app métier et permettra de
déplacer la table sans casser les migrations dans une étape dédiée.
"""

from mailsync.models import Supplier as SupplierModel


class Supplier(SupplierModel):
    class Meta:
        proxy = True
        verbose_name = "Fournisseur"
        verbose_name_plural = "Fournisseurs"
        ordering = ["name"]
