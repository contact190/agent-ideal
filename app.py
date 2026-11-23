"""Agent Idéal : serveur local + ouverture de l'interface dans le navigateur.

L'interface n'est accessible QUE depuis cet ordinateur (127.0.0.1), et chaque requête doit
porter un jeton secret généré au démarrage. Phase 2 (téléphone) : on branchera un accès
distant sécurisé sur ces mêmes routes /api/…
"""

import json
import secrets
import socket
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parent))


import config

if sys.stdout is None or sys.stderr is None:          # lancé sans console (pythonw) : on écrit dans un fichier
    _sortie = open(config.DOSSIER_DONNEES / "sortie.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or _sortie
    sys.stderr = sys.stderr or _sortie
import outils_google as G
import agent as module_agent
import routines
from agent import Agent, Bus

PORT_PREFERE = 8765
JETON = secrets.token_urlsafe(24)
DOSSIER_INTERFACE = Path(__file__).parent / "interface"

bus = Bus()
agent = Agent(bus)
planificateur = None          # démarré dans main()
_google_connexion = {"en_cours": False, "erreur": ""}


def etat_complet():
    r = config.charger_reglages()
    return {
        "cle_ok": bool(config.lire_cle_api()),
        "google": G.etat(),
        "google_connexion": _google_connexion,
        "reglages": r,
        "en_cours": agent.en_cours,
        "tokens": agent.tokens,
        "fil": agent.fil_pour_affichage(),
        "planificateur": planificateur.etat() if planificateur else {},
    }


def etat_routines():
    rs = routines.lister()
    for r in rs:
        p = routines.prochaine_execution(r)
        r["prochaine"] = p.strftime("%d/%m/%Y %H:%M") if p and r.get("actif", True) else ""
        r["horaire"] = routines.decrire_horaire(r)
    return {"routines": rs, "historique": routines.historique(20), "planificateur": planificateur.etat() if planificateur else {}}


def tester_cle(cle: str) -> str:
    import anthropic
    try:
        anthropic.Anthropic(api_key=cle, max_retries=1, timeout=30).models.list(limit=1)
        return ""
    except anthropic.AuthenticationError:
        return "Clé refusée par Anthropic : vérifie qu'elle est bien copiée en entier."
    except anthropic.APIConnectionError:
        return "Impossible de joindre Anthropic : vérifie la connexion Internet."
    except Exception as e:
        return f"{type(e).__name__} : {e}"


def connecter_google():
    _google_connexion.update(en_cours=True, erreur="")
    try:
        G.connecter()
    except Exception as e:
        texte = str(e)
        if "access_denied" in texte:
            texte = "Connexion refusée par Google. Si ton compte n'est pas autorisé, demande à être ajouté comme utilisateur."
        _google_connexion["erreur"] = texte
    finally:
        _google_connexion["en_cours"] = False
        bus.publier({"type": "google", "etat": G.etat()})


class Gestionnaire(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    # ------------- utilitaires
    def _json(self, donnees, code=200):
        corps = json.dumps(donnees, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corps)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corps)

    def _corps(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def _autorise(self):
        jeton = self.headers.get("X-Jeton") or parse_qs(urlparse(self.path).query).get("jeton", [""])[0]
        return secrets.compare_digest(jeton, JETON)

    # ------------- GET
    def do_GET(self):
        chemin = urlparse(self.path).path
        if chemin in ("/", "/index.html"):
            html = (DOSSIER_INTERFACE / "index.html").read_text(encoding="utf-8").replace("__JETON__", JETON)
            corps = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(corps)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(corps)
            return
        if chemin == "/ping":
            return self._json({"app": "agent-ideal"})
        if chemin == "/favicon.ico":
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if not self._autorise():
            return self._json({"erreur": "non autorisé"}, 403)
        if chemin == "/api/etat":
            return self._json(etat_complet())
        if chemin == "/api/routines":
            return self._json(etat_routines())
        if chemin == "/api/evenements":
            return self._flux()
        self._json({"erreur": "introuvable"}, 404)

    def _flux(self):
        q = bus.abonner()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            while True:
                try:
                    evt = q.get(timeout=15)
                    donnees = f"data: {json.dumps(evt, ensure_ascii=False, default=str)}\n\n"
                except Exception:
                    donnees = ": ping\n\n"
                self.wfile.write(donnees.encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            bus.desabonner(q)
            self.close_connection = True

    # ------------- POST
    def do_POST(self):
        if not self._autorise():
            return self._json({"erreur": "non autorisé"}, 403)
        chemin = urlparse(self.path).path
        try:
            d = self._corps()
        except Exception:
            return self._json({"erreur": "requête illisible"}, 400)

        if chemin == "/api/message":
            texte = (d.get("texte") or "").strip()
            if not texte:
                return self._json({"ok": False, "erreur": "Message vide."})
            if not config.lire_cle_api():
                return self._json({"ok": False, "erreur": "Ajoute d'abord ta clé API Claude dans les Réglages."})
            return self._json({"ok": agent.envoyer(texte), "erreur": "" if not agent.en_cours else ""})
        if chemin == "/api/stop":
            agent.arreter()
            return self._json({"ok": True})
        if chemin == "/api/confirmation":
            return self._json({"ok": agent.repondre_confirmation(d.get("id", ""), d.get("accepte", False))})
        if chemin == "/api/nouvelle":
            return self._json({"ok": agent.nouvelle_conversation()})
        if chemin == "/api/cle":
            cle = (d.get("cle") or "").strip()
            if not cle.startswith("sk-ant-"):
                return self._json({"ok": False, "erreur": "Une clé Claude commence par « sk-ant- »."})
            erreur = tester_cle(cle)
            if erreur:
                return self._json({"ok": False, "erreur": erreur})
            config.enregistrer_cle_api(cle)
            return self._json({"ok": True})
        if chemin == "/api/cle/effacer":
            config.effacer_cle_api()
            return self._json({"ok": True})
        if chemin == "/api/google/connecter":
            if not _google_connexion["en_cours"]:
                threading.Thread(target=connecter_google, daemon=True).start()
            return self._json({"ok": True})
        if chemin == "/api/google/deconnecter":
            G.deconnecter()
            return self._json({"ok": True})
        if chemin == "/api/reglages":
            if "dossiers_autorises" in d:
                d["dossiers_autorises"] = [x.strip() for x in d["dossiers_autorises"] if x.strip() and Path(x.strip()).expanduser().is_dir()]
            return self._json({"ok": True, "reglages": config.enregistrer_reglages(d)})
        if chemin == "/api/routines/enregistrer":
            try:
                return self._json({"ok": True, "routine": routines.enregistrer(d)})
            except Exception as e:
                return self._json({"ok": False, "erreur": str(e)})
        if chemin == "/api/routines/supprimer":
            return self._json({"ok": routines.supprimer(d.get("id", ""))})
        if chemin == "/api/routines/lancer":
            return self._json({"ok": planificateur.lancer_maintenant(d.get("id", ""))})
        if chemin == "/api/routines/arreter":
            planificateur.arreter_en_cours()
            return self._json({"ok": True})
        if chemin == "/api/quitter":
            self._json({"ok": True})
            threading.Thread(target=lambda: (time.sleep(0.5), serveur.shutdown()), daemon=True).start()
            return
        self._json({"erreur": "introuvable"}, 404)


def _port_libre():
    for port in (PORT_PREFERE, PORT_PREFERE + 1, PORT_PREFERE + 2, 0):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue


serveur = None


def _deja_lance():
    """Si l'agent tourne déjà, on rouvre simplement sa fenêtre."""
    import urllib.request
    for port in (PORT_PREFERE, PORT_PREFERE + 1, PORT_PREFERE + 2):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/ping", timeout=1) as r:
                if json.loads(r.read()).get("app") == "agent-ideal":
                    return f"http://127.0.0.1:{port}/"
        except Exception:
            continue
    return None


def main():
    global serveur
    deja = _deja_lance()
    if deja:
        webbrowser.open(deja)
        return
    global planificateur
    planificateur = routines.Planificateur(bus)
    module_agent.PLANIFICATEUR = planificateur
    port = _port_libre()
    serveur = ThreadingHTTPServer(("127.0.0.1", port), Gestionnaire)
    serveur.daemon_threads = True
    adresse = f"http://127.0.0.1:{port}/"
    print(f"Agent Idéal démarré : {adresse}  (ferme cette fenêtre pour l'arrêter)")
    config.journal(f"Démarrage sur {adresse}")
    if "--sans-navigateur" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(adresse)).start()
    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
