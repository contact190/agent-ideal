"""Bot Telegram : suivre et commander l'agent depuis le téléphone.

- Le PC va chercher lui-même les messages chez Telegram (aucun port ouvert sur le PC).
- Le bot n'obéit qu'au compte Telegram appairé (code à 6 chiffres affiché dans l'interface).
- Il relaie : réponses de l'agent, demandes de validation (boutons Valider / Refuser),
  fins de tâches automatiques, erreurs. Il reçoit : ordres écrits, fichiers et photos, commandes.
- Tout se passe en arrière-plan : sans Internet, l'agent démarre quand même et le bot réessaie.
"""

import base64
import datetime
import html
import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.request
import uuid

import config

BASE = os.environ.get("AGENT_TELEGRAM_API", "https://api.telegram.org")   # modifiable pour les tests
API = BASE + "/bot{jeton}/{methode}"
LIMITE = 3900

COMMANDES = [
    {"command": "ecran", "description": "Capture de l'écran du PC"},
    {"command": "taches", "description": "Tâches automatiques"},
    {"command": "etat", "description": "Ce que fait l'agent"},
    {"command": "stop", "description": "Arrêter le travail en cours"},
    {"command": "nouvelle", "description": "Nouvelle conversation"},
    {"command": "aide", "description": "Aide"},
]


# ================================================================ jeton (coffre-fort Windows)

def lire_jeton() -> str:
    try:
        import keyring
        j = keyring.get_password(config.NOM_APP, "telegram")
        if j:
            return j
    except Exception:
        pass
    f = config.DOSSIER_DONNEES / ".telegram"
    return f.read_text(encoding="utf-8").strip() if f.exists() else ""


def enregistrer_jeton(jeton: str):
    try:
        import keyring
        keyring.set_password(config.NOM_APP, "telegram", jeton)
        return
    except Exception:
        pass
    (config.DOSSIER_DONNEES / ".telegram").write_text(jeton, encoding="utf-8")


def effacer_jeton():
    try:
        import keyring
        keyring.delete_password(config.NOM_APP, "telegram")
    except Exception:
        pass
    f = config.DOSSIER_DONNEES / ".telegram"
    if f.exists():
        f.unlink()


# ================================================================ appels HTTP

class ErreurTelegram(Exception):
    pass


def appel(jeton, methode, donnees=None, fichier=None, delai=40):
    """Appel à l'API Telegram. fichier = (champ, nom, octets, type_mime) pour sendPhoto/sendDocument."""
    url = API.format(jeton=jeton, methode=methode)
    if fichier:
        limite = "----agentideal" + uuid.uuid4().hex
        corps = b""
        for k, v in (donnees or {}).items():
            corps += (f"--{limite}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n"
                      f"{v if isinstance(v, str) else json.dumps(v)}\r\n").encode("utf-8")
        champ, nom, octets, mime = fichier
        corps += (f"--{limite}\r\nContent-Disposition: form-data; name=\"{champ}\"; filename=\"{nom}\"\r\n"
                  f"Content-Type: {mime}\r\n\r\n").encode("utf-8") + octets + f"\r\n--{limite}--\r\n".encode()
        req = urllib.request.Request(url, data=corps, headers={"Content-Type": f"multipart/form-data; boundary={limite}"})
    else:
        req = urllib.request.Request(url, data=json.dumps(donnees or {}).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=delai) as r:
            rep = json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            rep = json.loads(e.read())
        except Exception:
            raise ErreurTelegram(f"HTTP {e.code}")
    if not rep.get("ok"):
        raise ErreurTelegram(rep.get("description", "erreur Telegram"))
    return rep.get("result")


def telecharger(jeton, file_id) -> bytes:
    info = appel(jeton, "getFile", {"file_id": file_id})
    with urllib.request.urlopen(f"{BASE}/file/bot{jeton}/{info['file_path']}", timeout=120) as r:
        return r.read()


def verifier_jeton(jeton: str) -> dict:
    return appel(jeton, "getMe", delai=20)


# ================================================================ mise en forme

def en_html(texte: str) -> str:
    """Markdown simple de l'agent -> HTML Telegram."""
    t = html.escape(texte, quote=False)
    t = re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", t)
    t = re.sub(r"^#{1,4}\s+(.*)$", r"<b>\1</b>", t, flags=re.M)
    t = re.sub(r"^\s*[-*]\s+", "• ", t, flags=re.M)
    return t


