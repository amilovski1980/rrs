"""Assemble la consigne réellement envoyée à Aminia (chat et voix)."""
from __future__ import annotations


def agent_instructions(user, company, *, channel: str = "voice") -> str:
    """Consigne générale, contexte de la société, puis cadre du forfait (prioritaire)."""
    from admin_backoffice.agent_prompts import layers_for_user

    from .assistant import instructions_for

    global_text, plan_text = layers_for_user(user)
    situational = instructions_for(user, company)
    if channel == "chat":
        situational = (
            situational.replace("assistante comptable vocale", "assistante comptable")
            .replace("phrases très courtes, adaptées à la voix", "phrases claires et concises")
            .replace("à voix haute", "clairement")
            + " Tu réponds en mode chat texte. Les brouillons (écritures, clients) "
            "restent à valider par un humain."
        )
    return "\n\n".join([
        global_text.strip(),
        situational.strip(),
        "Cadre du forfait — prioritaire. S'il contredit une autorisation précédente, "
        "tu suis ce cadre et tu n'appelles pas les outils interdits.\n\n" + plan_text.strip(),
    ])
