"""Réglages de l'agent : stockés dans le dossier de l'utilisateur, jamais dans le dossier du programme.

- Windows : %APPDATA%\\AgentIdeal
- Mac/Linux : ~/.agent-ideal
La clé API Claude est rangée dans le coffre-fort du système (Gestionnaire d'identifiants Windows)
via `keyring`. Si le coffre-fort n'est pas disponible, elle est gardée dans le dossier de réglages.
"""

import json
import os
import sys
from pathlib import Path

NOM_APP = "AgentIdeal"

if sys.platform == "win32":
    DOSSIER_DONNEES = Path(os.environ.get("APPDATA", Path.home())) / NOM_APP
else:
    DOSSIER_DONNEES = Path.home() / ".agent-ideal"
DOSSIER_DONNEES.mkdir(parents=True, exist_ok=True)

FICHIER_REGLAGES = DOSSIER_DONNEES / "reglages.json"
FICHIER_TOKEN_GOOGLE = DOSSIER_DONNEES / "google_token.json"
FICHIER_JOURNAL = DOSSIER_DONNEES / "journal.txt"
DOSSIER_CONVERSATIONS = DOSSIER_DONNEES / "conversations"
DOSSIER_CONVERSATIONS.mkdir(exist_ok=True)
DOSSIER_PROGRAMME = Path(__file__).parent


def _dossiers_par_defaut():
    maison = Path.home()
    candidats = [maison / "Desktop", maison / "Bureau", maison / "Documents", maison / "Downloads",
                 maison / "OneDrive" / "Desktop", maison / "OneDrive" / "Documents"]
    return [str(p) for p in candidats if p.exists()]


REGLAGES_PAR_DEFAUT = {
    "modele": "claude-sonnet-5-5",
    "dossiers_autorises": _dossiers_par_defaut(),
    "ecran_actif": True,
    "navigateur": "defaut",
    "telegram_chat_id": None,        # compte Telegram appairé (téléphone)
    "telegram_nom": "",
    "telegram_notifier_taches": True,
    "telegram_tout_suivre": True,    # relayer aussi les réponses et questions des demandes faites depuis le PC
    "telegram_notifier_debut": False,          # defaut, chrome, edge, firefox, brave, opera
    "commandes_actives": True,
    "google_mode_test": False,      # True quand l'application Google est « Externe » en mode test (reconnexion tous les 7 jours)
    "rappel_google_jours": 6,
    "nom_utilisateur": "",
    "entreprise": "",
    "consignes": "",                # consignes permanentes ajoutées au prompt de l'agent
    "applications": [],             # logiciels métier : [{"nom", "adresse", "description"}]
}


def charger_reglages() -> dict:
    reglages = dict(REGLAGES_PAR_DEFAUT)
    if FICHIER_REGLAGES.exists():
        try:
            reglages.update(json.loads(FICHIER_REGLAGES.read_text(encoding="utf-8")))
        except Exception:
            pass
    return reglages


def enregistrer_reglages(nouveaux: dict) -> dict:
    reglages = charger_reglages()
    for cle in REGLAGES_PAR_DEFAUT:
        if cle in nouveaux:
            reglages[cle] = nouveaux[cle]
    FICHIER_REGLAGES.write_text(json.dumps(reglages, ensure_ascii=False, indent=2), encoding="utf-8")
    return reglages


# ---------- Clé API Claude ----------

_FICHIER_CLE_SECOURS = DOSSIER_DONNEES / ".cle"


def lire_cle_api() -> str:
    try:
        import keyring
        cle = keyring.get_password(NOM_APP, "anthropic")
        if cle:
            return cle
    except Exception:
        pass
    if _FICHIER_CLE_SECOURS.exists():
        return _FICHIER_CLE_SECOURS.read_text(encoding="utf-8").strip()
    return os.environ.get("ANTHROPIC_API_KEY", "")


def enregistrer_cle_api(cle: str):
    cle = cle.strip()
    try:
        import keyring
        keyring.set_password(NOM_APP, "anthropic", cle)
        if _FICHIER_CLE_SECOURS.exists():
            _FICHIER_CLE_SECOURS.unlink()
        return
    except Exception:
        pass
    _FICHIER_CLE_SECOURS.write_text(cle, encoding="utf-8")


def effacer_cle_api():
    try:
        import keyring
        keyring.delete_password(NOM_APP, "anthropic")
    except Exception:
        pass
    if _FICHIER_CLE_SECOURS.exists():
        _FICHIER_CLE_SECOURS.unlink()


def journal(texte: str):
    import datetime
    try:
        with FICHIER_JOURNAL.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {texte}\n")
    except Exception:
        pass
