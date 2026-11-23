"""Outils Google : Drive, Sheets, Docs, Gmail, Agenda.

Le fichier `identifiant_google.json` (dans le dossier du programme) identifie L'APPLICATION.
Chaque utilisateur se connecte avec son propre compte : ses autorisations sont enregistrées
dans son dossier de réglages (google_token.json), jamais partagées.
"""

import base64
import datetime
import json
import mimetypes
from email.message import EmailMessage
from pathlib import Path

import config

FICHIER_IDENTIFIANT = config.DOSSIER_PROGRAMME / "identifiant_google.json"

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]

_services = {}
_creds = None


def config_application():
    """identifiant_google.json (s'il est présent, pour utiliser sa propre application Google) sinon l'identifiant intégré."""
    if FICHIER_IDENTIFIANT.exists():
        return json.loads(FICHIER_IDENTIFIANT.read_text(encoding="utf-8"))
    try:
        import base64
        from identifiant_google_app import IDENTIFIANT
        return json.loads(base64.b64decode(IDENTIFIANT))
    except Exception:
        return None


class GoogleNonConnecte(Exception):
    pass


# ---------------------------------------------------------------- connexion

def _lire_token():
    if not config.FICHIER_TOKEN_GOOGLE.exists():
        return None
    return json.loads(config.FICHIER_TOKEN_GOOGLE.read_text(encoding="utf-8"))


def connecter() -> str:
    """Ouvre le navigateur sur la page de connexion Google et attend l'accord de l'utilisateur."""
    from google_auth_oauthlib.flow import InstalledAppFlow
    global _creds
    flow = InstalledAppFlow.from_client_config(config_application(), SCOPES)
    creds = flow.run_local_server(
        port=0, prompt="consent", open_browser=True,
        success_message="Connexion réussie ! Tu peux fermer cet onglet et revenir à l'Agent Idéal.")
    email = ""
    try:
        from googleapiclient.discovery import build
        email = build("oauth2", "v2", credentials=creds, cache_discovery=False).userinfo().get().execute().get("email", "")
    except Exception:
        pass
    donnees = json.loads(creds.to_json())
    donnees["_email"] = email
    donnees["_connecte_le"] = datetime.datetime.now().isoformat(timespec="seconds")
    config.FICHIER_TOKEN_GOOGLE.write_text(json.dumps(donnees), encoding="utf-8")
    _creds = None
    _services.clear()
    config.journal(f"Google connecté : {email}")
    return email


def deconnecter():
    global _creds
    if config.FICHIER_TOKEN_GOOGLE.exists():
        config.FICHIER_TOKEN_GOOGLE.unlink()
    _creds = None
    _services.clear()


def identifiants():
    global _creds
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    if _creds and _creds.valid:
        return _creds
    donnees = _lire_token()
    if not donnees:
        raise GoogleNonConnecte("Google n'est pas connecté. L'utilisateur doit cliquer sur « Connecter Google » dans les Réglages.")
    creds = Credentials.from_authorized_user_info(donnees, SCOPES)
    if not creds.valid:
        try:
            creds.refresh(Request())
        except Exception as e:
            raise GoogleNonConnecte(
                "La connexion Google a expiré. L'utilisateur doit cliquer sur « Reconnecter Google » "
                f"(bandeau en haut de l'écran). Détail : {e}")
        nouv = json.loads(creds.to_json())
        nouv["_email"] = donnees.get("_email", "")
        nouv["_connecte_le"] = donnees.get("_connecte_le", "")
        config.FICHIER_TOKEN_GOOGLE.write_text(json.dumps(nouv), encoding="utf-8")
    _creds = creds
    return creds


def etat() -> dict:
    """État de la connexion Google pour l'interface, avec le rappel de reconnexion."""
    reglages = config.charger_reglages()
    donnees = _lire_token()
    if not config_application():
        return {"connecte": False, "message": "Identifiant de l'application Google manquant."}
    if not donnees:
        return {"connecte": False, "message": "Non connecté."}
    age = None
    if donnees.get("_connecte_le"):
        age = (datetime.datetime.now() - datetime.datetime.fromisoformat(donnees["_connecte_le"])).total_seconds() / 86400
    resultat = {"connecte": True, "email": donnees.get("_email", ""), "age_jours": round(age, 1) if age is not None else None,
                "alerte": False, "message": ""}
    try:
        identifiants()
    except GoogleNonConnecte:
        resultat.update(connecte=False, alerte=True, message="La connexion Google a expiré : clique sur « Reconnecter Google ».")
        return resultat
    if reglages.get("google_mode_test") and age is not None:
        restant = 7 - age
        if age >= reglages.get("rappel_google_jours", 6):
            resultat.update(alerte=True, message=(
                f"La connexion Google expire dans {max(restant, 0) * 24:.0f} h environ. "
                "Clique sur « Reconnecter Google » maintenant pour ne pas être coupé."))
        resultat["expire_dans_jours"] = round(max(restant, 0), 1)
    return resultat


