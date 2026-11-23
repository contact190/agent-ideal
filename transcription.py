"""Transcription des messages vocaux (Telegram) en texte, avant de les donner à l'agent.

L'API Claude n'accepte pas l'audio : on transcrit d'abord.
- « groq »   : Whisper large v3 chez Groq (clé gratuite sur console.groq.com) — le plus précis, darija compris.
- « openai » : Whisper chez OpenAI (clé payante).
- « local »  : faster-whisper sur le PC, sans clé ni Internet (plus lent ; modèle ~500 Mo téléchargé la 1re fois).
- « auto »   : Groq si une clé Groq est enregistrée, sinon OpenAI si clé, sinon local.
"""

import json
import tempfile
import threading
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import config

# vocabulaire du métier : aide Whisper à bien écrire les termes techniques
VOCABULAIRE = ("Devis, précadre, vantail, coulissant, ouvrant, oscillo-battant, aluminium, PVC, H52, profilé, "
               "vitrage, double vitrage, volet roulant, pose, TVA, marge, CalculDevis, Stock NV, Idéal Aluminium.")

FOURNISSEURS = {
    "groq": ("https://api.groq.com/openai/v1/audio/transcriptions", "whisper-large-v3"),
    "openai": ("https://api.openai.com/v1/audio/transcriptions", "whisper-1"),
}

_modele_local = None
_verrou_local = threading.Lock()


class ErreurTranscription(Exception):
    pass


# ---------------------------------------------------------------- clés (coffre-fort)

def lire_cle(fournisseur: str) -> str:
    try:
        import keyring
        return keyring.get_password(config.NOM_APP, f"stt_{fournisseur}") or ""
    except Exception:
        f = config.DOSSIER_DONNEES / f".stt_{fournisseur}"
        return f.read_text(encoding="utf-8").strip() if f.exists() else ""


def enregistrer_cle(fournisseur: str, cle: str):
    cle = cle.strip()
    fichier = config.DOSSIER_DONNEES / f".stt_{fournisseur}"
    try:
        import keyring
        if cle:
            keyring.set_password(config.NOM_APP, f"stt_{fournisseur}", cle)
            if fichier.exists():
                fichier.unlink()
            return
        try:
            keyring.delete_password(config.NOM_APP, f"stt_{fournisseur}")
        except Exception:
            pass
    except Exception:
        if cle:
            fichier.write_text(cle, encoding="utf-8")
            return
    if not cle and fichier.exists():
        fichier.unlink()


def local_disponible() -> bool:
    try:
        import faster_whisper  # noqa
        return True
    except Exception:
        return False


def mode_effectif() -> str:
    choix = config.charger_reglages().get("vocal_mode", "auto")
    if choix != "auto":
        return choix
    if lire_cle("groq"):
        return "groq"
    if lire_cle("openai"):
        return "openai"
    if local_disponible():
        return "local"
    return "aucun"


def etat() -> dict:
    return {"mode": config.charger_reglages().get("vocal_mode", "auto"), "effectif": mode_effectif(),
            "cle_groq": bool(lire_cle("groq")), "cle_openai": bool(lire_cle("openai")), "local": local_disponible()}


# ---------------------------------------------------------------- transcription

def _en_ligne(fournisseur, octets, nom):
    url, modele = FOURNISSEURS[fournisseur]
    cle = lire_cle(fournisseur)
    if not cle:
        raise ErreurTranscription(f"Pas de clé {fournisseur.capitalize()} : ajoute-la dans Réglages → Téléphone.")
    limite = "----agentideal" + uuid.uuid4().hex
    champs = {"model": modele, "response_format": "json", "prompt": VOCABULAIRE, "temperature": "0"}
    corps = b""
    for k, v in champs.items():
        corps += f"--{limite}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode("utf-8")
    corps += (f"--{limite}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{nom}\"\r\n"
              f"Content-Type: audio/ogg\r\n\r\n").encode("utf-8") + octets + f"\r\n--{limite}--\r\n".encode()
    req = urllib.request.Request(url, data=corps, headers={
        "Authorization": f"Bearer {cle}",
        "Content-Type": f"multipart/form-data; boundary={limite}",
        # sans identité de navigateur, Cloudflare (qui protège Groq) refuse avec « error code: 1010 »
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AgentIdeal/1.0",
        "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read()).get("text", "").strip()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:300]
        if e.code == 403 and "1010" in detail:
            raise ErreurTranscription("Le service de transcription a bloqué la demande (protection anti-robots). "
                                      "Fais /majour pour avoir le correctif, puis réessaie.")
        if e.code == 401:
            raise ErreurTranscription(f"Clé {fournisseur.capitalize()} refusée : vérifie-la dans les Réglages.")
        if e.code == 429:
            raise ErreurTranscription("Limite de transcriptions atteinte pour le moment : réessaie dans une minute.")
        raise ErreurTranscription(f"Erreur {fournisseur} {e.code} : {detail}")
    except urllib.error.URLError as e:
        raise ErreurTranscription(f"Service de transcription injoignable ({e.reason}).")


def _local(octets, nom, prevenir=None):
    global _modele_local
    if not local_disponible():
        raise ErreurTranscription("La transcription sur le PC n'est pas installée. Relance 1_INSTALLER.bat, "
                                  "ou ajoute une clé Groq gratuite dans Réglages → Téléphone.")
    from faster_whisper import WhisperModel
    with _verrou_local:
        if _modele_local is None:
            if prevenir:
                prevenir("⏳ Première utilisation : je télécharge le modèle de reconnaissance vocale (~500 Mo). "
                         "Ça peut prendre quelques minutes, une seule fois.")
            dossier = config.DOSSIER_DONNEES / "modeles_voix"
            _modele_local = WhisperModel("small", device="cpu", compute_type="int8", download_root=str(dossier))
        with tempfile.NamedTemporaryFile(suffix=Path(nom).suffix or ".ogg", delete=False) as f:
            f.write(octets)
            chemin = f.name
        try:
            segments, _ = _modele_local.transcribe(chemin, initial_prompt=VOCABULAIRE, vad_filter=True, beam_size=5)
            return " ".join(s.text.strip() for s in segments).strip()
        finally:
            try:
                Path(chemin).unlink()
            except Exception:
                pass


def transcrire(octets: bytes, nom: str = "vocal.ogg", prevenir=None) -> str:
    """Renvoie le texte du message vocal. prevenir(texte) sert à informer l'utilisateur d'une attente."""
    mode = mode_effectif()
    if mode in FOURNISSEURS:
        return _en_ligne(mode, octets, nom)
    if mode == "local":
        return _local(octets, nom, prevenir)
    raise ErreurTranscription("Aucun moyen de transcrire les vocaux n'est configuré. Ajoute une clé Groq gratuite "
                              "(console.groq.com → API Keys) dans Réglages → Téléphone de l'Agent Idéal.")
