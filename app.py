"""Agent Idéal : serveur local + ouverture de l'interface dans le navigateur.

L'interface n'est accessible QUE depuis cet ordinateur (127.0.0.1), et chaque requête doit
porter un jeton secret généré au démarrage. Phase 2 (téléphone) : on branchera un accès
distant sécurisé sur ces mêmes routes /api/…
"""

import json
import re
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
import navigateur
import routines
import telegram_bot
import transcription
import mise_a_jour
from agent import Agent, Bus

PORT_PREFERE = 8765
JETON = secrets.token_urlsafe(24)
DOSSIER_INTERFACE = Path(__file__).parent / "interface"

bus = Bus()
agent = Agent(bus)
planificateur = None          # démarré dans main()
bot = None                    # bot Telegram, démarré dans main()


def repondre_confirmation(id_conf, accepte) -> bool:
    """Une validation peut venir de la conversation ou d'une tâche automatique en cours."""
    if agent.repondre_confirmation(id_conf, accepte):
        return True
    en_cours = planificateur._agent_en_cours if planificateur else None
    return bool(en_cours and en_cours.repondre_confirmation(id_conf, accepte))
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
        "navigateurs": navigateur.disponibles(),
        "telegram": bot.etat() if bot else {},
        "vocal": transcription.etat(),
        "version": mise_a_jour.version_locale()[:7] or "inconnue",
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


def choisir_dossier() -> str:
    """Ouvre la fenêtre Windows « Choisir un dossier » sur l'ordinateur et renvoie le chemin choisi ('' si annulé)."""
    import subprocess
    import tempfile
    sortie = Path(tempfile.gettempdir()) / f"agent_ideal_dossier_{secrets.token_hex(4)}.txt"
    code = ("import sys, tkinter as tk, tkinter.filedialog as fd\n"
            "r = tk.Tk(); r.withdraw(); r.attributes('-topmost', True); r.update()\n"
            "c = fd.askdirectory(parent=r, title=\"Agent Idéal : choisis un dossier que l'agent pourra utiliser\", mustexist=True)\n"
            "open(sys.argv[1], 'w', encoding='utf-8').write(c or '')\n")
    try:
        subprocess.run([sys.executable, "-c", code, str(sortie)], timeout=600)
        chemin = sortie.read_text(encoding="utf-8").strip() if sortie.exists() else ""
    finally:
        try:
            sortie.unlink()
        except Exception:
            pass
    return str(Path(chemin)) if chemin else ""


_maj = {"en_cours": False}


