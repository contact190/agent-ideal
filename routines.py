"""Tâches planifiées : l'agent travaille seul à heures fixes.

Une routine = une consigne en langage naturel + un horaire + des autorisations données à l'avance.
Exemple : « Chaque jour à 8 h : lis la liste des fournisseurs dans le Google Sheet X, envoie à chacun la
commande du jour, puis ouvre Stock NV, vérifie les sorties d'hier et envoie-moi un rapport. »

Pendant une routine, personne n'est devant l'écran :
- les actions couvertes par les autorisations de la routine sont faites directement ;
- les autres attendent ta validation dans l'interface (20 min), sinon elles sont refusées et
  signalées dans le rapport.
"""

import datetime
import json
import threading
import time
import uuid

import config

FICHIER_ROUTINES = config.DOSSIER_DONNEES / "routines.json"
DOSSIER_HISTORIQUE = config.DOSSIER_DONNEES / "historique_routines"
DOSSIER_HISTORIQUE.mkdir(exist_ok=True)
FICHIER_CARNET = config.DOSSIER_DONNEES / "carnet.md"

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
RATTRAPAGE_HEURES = 12          # si le PC était éteint à l'heure prévue, on rattrape dans les 12 h

_verrou = threading.RLock()


# ---------------------------------------------------------------- stockage

def lister() -> list:
    with _verrou:
        if not FICHIER_ROUTINES.exists():
            return []
        try:
            return json.loads(FICHIER_ROUTINES.read_text(encoding="utf-8"))
        except Exception:
            return []


def _sauver_tout(routines):
    with _verrou:
        FICHIER_ROUTINES.write_text(json.dumps(routines, ensure_ascii=False, indent=2), encoding="utf-8")


def obtenir(id_routine):
    return next((r for r in lister() if r["id"] == id_routine), None)


def _normaliser_heures(heures):
    if isinstance(heures, str):
        heures = [h for h in heures.replace(";", ",").split(",")]
    propres = []
    for h in heures or []:
        h = str(h).strip().lower().replace("h", ":")
        if not h:
            continue
        if h.endswith(":"):
            h += "00"
        hh, mm = (h.split(":") + ["0"])[:2]
        propres.append(f"{int(hh):02d}:{int(mm or 0):02d}")
    return sorted(set(propres))


def _normaliser_jours(jours):
    """Accepte [1..7] (1 = lundi) ou des noms ; vide = tous les jours."""
    if not jours:
        return [1, 2, 3, 4, 5, 6, 7]
    res = set()
    for j in jours:
        if isinstance(j, int) or str(j).isdigit():
            res.add(int(j))
        else:
            n = str(j).strip().lower()[:3]
            for i, nom in enumerate(JOURS, 1):
                if nom.startswith(n):
                    res.add(i)
    return sorted(x for x in res if 1 <= x <= 7) or [1, 2, 3, 4, 5, 6, 7]


def enregistrer(donnees: dict) -> dict:
    """Crée ou met à jour une routine. Renvoie la routine enregistrée."""
    with _verrou:
        routines = lister()
        existante = next((r for r in routines if r["id"] == donnees.get("id")), None) if donnees.get("id") else None
        r = existante or {"id": uuid.uuid4().hex[:8], "cree_le": datetime.datetime.now().isoformat(timespec="seconds"),
                          "derniere_execution": None, "dernier_resultat": "", "dernier_statut": ""}
        for cle in ("nom", "consigne", "actif"):
            if cle in donnees:
                r[cle] = donnees[cle]
        if "heures" in donnees:
            r["heures"] = _normaliser_heures(donnees["heures"])
        if "jours" in donnees:
            r["jours"] = _normaliser_jours(donnees["jours"])
        aut = dict(r.get("autorisations") or {})
        for cle in ("emails_autorises", "commandes", "suppressions", "remplacer_fichiers"):
            if cle in donnees:
                aut[cle] = donnees[cle]
            if "autorisations" in donnees and cle in donnees["autorisations"]:
                aut[cle] = donnees["autorisations"][cle]
        if isinstance(aut.get("emails_autorises"), str):
            aut["emails_autorises"] = [e.strip() for e in aut["emails_autorises"].replace(";", ",").split(",") if e.strip()]
        aut.setdefault("emails_autorises", [])
        aut.setdefault("commandes", False)
        aut.setdefault("suppressions", False)
        aut.setdefault("remplacer_fichiers", True)
        r["autorisations"] = aut
        r.setdefault("actif", True)
        r.setdefault("heures", ["08:00"])
        r.setdefault("jours", [1, 2, 3, 4, 5, 6, 7])
        if not r.get("nom") or not r.get("consigne"):
            raise ValueError("Une tâche planifiée a besoin d'un nom et d'une consigne.")
        if not r["heures"]:
            raise ValueError("Indique au moins une heure (ex. 08:30).")
        if not existante:
            # ne pas exécuter immédiatement une heure déjà passée aujourd'hui
            r["derniere_execution"] = datetime.datetime.now().isoformat(timespec="seconds")
            routines.append(r)
        _sauver_tout(routines)
        return r


