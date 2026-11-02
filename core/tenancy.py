from django.conf import settings


def set_current_tenant(request, company):
    """ Pose le tenant courant pour la requête (plus tard : RLS via GUC Postgres)."""
    request.tenant = company


def validate_tenant_access(company, user):
    """Zero Trust basique : un user ne voit que SES sociétés.
    Plus tard : renforcé par RLS postgre (policy + tenant_id sur chaque table)."""
    return company.owner_id == user.id


class TenantMiddleware:
    """Middleware simple : extrait tenant_id, injecte request.tenant.

    TODO (S1) : brancher l'isolation Postgres RLS via la session (set_config):
       SET app.tenant_id = ...  -> policy USING (tenant_id = current_setting('app.tenant_id')::uuid)
       Un seul wrapper : voir "core/tenancy.py".
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.tenant = None
        response = self.get_response(request)
        return response