def installer_mise_a_jour(sha, prevenir=lambda t: None, origine="interface"):
    """Installe la version `sha` puis redémarre l'agent. Renvoie un message d'erreur, ou ne revient pas."""
    if _maj["en_cours"]:
        return "Une mise à jour est déjà en cours."
    if agent.en_cours or (planificateur and planificateur.etat().get("en_cours")):
        return "L'agent est en train de travailler : attends la fin (ou /stop) puis relance la mise à jour."
    _maj["en_cours"] = True
    bus.publier({"type": "maj", "etape": "debut"})
    try:
        resume = mise_a_jour.appliquer(sha, prevenir)
    except Exception as e:
        _maj["en_cours"] = False
        config.journal(f"Mise à jour échouée : {e}")
        return f"La mise à jour a échoué : {e}"
    prevenir(f"♻️ {resume}. Redémarrage de l'agent…")
    bus.publier({"type": "maj", "etape": "redemarrage"})
    time.sleep(1.5)
    mise_a_jour.redemarrer({"version": sha[:7], "origine": origine,
                            "chat_id": config.charger_reglages().get("telegram_chat_id")})


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
        if chemin in ("/favicon.ico", "/icone.png"):
            fichier = Path(__file__).parent / ("icone.ico" if chemin == "/favicon.ico" else "interface/icone.png")
            corps = fichier.read_bytes() if fichier.exists() else b""
            self.send_response(200 if corps else 204)
            self.send_header("Content-Type", "image/x-icon" if chemin == "/favicon.ico" else "image/png")
            self.send_header("Content-Length", str(len(corps)))
            self.send_header("Cache-Control", "max-age=86400")
            self.end_headers()
            self.wfile.write(corps)
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
            return self._json({"ok": repondre_confirmation(d.get("id", ""), d.get("accepte", False))})
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
        if chemin == "/api/telegram/jeton":
            jeton = (d.get("jeton") or "").strip()
            if not re.match(r"^\d+:[\w-]{30,}$", jeton):
                return self._json({"ok": False, "erreur": "Ce n'est pas un jeton de bot (format 123456789:ABC…). Copie-le depuis @BotFather."})
            erreur = ""
            for essai in range(3):                       # connexion parfois lente : on réessaie
                try:
                    telegram_bot.verifier_jeton(jeton)
                    erreur = ""
                    break
                except telegram_bot.ErreurTelegram as e:
                    erreur = f"Jeton refusé par Telegram ({e}) : recopie-le depuis @BotFather."
                    break
                except Exception as e:
                    erreur = ("Telegram est injoignable depuis ce PC (connexion lente ou bloquée). "
                              f"Vérifie Internet puis réessaie dans un instant. Détail : {e}")
                    time.sleep(2)
            if erreur:
                return self._json({"ok": False, "erreur": erreur})
            telegram_bot.enregistrer_jeton(jeton)
            bot.dissocier()
            bot.demarrer()
            return self._json({"ok": True, "telegram": bot.etat(), "appairage": bot.nouveau_code()})
        if chemin == "/api/vocal":
            if "mode" in d:
                config.enregistrer_reglages({"vocal_mode": d["mode"]})
            for f in ("groq", "openai"):
                if d.get(f"cle_{f}") is not None:
                    transcription.enregistrer_cle(f, d[f"cle_{f}"])
            return self._json({"ok": True, "vocal": transcription.etat()})
        if chemin == "/api/maj/verifier":
            try:
                return self._json({"ok": True, **mise_a_jour.verifier()})
            except Exception as e:
                return self._json({"ok": False, "erreur": f"Impossible de joindre GitHub : {e}"})
        if chemin == "/api/maj/installer":
            sha = d.get("sha", "")
            if not sha:
                return self._json({"ok": False, "erreur": "Version manquante."})
            erreur_maj = []
            threading.Thread(target=lambda: erreur_maj.append(installer_mise_a_jour(sha, origine="interface")), daemon=True).start()
            time.sleep(0.5)
            return self._json({"ok": not erreur_maj, "erreur": erreur_maj[0] if erreur_maj else ""})
        if chemin == "/api/telegram/code":
            if not bot.jeton:
                return self._json({"ok": False, "erreur": "Enregistre d'abord le jeton du bot."})
            return self._json({"ok": True, "appairage": bot.nouveau_code()})
        if chemin == "/api/telegram/dissocier":
            bot.dissocier()
            return self._json({"ok": True, "telegram": bot.etat()})
        if chemin == "/api/telegram/supprimer":
            bot.arreter()
            bot.dissocier()
            telegram_bot.effacer_jeton()
            bot.jeton = ""
            bot.info_bot = {}
            return self._json({"ok": True, "telegram": bot.etat()})
        if chemin == "/api/telegram/test":
            m = bot.envoyer("👋 Test depuis ton PC : le téléphone est bien relié à l'Agent Idéal.")
            return self._json({"ok": bool(m), "erreur": "" if m else (bot.erreur or "Envoi impossible.")})
        if chemin == "/api/choisir_dossier":
            return self._json({"chemin": choisir_dossier()})
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
    apres_maj = "--apres-maj" in sys.argv
    if apres_maj:
        # l'ancienne version est en train de s'arrêter : on attend que son port se libère
        for _ in range(40):
            with socket.socket() as s_:
                try:
                    s_.bind(("127.0.0.1", PORT_PREFERE))
                    break
                except OSError:
                    time.sleep(0.5)
    deja = None if apres_maj else _deja_lance()
    if deja:
        navigateur.ouvrir(deja)
        return
    global planificateur
    planificateur = routines.Planificateur(bus)
    module_agent.PLANIFICATEUR = planificateur
    global bot
    bot = telegram_bot.BotTelegram(bus, agent, planificateur, repondre_confirmation, installer_mise_a_jour)
    signal = mise_a_jour.lire_signal()
    if signal:
        bot.message_au_demarrage = (f"✅ <b>Agent mis à jour</b> (version {signal.get('version', '?')}) et redémarré. "
                                    "Il est prêt.")
    bot.demarrer()
    port = _port_libre()
    serveur = ThreadingHTTPServer(("127.0.0.1", port), Gestionnaire)
    serveur.daemon_threads = True
    adresse = f"http://127.0.0.1:{port}/"
    print(f"Agent Idéal démarré : {adresse}  (ferme cette fenêtre pour l'arrêter)")
    config.journal(f"Démarrage sur {adresse}")
    if "--sans-navigateur" not in sys.argv:
        threading.Timer(0.8, lambda: navigateur.ouvrir(adresse)).start()
    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