def supprimer(id_routine) -> bool:
    with _verrou:
        routines = lister()
        reste = [r for r in routines if r["id"] != id_routine]
        _sauver_tout(reste)
        return len(reste) != len(routines)


def _maj(id_routine, **champs):
    with _verrou:
        routines = lister()
        for r in routines:
            if r["id"] == id_routine:
                r.update(champs)
        _sauver_tout(routines)


# ---------------------------------------------------------------- horaires

def _creneaux(r, jour: datetime.date):
    if jour.isoweekday() not in r.get("jours", []):
        return []
    res = []
    for h in r.get("heures", []):
        hh, mm = map(int, h.split(":"))
        res.append(datetime.datetime.combine(jour, datetime.time(hh, mm)))
    return res


def prochaine_execution(r, maintenant=None):
    maintenant = maintenant or datetime.datetime.now()
    for d in range(0, 8):
        for c in _creneaux(r, maintenant.date() + datetime.timedelta(days=d)):
            if c > maintenant:
                return c
    return None


def creneau_du(r, maintenant=None):
    """Renvoie le créneau à exécuter maintenant (le plus récent pas encore fait), ou None."""
    if not r.get("actif", True):
        return None
    maintenant = maintenant or datetime.datetime.now()
    derniere = datetime.datetime.fromisoformat(r["derniere_execution"]) if r.get("derniere_execution") else datetime.datetime.min
    candidats = []
    for d in (1, 0):
        for c in _creneaux(r, maintenant.date() - datetime.timedelta(days=d)):
            if derniere < c <= maintenant and (maintenant - c).total_seconds() <= RATTRAPAGE_HEURES * 3600:
                candidats.append(c)
    return max(candidats) if candidats else None


def decrire_horaire(r):
    jours = r.get("jours", [])
    if len(jours) == 7:
        j = "tous les jours"
    elif set(jours) == {1, 2, 3, 4, 5}:
        j = "du lundi au vendredi"
    elif set(jours) == {6, 7, 1, 2, 3, 4}:
        j = "du samedi au jeudi"
    elif set(jours) == {7, 1, 2, 3, 4}:
        j = "du dimanche au jeudi"
    else:
        j = "le " + ", ".join(JOURS[i - 1] for i in jours)
    return f"{j} à {', '.join(r.get('heures', []))}"


def resume_pour_agent(r):
    a = r.get("autorisations", {})
    prochaine = prochaine_execution(r)
    return (f"- id={r['id']} « {r['nom']} » ({'active' if r.get('actif', True) else 'en pause'}) — {decrire_horaire(r)}\n"
            f"  Consigne : {r['consigne']}\n"
            f"  Autorisations sans validation : e-mails vers {', '.join(a.get('emails_autorises') or []) or 'personne'}"
            f"{' ; commandes' if a.get('commandes') else ''}{' ; suppressions' if a.get('suppressions') else ''}\n"
            f"  Prochaine exécution : {prochaine:%d/%m/%Y %H:%M}" if prochaine else "  Prochaine exécution : aucune"
            ) + (f"\n  Dernière : {r['derniere_execution']} [{r.get('dernier_statut', '')}] {r.get('dernier_resultat', '')[:300]}"
                 if r.get("dernier_statut") else "")


