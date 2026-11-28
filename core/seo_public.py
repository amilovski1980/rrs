"""Fichiers SEO publics : robots.txt et sitemap.xml."""
from django.http import HttpResponse


def robots_txt(request):
    sitemap = request.build_absolute_uri("/sitemap.xml")
    body = "User-agent: *\nAllow: /\nSitemap: " + sitemap + "\n"
    return HttpResponse(body, content_type="text/plain; charset=utf-8")


def sitemap_xml(request):
    base = request.build_absolute_uri("/").rstrip("/")
    urls = [base + "/", base + "/clair/", base + "/inscription/"]
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(f"<url><loc>{url}</loc></url>" for url in urls)
        + "</urlset>"
    )
    return HttpResponse(body, content_type="application/xml; charset=utf-8")
