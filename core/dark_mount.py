"""Monte toute l'application sous /dark sans dupliquer les vues.

Le préfixe est retiré avant le routeur. Les liens générés pendant la requête
repartent sous /dark grâce au préfixe de script de Django.
"""
from __future__ import annotations

from django.urls import set_script_prefix

PREFIX = "/dark"


def app_path(request) -> str:
    """Chemin vu par les règles métier, sans le préfixe visuel."""
    return request.path_info or "/"


def _strip(path: str) -> str | None:
    if path == PREFIX or path.startswith(PREFIX + "/"):
        rest = path[len(PREFIX):] or "/"
        if not rest.startswith("/"):
            rest = "/" + rest
        return rest
    return None


def _keep_in_dark(location: str) -> str:
    if not location.startswith("/") or location.startswith("//"):
        return location
    if location == PREFIX or location.startswith(PREFIX + "/"):
        return location
    return PREFIX + location


class DarkMountMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        rest = _strip(request.path_info or "/")
        request.dark_ui = rest is not None
        if rest is None:
            return self.get_response(request)
        request.path_info = rest
        set_script_prefix(PREFIX)
        try:
            response = self.get_response(request)
        finally:
            set_script_prefix("/")
        location = response.get("Location")
        if location:
            response["Location"] = _keep_in_dark(location)
        return response