# ---------------------------------------------------------------- carnet (mémoire entre les exécutions)

def carnet_lire() -> str:
    return FICHIER_CARNET.read_text(encoding="utf-8") if FICHIER_CARNET.exists() else "(carnet vide)"


def carnet_ecrire(texte: str, remplacer: bool = False) -> str:
    with _verrou:
        if remplacer or not FICHIER_CARNET.exists():
            FICHIER_CARNET.write_text(texte.strip() + "\n", encoding="utf-8")
        else:
            with FICHIER_CARNET.open("a", encoding="utf-8") as f:
                f.write(f"\n[{datetime.datetime.now():%d/%m/%Y %H:%M}] {texte.strip()}\n")
    return "Carnet mis à jour."


# ---------------------------------------------------------------- planificateur

class Planificateur:
    def __init__(self, bus):
        self.bus = bus
        self._file = []
        self._en_cours = None
        self._agent_en_cours = None
        self._verrou = threading.Lock()
        threading.Thread(target=self._boucle, daemon=True).start()

    def lancer_maintenant(self, id_routine):
        with self._verrou:
            if id_routine not in self._file and self._en_cours != id_routine:
                self._file.append(id_routine)
        return True

    def arreter_en_cours(self):
        if self._agent_en_cours:
            self._agent_en_cours.arreter()

    def etat(self):
        return {"en_cours": self._en_cours, "file": list(self._file)}

    def _boucle(self):
        time.sleep(5)
        while True:
            try:
                maintenant = datetime.datetime.now()
                for r in lister():
                    c = creneau_du(r, maintenant)
                    if c:
                        _maj(r["id"], derniere_execution=c.isoformat(timespec="seconds"))
                        self.lancer_maintenant(r["id"])
                with self._verrou:
                    suivant = self._file.pop(0) if self._file else None
                if suivant:
                    self._executer(suivant)
            except Exception as e:
                config.journal(f"Planificateur : {type(e).__name__} : {e}")
            time.sleep(20)

    def _executer(self, id_routine):
        from agent import Agent
        r = obtenir(id_routine)
        if not r:
            return
        self._en_cours = id_routine
        debut = datetime.datetime.now()
        self.bus.publier({"type": "routine_debut", "routine": r["nom"], "id": r["id"]})
        config.journal(f"Routine « {r['nom']} » démarrée")
        ag = Agent(self.bus, routine=r)
        self._agent_en_cours = ag
        try:
            resultat, statut = ag.executer_routine()
        except Exception as e:
            resultat, statut = f"Erreur : {e}", "erreur"
        finally:
            self._agent_en_cours = None
            self._en_cours = None
        duree = int((datetime.datetime.now() - debut).total_seconds())
        _maj(id_routine, dernier_resultat=resultat[:2000], dernier_statut=statut, derniere_duree=duree)
        entree = {"routine": r["nom"], "id": r["id"], "debut": debut.isoformat(timespec="seconds"), "duree_s": duree,
                  "statut": statut, "resultat": resultat, "tokens": ag.tokens}
        (DOSSIER_HISTORIQUE / f"{debut:%Y-%m-%d_%H%M%S}_{r['id']}.json").write_text(json.dumps(entree, ensure_ascii=False, indent=1), encoding="utf-8")
        self.bus.publier({"type": "routine_fin", "routine": r["nom"], "id": r["id"], "statut": statut, "resultat": resultat[:600]})
        config.journal(f"Routine « {r['nom']} » terminée ({statut}, {duree} s)")


def historique(nombre=30):
    fichiers = sorted(DOSSIER_HISTORIQUE.glob("*.json"), reverse=True)[:nombre]
    res = []
    for f in fichiers:
        try:
            res.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return res