def decouper(texte: str, n=LIMITE):
    morceaux = []
    while len(texte) > n:
        coupe = texte.rfind("\n", 0, n)
        coupe = coupe if coupe > n // 2 else n
        morceaux.append(texte[:coupe])
        texte = texte[coupe:].lstrip("\n")
    morceaux.append(texte)
    return morceaux


AIDE = (
    "🤖 <b>Agent Idéal</b> — écris-moi simplement ce que tu veux que je fasse sur ton PC.\n\n"
    "Exemples :\n• Fais le devis du client Benali et envoie-le-moi en PDF\n"
    "• Quels sont mes rendez-vous demain ?\n• Résume mes e-mails non lus\n\n"
    "Tu peux aussi m'envoyer une photo ou un fichier : je le range sur le PC et je m'en sers.\n\n"
    "Commandes :\n/ecran — capture de l'écran du PC\n/taches — tâches automatiques\n"
    "/etat — ce que fait l'agent\n/stop — arrêter le travail en cours\n/nouvelle — nouvelle conversation\n/aide — ce message"
)


# ================================================================ le bot

class BotTelegram:
    def __init__(self, bus, agent, planificateur, repondre_confirmation):
        self.bus = bus
        self.agent = agent
        self.planificateur = planificateur
        self.repondre_confirmation = repondre_confirmation   # fonction(id, accepte) -> bool
        self.jeton = ""
        self.info_bot = {}
        self.code = None
        self.code_expire = 0
        self.erreur = ""
        self._suivi = False             # relayer les réponses de l'agent (la demande vient du téléphone)
        self._msg_progression = None    # message « travail en cours » modifié au fil des actions
        self._derniere_maj = 0
        self._confs = {}                # id confirmation -> (message_id, texte)
        self._offset = None
        self._arret = threading.Event()
        self._fils = []

    # ---------------- état / réglages

    @property
    def chat_id(self):
        return config.charger_reglages().get("telegram_chat_id")

    def etat(self):
        r = config.charger_reglages()
        return {"configure": bool(self.jeton), "bot": self.info_bot.get("username", ""),
                "appaire": bool(r.get("telegram_chat_id")), "nom": r.get("telegram_nom", ""),
                "actif": any(f.is_alive() for f in self._fils), "erreur": self.erreur}

    def nouveau_code(self):
        if not self.info_bot and self.jeton:
            try:
                self.info_bot = verifier_jeton(self.jeton)
            except Exception:
                pass
        self.code = f"{secrets.randbelow(10**6):06d}"
        self.code_expire = time.time() + 15 * 60
        lien = f"https://t.me/{self.info_bot.get('username', '')}?start={self.code}"
        qr = ""
        try:
            import io
            import qrcode
            img = qrcode.make(lien, box_size=6, border=2)
            t = io.BytesIO()
            img.save(t, format="PNG")
            qr = "data:image/png;base64," + base64.b64encode(t.getvalue()).decode()
        except Exception:
            pass
        return {"code": self.code, "lien": lien, "qr": qr, "bot": self.info_bot.get("username", "")}

    def dissocier(self):
        config.enregistrer_reglages({"telegram_chat_id": None, "telegram_nom": ""})

    # ---------------- démarrage / arrêt (ne bloque jamais)

    def demarrer(self):
        self.arreter()
        self.jeton = lire_jeton()
        self.erreur = ""
        self.info_bot = {}
        self._offset = None
        if not self.jeton:
            return False
        self._arret = threading.Event()
        arret = self._arret
        self._fils = [threading.Thread(target=self._recevoir, args=(arret,), daemon=True),
                      threading.Thread(target=self._relayer, args=(arret,), daemon=True)]
        for f in self._fils:
            f.start()
        return True

    def arreter(self):
        self._arret.set()

    def _preparer(self):
        self.info_bot = verifier_jeton(self.jeton)
        try:
            appel(self.jeton, "setMyCommands", {"commands": COMMANDES})
        except Exception:
            pass

    # ---------------- envoi

    def envoyer(self, texte, html_ok=True, boutons=None, chat_id=None):
        chat = chat_id or self.chat_id
        if not (self.jeton and chat):
            return None
        dernier = None
        morceaux = decouper(texte)
        for i, m in enumerate(morceaux):
            donnees = {"chat_id": chat, "text": m, "disable_web_page_preview": True}
            if html_ok:
                donnees["parse_mode"] = "HTML"
            if boutons and i == len(morceaux) - 1:
                donnees["reply_markup"] = {"inline_keyboard": boutons}
            try:
                dernier = appel(self.jeton, "sendMessage", donnees)
            except ErreurTelegram as e:
                if html_ok and "parse" in str(e).lower():       # HTML refusé : on renvoie en texte brut
                    donnees.pop("parse_mode")
                    donnees["text"] = re.sub(r"<[^>]+>", "", html.unescape(m))
                    try:
                        dernier = appel(self.jeton, "sendMessage", donnees)
                    except Exception as e2:
                        config.journal(f"Telegram envoi : {e2}")
                else:
                    config.journal(f"Telegram envoi : {e}")
            except Exception as e:
                config.journal(f"Telegram envoi : {e}")
        return dernier

    def _modifier(self, message_id, texte, boutons=None):
        donnees = {"chat_id": self.chat_id, "message_id": message_id, "text": texte[:LIMITE], "parse_mode": "HTML",
                   "disable_web_page_preview": True}
        if boutons is not None:
            donnees["reply_markup"] = {"inline_keyboard": boutons}
        try:
            appel(self.jeton, "editMessageText", donnees)
        except Exception:
            pass

    def envoyer_capture(self):
        import outils_ecran
        b64, _, _ = outils_ecran.capture()
        appel(self.jeton, "sendPhoto", {"chat_id": str(self.chat_id), "caption": f"🖥️ Écran du PC — {datetime.datetime.now():%H:%M}"},
              fichier=("photo", "ecran.png", base64.b64decode(b64), "image/png"), delai=120)

    # ---------------- relais des événements de l'agent vers le téléphone

    def _relayer(self, arret):
        q = self.bus.abonner()
        try:
            while not arret.is_set():
                try:
                    e = q.get(timeout=1)
                except Exception:
                    continue
                if not self.chat_id:
                    continue
                try:
                    self._traiter_evenement(e)
                except Exception as ex:
                    config.journal(f"Telegram relais : {type(ex).__name__} : {ex}")
        finally:
            self.bus.desabonner(q)

    def _progression(self, texte):
        if not self._suivi:
            return
        maintenant = time.time()
        if self._msg_progression is None:
            m = self.envoyer(f"⏳ {html.escape(texte)}")
            self._msg_progression = m["message_id"] if m else None
            self._derniere_maj = maintenant
        elif maintenant - self._derniere_maj > 3:
            self._modifier(self._msg_progression, f"⏳ {html.escape(texte)}")
            self._derniere_maj = maintenant

    def _fin_progression(self):
        if self._msg_progression:
            try:
                appel(self.jeton, "deleteMessage", {"chat_id": self.chat_id, "message_id": self._msg_progression})
            except Exception:
                pass
        self._msg_progression = None

    def _traiter_evenement(self, e):
        t = e.get("type")
        r = config.charger_reglages()
        if t == "action":
            self._progression(f"{e.get('libelle', '')} {('· ' + e['detail']) if e.get('detail') else ''}")
        elif t == "texte" and self._suivi:
            self._fin_progression()
            self.envoyer(en_html(e["texte"]))
        elif t == "erreur" and self._suivi:
            self._fin_progression()
            self.envoyer("❌ " + html.escape(e["texte"]))
        elif t == "info" and self._suivi:
            self.envoyer("ℹ️ " + html.escape(e["texte"]))
        elif t == "fin" and self._suivi:
            self._fin_progression()
            self._suivi = False
        elif t == "confirmation":
            texte = (f"🔔 <b>{html.escape(e['titre'])}</b>\n\n{html.escape(e['details'][:3000])}\n\n"
                     "<i>L'agent attend ta réponse.</i>")
            m = self.envoyer(texte, boutons=[[{"text": "✅ Valider", "callback_data": f"c:{e['id']}:1"},
                                              {"text": "❌ Refuser", "callback_data": f"c:{e['id']}:0"}]])
            if m:
                self._confs[e["id"]] = (m["message_id"], texte)
        elif t == "confirmation_reponse":
            if e["id"] in self._confs:
                mid, texte = self._confs.pop(e["id"])
                self._modifier(mid, texte.replace("<i>L'agent attend ta réponse.</i>",
                                                  "<b>✅ Validé</b>" if e["accepte"] else "<b>❌ Refusé</b>"), boutons=[])
        elif t == "routine_debut" and r.get("telegram_notifier_debut"):
            self.envoyer(f"🕗 Tâche « {html.escape(e['routine'])} » démarrée")
        elif t == "routine_fin" and r.get("telegram_notifier_taches", True):
            icone = "✅" if e["statut"] == "réussie" else "⚠️"
            self.envoyer(f"{icone} <b>Tâche « {html.escape(e['routine'])} » : {html.escape(e['statut'])}</b>\n\n{en_html(e.get('resultat', ''))}")
        elif t == "routine_erreur" and r.get("telegram_notifier_taches", True):
            self.envoyer(f"❌ Tâche « {html.escape(e.get('routine', ''))} » : {html.escape(e['texte'])}")
        elif t == "google" and (e.get("etat") or {}).get("alerte"):
            self.envoyer("🔑 " + html.escape(e["etat"].get("message", "La connexion Google demande ton attention.")))

    # ---------------- réception des messages du téléphone

    def _recevoir(self, arret):
        attente = 2
        while not arret.is_set():
            try:
                if not self.info_bot:
                    self._preparer()
                params = {"timeout": 30, "allowed_updates": ["message", "callback_query"]}
                if self._offset is not None:
                    params["offset"] = self._offset
                for u in appel(self.jeton, "getUpdates", params, delai=45) or []:
                    if arret.is_set():
                        return
                    self._offset = u["update_id"] + 1
                    try:
                        self._traiter_update(u)
                    except Exception as ex:
                        config.journal(f"Telegram message : {type(ex).__name__} : {ex}")
                self.erreur = ""
                attente = 2
            except ErreurTelegram as ex:
                self.erreur = str(ex)
                if "Unauthorized" in str(ex) or "Not Found" in str(ex):
                    self.erreur = "Jeton du bot refusé par Telegram : recrée-le avec @BotFather."
                    config.journal("Telegram : " + self.erreur)
                    return
                if "Conflict" in str(ex):
                    self.erreur = "Ce bot est déjà utilisé par un autre ordinateur."
                arret.wait(attente)
                attente = min(attente * 2, 60)
            except Exception as ex:          # pas d'Internet, etc.
                self.erreur = f"Connexion à Telegram impossible ({type(ex).__name__}), nouvel essai automatique."
                arret.wait(attente)
                attente = min(attente * 2, 60)

    def _traiter_update(self, u):
        if "callback_query" in u:
            cq = u["callback_query"]
            if str(cq["from"]["id"]) != str(self.chat_id) and str(cq["message"]["chat"]["id"]) != str(self.chat_id):
                return
            donnees = cq.get("data", "")
            reponse = ""
            if donnees.startswith("c:"):
                _, id_conf, ok = donnees.split(":")
                reponse = "C'est noté." if self.repondre_confirmation(id_conf, ok == "1") else "Cette demande n'est plus en attente."
            elif donnees.startswith("l:"):
                self.planificateur.lancer_maintenant(donnees[2:])
                reponse = "Tâche lancée."
            try:
                appel(self.jeton, "answerCallbackQuery", {"callback_query_id": cq["id"], "text": reponse})
            except Exception:
                pass
            return

        m = u.get("message")
        if not m:
            return
        chat = m["chat"]["id"]
        texte = (m.get("text") or m.get("caption") or "").strip()

        # appairage
        if not self.chat_id:
            code = texte.replace("/start", "").strip()
            if self.code and time.time() < self.code_expire and code == self.code:
                nom = " ".join(x for x in (m["from"].get("first_name"), m["from"].get("last_name")) if x)
                config.enregistrer_reglages({"telegram_chat_id": chat, "telegram_nom": nom})
                self.code = None
                self.envoyer(f"✅ Appairé ! Bonjour {html.escape(nom)}.\n\n" + AIDE, chat_id=chat)
                self.bus.publier({"type": "telegram", "etat": self.etat()})
            else:
                self.envoyer("Pour relier ce téléphone, ouvre les Réglages de l'Agent Idéal sur ton PC "
                             "(section Téléphone) et scanne le QR code ou envoie le code affiché.", html_ok=False, chat_id=chat)
            return
        if str(chat) != str(self.chat_id):
            self.envoyer("⛔ Ce bot est privé.", html_ok=False, chat_id=chat)
            return

        # fichiers et photos reçus
        piece = None
        if m.get("document"):
            d = m["document"]
            piece = (d["file_id"], d.get("file_name") or f"fichier_{d.get('file_unique_id', 'x')}")
        elif m.get("photo"):
            p = m["photo"][-1]
            piece = (p["file_id"], f"photo_{datetime.datetime.now():%Y%m%d_%H%M%S}.jpg")
        elif m.get("voice") or m.get("audio"):
            self.envoyer("🎙️ Je ne comprends pas encore les messages vocaux. Écris ta demande "
                         "(astuce : le micro du clavier du téléphone transforme ta voix en texte).", html_ok=False)
            return
        if piece:
            chemin = self._enregistrer_piece(*piece)
            if not chemin:
                return
            texte = (texte + "\n\n" if texte else "Je t'envoie ce fichier depuis mon téléphone. ") + f"[Fichier reçu et enregistré : {chemin}]"

        if texte.startswith("/"):
            self._commande(texte.split()[0].split("@")[0].lower())
            return
        if not texte:
            return
        if self.agent.en_cours:
            self.envoyer("⏳ L'agent travaille déjà sur une autre demande. Attends la fin ou envoie /stop.", html_ok=False)
            return
        if not config.lire_cle_api():
            self.envoyer("La clé API Claude n'est pas configurée sur le PC.", html_ok=False)
            return
        self._suivi = True
        self._msg_progression = None
        self.agent.envoyer(texte)

    def _enregistrer_piece(self, file_id, nom):
        dossiers = config.charger_reglages().get("dossiers_autorises") or []
        if not dossiers:
            self.envoyer("Aucun dossier autorisé sur le PC : ajoute-en un dans les Réglages.", html_ok=False)
            return None
        from pathlib import Path
        cible = Path(dossiers[0]) / "Reçus Telegram"
        cible.mkdir(parents=True, exist_ok=True)
        nom = re.sub(r'[\\/:*?"<>|]', "_", nom)
        chemin = cible / nom
        if chemin.exists():
            chemin = cible / f"{chemin.stem}_{datetime.datetime.now():%H%M%S}{chemin.suffix}"
        try:
            chemin.write_bytes(telecharger(self.jeton, file_id))
        except Exception as e:
            self.envoyer(f"Impossible de récupérer le fichier : {e}", html_ok=False)
            return None
        return str(chemin)

    def _commande(self, cmd):
        import routines
        if cmd in ("/aide", "/help", "/start"):
            self.envoyer(AIDE)
        elif cmd == "/stop":
            self.agent.arreter()
            self.planificateur.arreter_en_cours()
            self.envoyer("⏹️ Arrêt demandé.", html_ok=False)
        elif cmd == "/nouvelle":
            ok = self.agent.nouvelle_conversation()
            self.envoyer("🆕 Nouvelle conversation." if ok else "Impossible pendant que l'agent travaille.", html_ok=False)
        elif cmd == "/ecran":
            try:
                self.envoyer_capture()
            except Exception as e:
                self.envoyer(f"Capture impossible : {e}", html_ok=False)
        elif cmd == "/etat":
            pl = self.planificateur.etat()
            r_en_cours = routines.obtenir(pl["en_cours"]) if pl.get("en_cours") else None
            lignes = [f"💬 Conversation : {'en cours de travail' if self.agent.en_cours else 'au repos'}",
                      f"🕗 Tâche automatique : {('« ' + r_en_cours['nom'] + ' » en cours') if r_en_cours else 'aucune en cours'}"]
            try:
                import outils_google
                g = outils_google.etat()
                lignes.append(f"🔑 Google : {g.get('email') or 'connecté'}" if g.get("connecte") else f"🔑 Google : {g.get('message')}")
            except Exception:
                pass
            self.envoyer("\n".join(html.escape(x) for x in lignes))
        elif cmd == "/taches":
            rs = routines.lister()
            if not rs:
                self.envoyer("Aucune tâche automatique. Demande-moi par exemple : « Chaque matin à 8 h, envoie-moi un résumé de mes e-mails ».", html_ok=False)
                return
            lignes, boutons = [], []
            for r in rs:
                p = routines.prochaine_execution(r)
                etat = "⏸️" if r.get("actif") is False else "🟢"
                lignes.append(f"{etat} <b>{html.escape(r['nom'])}</b> — {html.escape(routines.decrire_horaire(r))}"
                              + (f"\n   prochaine : {p:%d/%m %H:%M}" if p and r.get("actif", True) else "")
                              + (f"\n   dernière : {html.escape(r.get('dernier_statut', ''))}" if r.get("dernier_statut") else ""))
                boutons.append([{"text": f"▶ Lancer « {r['nom'][:40]} »", "callback_data": f"l:{r['id']}"}])
            self.envoyer("\n\n".join(lignes), boutons=boutons)
        else:
            self.envoyer("Commande inconnue. /aide pour la liste.", html_ok=False)