def service(nom, version):
    from googleapiclient.discovery import build
    cle = (nom, version)
    if cle not in _services:
        _services[cle] = build(nom, version, credentials=identifiants(), cache_discovery=False)
    return _services[cle]


def _lien(f):
    return f.get("webViewLink", "")


# ---------------------------------------------------------------- Drive

TYPES = {"application/vnd.google-apps.folder": "dossier", "application/vnd.google-apps.spreadsheet": "Google Sheet",
         "application/vnd.google-apps.document": "Google Doc", "application/vnd.google-apps.presentation": "Google Slides"}


def drive_rechercher(texte: str = "", dans_dossier: str = "", type_fichier: str = "", max_resultats: int = 30) -> str:
    q = ["trashed = false"]
    if texte:
        t = texte.replace("'", "\\'")
        q.append(f"(name contains '{t}' or fullText contains '{t}')")
    if dans_dossier:
        q.append(f"'{dans_dossier}' in parents")
    inv = {v.lower(): k for k, v in TYPES.items()}
    if type_fichier and type_fichier.lower() in inv:
        q.append(f"mimeType = '{inv[type_fichier.lower()]}'")
    r = service("drive", "v3").files().list(
        q=" and ".join(q), pageSize=min(max_resultats, 100), orderBy="modifiedTime desc",
        fields="files(id,name,mimeType,modifiedTime,webViewLink,parents)",
        supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
    fichiers = r.get("files", [])
    if not fichiers:
        return "Aucun résultat dans Google Drive."
    return "\n".join(f"- {f['name']} [{TYPES.get(f['mimeType'], f['mimeType'])}] id={f['id']} modifié {f['modifiedTime'][:10]} {_lien(f)}"
                     for f in fichiers)


def drive_creer_dossier(nom: str, parent_id: str = "") -> str:
    corps = {"name": nom, "mimeType": "application/vnd.google-apps.folder"}
    if parent_id:
        corps["parents"] = [parent_id]
    f = service("drive", "v3").files().create(body=corps, fields="id,webViewLink", supportsAllDrives=True).execute()
    return f"Dossier Drive « {nom} » créé : id={f['id']} {f['webViewLink']}"


def drive_televerser(chemin_local: str, dossier_id: str = "", convertir: bool = False) -> str:
    from googleapiclient.http import MediaFileUpload
    import outils_fichiers
    p = outils_fichiers.verifier_chemin(chemin_local)
    mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    corps = {"name": p.name}
    if convertir:
        conv = {".xlsx": "application/vnd.google-apps.spreadsheet", ".csv": "application/vnd.google-apps.spreadsheet",
                ".docx": "application/vnd.google-apps.document", ".txt": "application/vnd.google-apps.document"}
        if p.suffix.lower() in conv:
            corps["mimeType"] = conv[p.suffix.lower()]
            corps["name"] = p.stem
    if dossier_id:
        corps["parents"] = [dossier_id]
    f = service("drive", "v3").files().create(body=corps, media_body=MediaFileUpload(str(p), mimetype=mime, resumable=True),
                                              fields="id,webViewLink", supportsAllDrives=True).execute()
    return f"Envoyé sur Drive : {corps['name']} id={f['id']} {f['webViewLink']}"


def drive_telecharger(fichier_id: str, dossier_local: str, format_export: str = "") -> str:
    import io
    from googleapiclient.http import MediaIoBaseDownload
    import outils_fichiers
    d = outils_fichiers.verifier_chemin(dossier_local)
    d.mkdir(parents=True, exist_ok=True)
    drv = service("drive", "v3")
    meta = drv.files().get(fileId=fichier_id, fields="name,mimeType", supportsAllDrives=True).execute()
    exports = {"application/vnd.google-apps.spreadsheet": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
               "application/vnd.google-apps.document": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
               "application/vnd.google-apps.presentation": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx")}
    if meta["mimeType"] in exports:
        mime, ext = exports[meta["mimeType"]]
        if format_export.lower() == "pdf":
            mime, ext = "application/pdf", ".pdf"
        requete = drv.files().export_media(fileId=fichier_id, mimeType=mime)
        nom = meta["name"] + ext
    else:
        requete = drv.files().get_media(fileId=fichier_id, supportsAllDrives=True)
        nom = meta["name"]
    cible = d / nom
    with io.FileIO(cible, "wb") as fh:
        dl = MediaIoBaseDownload(fh, requete)
        fini = False
        while not fini:
            _, fini = dl.next_chunk()
    return f"Téléchargé : {cible}"


def drive_partager(fichier_id: str, email: str, role: str = "reader") -> str:
    service("drive", "v3").permissions().create(
        fileId=fichier_id, body={"type": "user", "role": role, "emailAddress": email},
        sendNotificationEmail=True, supportsAllDrives=True).execute()
    return f"Partagé avec {email} ({role})."


def drive_corbeille(fichier_id: str) -> str:
    service("drive", "v3").files().update(fileId=fichier_id, body={"trashed": True}, supportsAllDrives=True).execute()
    return "Fichier mis à la corbeille Google Drive (récupérable 30 jours)."


# ---------------------------------------------------------------- Sheets

def sheets_creer(titre: str, lignes: list = None, dossier_id: str = "") -> str:
    corps = {"name": titre, "mimeType": "application/vnd.google-apps.spreadsheet"}
    if dossier_id:
        corps["parents"] = [dossier_id]
    f = service("drive", "v3").files().create(body=corps, fields="id,webViewLink", supportsAllDrives=True).execute()
    if lignes:
        service("sheets", "v4").spreadsheets().values().update(
            spreadsheetId=f["id"], range="A1", valueInputOption="USER_ENTERED", body={"values": lignes}).execute()
    return f"Google Sheet « {titre} » créé : id={f['id']} {f['webViewLink']}"


def sheets_lire(classeur_id: str, plage: str = "") -> str:
    sh = service("sheets", "v4").spreadsheets()
    meta = sh.get(spreadsheetId=classeur_id, fields="properties.title,sheets.properties.title").execute()
    onglets = [s["properties"]["title"] for s in meta["sheets"]]
    plage = plage or onglets[0]
    v = sh.values().get(spreadsheetId=classeur_id, range=plage).execute().get("values", [])
    lignes = "\n".join(" | ".join(map(str, l)) for l in v[:500])
    return f"Classeur « {meta['properties']['title']} » – onglets : {', '.join(onglets)}\nPlage {plage} :\n{lignes or '(vide)'}"


def sheets_ecrire(classeur_id: str, plage: str, valeurs: list, ajouter_a_la_suite: bool = False) -> str:
    vals = service("sheets", "v4").spreadsheets().values()
    corps = {"values": valeurs}
    if ajouter_a_la_suite:
        vals.append(spreadsheetId=classeur_id, range=plage, valueInputOption="USER_ENTERED",
                    insertDataOption="INSERT_ROWS", body=corps).execute()
        return f"{len(valeurs)} ligne(s) ajoutée(s)."
    vals.update(spreadsheetId=classeur_id, range=plage, valueInputOption="USER_ENTERED", body=corps).execute()
    return f"Plage {plage} mise à jour."


# ---------------------------------------------------------------- Docs

def docs_creer(titre: str, texte: str = "", dossier_id: str = "") -> str:
    corps = {"name": titre, "mimeType": "application/vnd.google-apps.document"}
    if dossier_id:
        corps["parents"] = [dossier_id]
    f = service("drive", "v3").files().create(body=corps, fields="id,webViewLink", supportsAllDrives=True).execute()
    if texte:
        docs_ajouter(f["id"], texte)
    return f"Google Doc « {titre} » créé : id={f['id']} {f['webViewLink']}"


def docs_ajouter(document_id: str, texte: str) -> str:
    doc = service("docs", "v1").documents().get(documentId=document_id).execute()
    fin = doc["body"]["content"][-1]["endIndex"] - 1
    service("docs", "v1").documents().batchUpdate(documentId=document_id, body={"requests": [
        {"insertText": {"location": {"index": max(fin, 1)}, "text": texte}}]}).execute()
    return "Texte ajouté au document."


def docs_lire(document_id: str) -> str:
    doc = service("docs", "v1").documents().get(documentId=document_id).execute()
    morceaux = []
    for el in doc["body"]["content"]:
        for pe in el.get("paragraph", {}).get("elements", []):
            morceaux.append(pe.get("textRun", {}).get("content", ""))
        if "table" in el:
            for row in el["table"]["tableRows"]:
                cellules = []
                for c in row["tableCells"]:
                    cellules.append("".join(pe.get("textRun", {}).get("content", "")
                                            for p in c["content"] for pe in p.get("paragraph", {}).get("elements", [])).strip())
                morceaux.append(" | ".join(cellules) + "\n")
    return f"« {doc['title']} »\n" + "".join(morceaux)[:60_000]


# ---------------------------------------------------------------- Gmail

def gmail_rechercher(requete: str = "", max_resultats: int = 15) -> str:
    g = service("gmail", "v1").users()
    r = g.messages().list(userId="me", q=requete, maxResults=min(max_resultats, 50)).execute()
    lignes = []
    for m in r.get("messages", []):
        meta = g.messages().get(userId="me", id=m["id"], format="metadata",
                                metadataHeaders=["From", "To", "Subject", "Date"]).execute()
        h = {x["name"]: x["value"] for x in meta["payload"].get("headers", [])}
        non_lu = " (non lu)" if "UNREAD" in meta.get("labelIds", []) else ""
        lignes.append(f"- id={m['id']}{non_lu} | {h.get('Date', '')} | De : {h.get('From', '')} | Objet : {h.get('Subject', '')}\n  {meta.get('snippet', '')}")
    return "\n".join(lignes) if lignes else "Aucun e-mail trouvé."


def _texte_partie(part):
    if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", "ignore")
    for p in part.get("parts", []) or []:
        t = _texte_partie(p)
        if t:
            return t
    if part.get("mimeType") == "text/html" and part.get("body", {}).get("data"):
        import re
        html = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", "ignore")
        return re.sub(r"<[^>]+>", " ", html)
    return ""


def _pieces(part, liste):
    if part.get("filename") and part.get("body", {}).get("attachmentId"):
        liste.append((part["filename"], part["body"]["attachmentId"]))
    for p in part.get("parts", []) or []:
        _pieces(p, liste)
    return liste


def gmail_lire(message_id: str) -> str:
    m = service("gmail", "v1").users().messages().get(userId="me", id=message_id, format="full").execute()
    h = {x["name"]: x["value"] for x in m["payload"].get("headers", [])}
    pj = _pieces(m["payload"], [])
    texte = _texte_partie(m["payload"]).strip()
    return (f"De : {h.get('From', '')}\nÀ : {h.get('To', '')}\nDate : {h.get('Date', '')}\nObjet : {h.get('Subject', '')}\n"
            f"Fil : {m.get('threadId')}\nPièces jointes : {', '.join(n for n, _ in pj) or 'aucune'}\n\n{texte[:30_000]}")


def gmail_enregistrer_piece_jointe(message_id: str, nom_fichier: str, dossier_local: str) -> str:
    import outils_fichiers
    m = service("gmail", "v1").users().messages().get(userId="me", id=message_id, format="full").execute()
    for nom, att_id in _pieces(m["payload"], []):
        if nom == nom_fichier:
            a = service("gmail", "v1").users().messages().attachments().get(userId="me", messageId=message_id, id=att_id).execute()
            d = outils_fichiers.verifier_chemin(dossier_local)
            d.mkdir(parents=True, exist_ok=True)
            (d / nom).write_bytes(base64.urlsafe_b64decode(a["data"]))
            return f"Pièce jointe enregistrée : {d / nom}"
    return "Pièce jointe introuvable."


def _construire(a, objet, corps, cc="", pieces_jointes=None, repondre_a=""):
    import outils_fichiers
    msg = EmailMessage()
    if a:
        msg["To"] = a
    if cc:
        msg["Cc"] = cc
    msg["Subject"] = objet
    msg.set_content(corps)
    thread_id = None
    if repondre_a:
        orig = service("gmail", "v1").users().messages().get(
            userId="me", id=repondre_a, format="metadata", metadataHeaders=["Message-ID", "Subject"]).execute()
        h = {x["name"]: x["value"] for x in orig["payload"].get("headers", [])}
        if h.get("Message-ID"):
            msg["In-Reply-To"] = h["Message-ID"]
            msg["References"] = h["Message-ID"]
        thread_id = orig.get("threadId")
    for chemin in pieces_jointes or []:
        p = outils_fichiers.verifier_chemin(chemin)
        mime = (mimetypes.guess_type(p.name)[0] or "application/octet-stream").split("/")
        msg.add_attachment(p.read_bytes(), maintype=mime[0], subtype=mime[1], filename=p.name)
    corps_api = {"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}
    if thread_id:
        corps_api["threadId"] = thread_id
    return corps_api


def gmail_brouillon(a: str, objet: str, corps: str, cc: str = "", pieces_jointes: list = None, repondre_a: str = "") -> str:
    d = service("gmail", "v1").users().drafts().create(
        userId="me", body={"message": _construire(a, objet, corps, cc, pieces_jointes, repondre_a)}).execute()
    return f"Brouillon créé (id={d['id']}). Il est dans les Brouillons Gmail, rien n'a été envoyé."


def gmail_envoyer(a: str, objet: str, corps: str, cc: str = "", pieces_jointes: list = None, repondre_a: str = "") -> str:
    m = service("gmail", "v1").users().messages().send(
        userId="me", body=_construire(a, objet, corps, cc, pieces_jointes, repondre_a)).execute()
    return f"E-mail envoyé à {a} (id={m['id']})."


def gmail_envoyer_brouillon(brouillon_id: str) -> str:
    m = service("gmail", "v1").users().drafts().send(userId="me", body={"id": brouillon_id}).execute()
    return f"Brouillon envoyé (id={m['id']})."


# ---------------------------------------------------------------- Agenda

def _fuseau():
    try:
        return service("calendar", "v3").settings().get(setting="timezone").execute()["value"]
    except Exception:
        return "Africa/Algiers"


def agenda_lister(debut: str, fin: str, recherche: str = "") -> str:
    tz = _fuseau()
    from zoneinfo import ZoneInfo
    z = ZoneInfo(tz)
    d = datetime.datetime.fromisoformat(debut)
    f = datetime.datetime.fromisoformat(fin)
    d = d if d.tzinfo else d.replace(tzinfo=z)
    f = f if f.tzinfo else f.replace(tzinfo=z)
    params = dict(calendarId="primary", timeMin=d.isoformat(), timeMax=f.isoformat(), singleEvents=True,
                  orderBy="startTime", maxResults=100)
    if recherche:
        params["q"] = recherche
    evs = service("calendar", "v3").events().list(**params).execute().get("items", [])
    if not evs:
        return "Aucun événement sur cette période."
    return "\n".join(f"- id={e['id']} | {e['start'].get('dateTime', e['start'].get('date'))} → {e['end'].get('dateTime', e['end'].get('date'))} | "
                     f"{e.get('summary', '(sans titre)')} | {e.get('location', '')}" for e in evs) + f"\n(fuseau : {tz})"


def agenda_creer(titre: str, debut: str, fin: str, lieu: str = "", description: str = "", invites: list = None) -> str:
    tz = _fuseau()
    corps = {"summary": titre, "location": lieu, "description": description,
             "start": {"dateTime": debut, "timeZone": tz}, "end": {"dateTime": fin, "timeZone": tz}}
    if invites:
        corps["attendees"] = [{"email": e} for e in invites]
    ev = service("calendar", "v3").events().insert(calendarId="primary", body=corps,
                                                   sendUpdates="all" if invites else "none").execute()
    return f"Événement créé : {titre} le {debut} (id={ev['id']}) {ev.get('htmlLink', '')}"


def agenda_modifier(evenement_id: str, titre: str = "", debut: str = "", fin: str = "", lieu: str = "", description: str = "") -> str:
    tz = _fuseau()
    corps = {}
    if titre:
        corps["summary"] = titre
    if lieu:
        corps["location"] = lieu
    if description:
        corps["description"] = description
    if debut:
        corps["start"] = {"dateTime": debut, "timeZone": tz}
    if fin:
        corps["end"] = {"dateTime": fin, "timeZone": tz}
    service("calendar", "v3").events().patch(calendarId="primary", eventId=evenement_id, body=corps, sendUpdates="none").execute()
    return "Événement modifié."


def agenda_supprimer(evenement_id: str) -> str:
    service("calendar", "v3").events().delete(calendarId="primary", eventId=evenement_id, sendUpdates="none").execute()
    return "Événement supprimé."
