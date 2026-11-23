"""Mise à jour de l'agent depuis GitHub, sans intervention sur le PC.

1. verifier()  : compare la version installée à la dernière version du dépôt GitHub.
2. appliquer() : télécharge la nouvelle version, remplace les fichiers du programme (jamais les
                 réglages, la clé ni les tâches, qui sont dans le dossier de l'utilisateur),
                 installe les bibliothèques manquantes, puis redémarre l'agent.
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

import config

DEPOT = "contact190/agent-ideal"
BRANCHE = "main"
URL_COMMIT = f"https://api.github.com/repos/{DEPOT}/commits/{BRANCHE}"
URL_ZIP = f"https://github.com/{DEPOT}/archive/refs/heads/{BRANCHE}.zip"
URL_COMPARER = f"https://api.github.com/repos/{DEPOT}/compare/{{ancien}}...{BRANCHE}"

DOSSIER = config.DOSSIER_PROGRAMME
FICHIER_VERSION = DOSSIER / ".version"
FICHIER_SIGNAL = config.DOSSIER_DONNEES / "maj_terminee.json"   # lu après le redémarrage pour prévenir l'utilisateur
NE_PAS_TOUCHER = {".venv", ".git", "__pycache__"}


def version_locale() -> str:
    return FICHIER_VERSION.read_text(encoding="utf-8").strip() if FICHIER_VERSION.exists() else ""


def _json(url, delai=20):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "agent-ideal"})
    with urllib.request.urlopen(req, timeout=delai) as r:
        return json.loads(r.read())


def verifier() -> dict:
    """{'disponible', 'locale', 'distante', 'changements': [messages], 'date'}"""
    c = _json(URL_COMMIT)
    distante = c["sha"]
    locale = version_locale()
    changements = []
    if locale and locale != distante:
        try:
            comp = _json(URL_COMPARER.format(ancien=locale))
            changements = [x["commit"]["message"].splitlines()[0] for x in comp.get("commits", [])][-15:]
        except Exception:
            pass
    if not changements and locale != distante:
        changements = [c["commit"]["message"].splitlines()[0]]
    return {"disponible": locale != distante, "locale": locale[:7] or "inconnue", "distante": distante[:7],
            "sha": distante, "changements": changements, "date": c["commit"]["committer"]["date"][:10]}


def _python_console():
    """python.exe à côté de pythonw.exe (pip a besoin d'une console)."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and (exe.parent / "python.exe").exists():
        return str(exe.parent / "python.exe")
    return sys.executable


def appliquer(sha: str, prevenir=lambda t: None) -> str:
    """Télécharge et installe la version `sha`. Renvoie un résumé. Ne redémarre pas (voir redemarrer)."""
    prevenir("⬇️ Téléchargement de la nouvelle version…")
    req = urllib.request.Request(URL_ZIP, headers={"User-Agent": "agent-ideal"})
    with urllib.request.urlopen(req, timeout=180) as r:
        donnees = r.read()
    with tempfile.TemporaryDirectory() as tmp:
        zipfile.ZipFile(io.BytesIO(donnees)).extractall(tmp)
        racine = next(p for p in Path(tmp).iterdir() if p.is_dir())
        if not (racine / "app.py").exists():
            raise RuntimeError("Archive inattendue : app.py introuvable.")
        prevenir("📦 Installation des fichiers…")
        n = 0
        for f in racine.rglob("*"):
            rel = f.relative_to(racine)
            if any(part in NE_PAS_TOUCHER for part in rel.parts) or f.is_dir():
                continue
            cible = DOSSIER / rel
            cible.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, cible)
            n += 1
    prevenir("🧩 Vérification des bibliothèques…")
    try:
        lignes = [l.strip() for l in (DOSSIER / "requirements.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
        for paquet in lignes:       # un par un : un échec n'empêche pas les autres
            subprocess.run([_python_console(), "-m", "pip", "install", paquet, "--quiet", "--disable-pip-version-check"],
                           capture_output=True, timeout=900, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as e:
        config.journal(f"Mise à jour : bibliothèques : {e}")
    FICHIER_VERSION.write_text(sha, encoding="utf-8")
    config.journal(f"Mise à jour installée : {sha[:7]} ({n} fichiers)")
    return f"{n} fichiers mis à jour"


def redemarrer(infos: dict = None):
    """Lance une nouvelle instance de l'agent puis arrête celle-ci."""
    FICHIER_SIGNAL.write_text(json.dumps(infos or {}, ensure_ascii=False), encoding="utf-8")
    exe = Path(sys.executable)
    pythonw = exe.parent / "pythonw.exe" if (exe.parent / "pythonw.exe").exists() else exe
    drapeaux = 0
    if sys.platform == "win32":
        drapeaux = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([str(pythonw), str(DOSSIER / "app.py"), "--sans-navigateur", "--apres-maj"],
                     cwd=str(DOSSIER), creationflags=drapeaux, close_fds=True)
    time.sleep(1)
    os._exit(0)


def lire_signal() -> dict:
    """Après un redémarrage : informations sur la mise à jour qui vient d'être faite (une seule fois)."""
    if not FICHIER_SIGNAL.exists():
        return {}
    try:
        infos = json.loads(FICHIER_SIGNAL.read_text(encoding="utf-8"))
    except Exception:
        infos = {}
    FICHIER_SIGNAL.unlink()
    return infos
