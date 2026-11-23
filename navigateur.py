"""Choix du navigateur utilisé par l'agent (interface, connexion Google, sites et logiciels web)."""
import os
import subprocess
import sys
import webbrowser
from pathlib import Path

import config

NOMS = {"defaut": "Navigateur par défaut de Windows", "chrome": "Google Chrome", "edge": "Microsoft Edge",
        "firefox": "Mozilla Firefox", "brave": "Brave", "opera": "Opera"}


def _candidats():
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    local = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
    return {
        "chrome": [rf"{pf}\Google\Chrome\Application\chrome.exe", rf"{pf86}\Google\Chrome\Application\chrome.exe",
                   rf"{local}\Google\Chrome\Application\chrome.exe"],
        "edge": [rf"{pf86}\Microsoft\Edge\Application\msedge.exe", rf"{pf}\Microsoft\Edge\Application\msedge.exe"],
        "firefox": [rf"{pf}\Mozilla Firefox\firefox.exe", rf"{pf86}\Mozilla Firefox\firefox.exe"],
        "brave": [rf"{pf}\BraveSoftware\Brave-Browser\Application\brave.exe", rf"{local}\BraveSoftware\Brave-Browser\Application\brave.exe"],
        "opera": [rf"{local}\Programs\Opera\opera.exe", rf"{pf}\Opera\opera.exe"],
    }


def chemin(nom):
    for c in _candidats().get(nom, []):
        if Path(c).exists():
            return c
    return None


def disponibles():
    """Liste [{id, nom}] des navigateurs installés (toujours avec « par défaut »)."""
    res = [{"id": "defaut", "nom": NOMS["defaut"]}]
    for n in ("chrome", "edge", "firefox", "brave", "opera"):
        if sys.platform != "win32" or chemin(n):
            res.append({"id": n, "nom": NOMS[n]})
    return res


def nom_webbrowser():
    """Nom à passer à webbrowser.get() / run_local_server(browser=…), ou None pour le navigateur par défaut."""
    choix = config.charger_reglages().get("navigateur", "defaut")
    exe = chemin(choix) if choix != "defaut" else None
    if not exe:
        return None
    webbrowser.register("agent_ideal", None, webbrowser.BackgroundBrowser(exe))
    return "agent_ideal"


def ouvrir(url: str):
    nom = nom_webbrowser()
    if nom:
        webbrowser.get(nom).open(url)
    elif sys.platform == "win32":
        os.startfile(url)  # noqa
    else:
        webbrowser.open(url)
