# Remplace la vue company_delete par la version sécurisée (écran de confirmation
# en GET, suppression protégée contre les erreurs de cascade).
path = r"companies/views.py"
lines = open(path, encoding="utf-8", errors="replace").read().splitlines()

# Repérage de l'ancien bloc (@login_required / def company_delete ... jusqu'au
# `return redirect("cockpit")` inclus).
start = None
end = None
for index, line in enumerate(lines):
    if "def company_delete" in line:
        start = index - 1  # @login_required au-dessus
        break
if start is not None:
    for index in range(start, len(lines)):
        if 'return redirect("cockpit")' in lines[index]:
            end = index
            break
if start is None or end is None:
    raise SystemExit("bloc ancien introuvable")

new_block = '''@login_required
def company_delete(request):
    """Supprime définitivement la société courante et ses données rattachées."""
    import logging

    company_id = request.POST.get("societe") or request.GET.get("societe")
    try:
        company = Company.objects.get(pk=company_id, owner=request.user)
    except (Company.DoesNotExist, ValidationError, TypeError):
        raise Http404("Société introuvable.")
    name = company.denomination

    # GET : l'écran de confirmation (aucune suppression sans POST explicite).
    if request.method != "POST":
        return render(request, "companies/company_delete.html", {
            "company": company,
        })
    if request.POST.get("confirm") != "supprimer":
        messages.error(request, "Cochez la confirmation avant de supprimer la société.")
        return redirect(reverse("company_settings") + f"?societe={company.id}")

    try:
        with transaction.atomic():
            if request.session.get("societe_id") == str(company.id):
                request.session.pop("societe_id", None)
            company.delete()
    except Exception as exc:
        # Aucun 500 : certaines données rattachées peuvent encore exister
        # (rapprochements, documents protégés…). Message lisible et sortie propre.
        logging.getLogger(__name__).exception(
            "Suppression de la société %s en échec", company.pk
        )
        messages.error(
            request,
            "La suppression a échoué : des éléments restent rattachés à cette "
            "société. Supprimez-les d'abord, ou contactez le support "
            f"(réf. {company.pk}).",
        )
        return redirect(reverse("company_settings") + f"?societe={company.id}")


'''
lines[start:end + 1] = new_block.splitlines()[:-2]
open(path, "w", encoding="utf-8").write("\n".join(lines))
print("vue remplacée — lignes", start + 1, "à", end + 1)
