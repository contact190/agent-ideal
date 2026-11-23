"""Outils fichiers et documents : lire, créer, ranger, convertir.

Sécurité :
- l'agent ne travaille que dans les dossiers autorisés (réglages) ;
- il ne supprime jamais définitivement : « supprimer » envoie dans une corbeille interne ;
- écraser un fichier existant demande une confirmation.
"""

import datetime
import json
import os
import shutil
import subprocess
import sys
import zipfile
import re
from pathlib import Path

import config

LIMITE_TEXTE = 60_000


class RefusAcces(Exception):
    pass


def _dossiers_autorises():
    return [Path(d).expanduser().resolve() for d in config.charger_reglages()["dossiers_autorises"]]


def verifier_chemin(chemin: str) -> Path:
    if not chemin:
        raise RefusAcces("Chemin vide.")
    p = Path(os.path.expandvars(chemin)).expanduser()
    if not p.is_absolute():
        p = Path.home() / p
    p = p.resolve()
    for d in _dossiers_autorises():
        if p == d or d in p.parents:
            return p
    raise RefusAcces(
        f"Accès refusé : {p} n'est pas dans les dossiers autorisés "
        f"({', '.join(str(d) for d in _dossiers_autorises())}). "
        "L'utilisateur peut ajouter ce dossier dans les Réglages.")


def _taille_lisible(n):
    for unite in ("o", "Ko", "Mo", "Go"):
        if n < 1024:
            return f"{n:.0f} {unite}"
        n /= 1024
    return f"{n:.1f} To"


# ---------------------------------------------------------------- navigation

def lister_dossier(chemin: str, recursif: bool = False) -> str:
    p = verifier_chemin(chemin)
    if not p.is_dir():
        return f"{p} n'est pas un dossier."
    lignes = []
    iterateur = p.rglob("*") if recursif else p.iterdir()
    for i, e in enumerate(sorted(iterateur, key=lambda x: (not x.is_dir(), str(x).lower()))):
        if i >= 400:
            lignes.append("… (liste tronquée à 400 éléments)")
            break
        rel = e.relative_to(p)
        if e.is_dir():
            lignes.append(f"[dossier] {rel}")
        else:
            st = e.stat()
            lignes.append(f"{rel}  ({_taille_lisible(st.st_size)}, modifié {datetime.datetime.fromtimestamp(st.st_mtime):%d/%m/%Y %H:%M})")
    return f"Contenu de {p} :\n" + ("\n".join(lignes) if lignes else "(vide)")


def rechercher_fichiers(nom_contient: str, dossier: str = "") -> str:
    racines = [verifier_chemin(dossier)] if dossier else _dossiers_autorises()
    motif = nom_contient.lower()
    trouves = []
    for r in racines:
        for e in r.rglob("*"):
            if motif in e.name.lower():
                trouves.append(str(e))
                if len(trouves) >= 100:
                    break
    return "\n".join(trouves) if trouves else "Aucun fichier trouvé."


# ---------------------------------------------------------------- lecture

def _texte_odf(p: Path) -> str:
    with zipfile.ZipFile(p) as z:
        xml = z.read("content.xml").decode("utf-8", "ignore")
    xml = re.sub(r"<table:table-row[^>]*>", "\n", xml)
    xml = re.sub(r"<table:table-cell[^>]*>", " | ", xml)
    xml = re.sub(r"<text:(p|h)[^>]*>", "\n", xml)
    texte = re.sub(r"<[^>]+>", "", xml)
    return "\n".join(l for l in texte.splitlines() if l.strip(" |"))


def lire_fichier(chemin: str, feuille: str = "") -> str:
    p = verifier_chemin(chemin)
    if not p.is_file():
        return f"Fichier introuvable : {p}"
    ext = p.suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        import openpyxl
        wb_f = openpyxl.load_workbook(p, data_only=False)
        wb_v = openpyxl.load_workbook(p, data_only=True)
        noms = [feuille] if feuille else wb_f.sheetnames
        morceaux = [f"Classeur {p.name} – feuilles : {', '.join(wb_f.sheetnames)}"]
        for n in noms:
            ws, wv = wb_f[n], wb_v[n]
            morceaux.append(f"\n=== Feuille « {n} » ({ws.max_row} lignes × {ws.max_column} colonnes) ===")
            for row_f, row_v in zip(ws.iter_rows(), wv.iter_rows()):
                cellules = []
                for cf, cv in zip(row_f, row_v):
                    if cf.value is None:
                        continue
                    if isinstance(cf.value, str) and cf.value.startswith("="):
                        cellules.append(f"{cf.coordinate}={cf.value}" + (f" (= {cv.value!r})" if cv.value is not None else ""))
                    else:
                        cellules.append(f"{cf.coordinate}={cf.value!r}")
                if cellules:
                    morceaux.append("  ".join(cellules))
        texte = "\n".join(morceaux)
    elif ext == ".docx":
        import docx
        d = docx.Document(p)
        parties = [para.text for para in d.paragraphs]
        for t_i, t in enumerate(d.tables, 1):
            parties.append(f"\n[Tableau {t_i}]")
            for r in t.rows:
                parties.append(" | ".join(c.text for c in r.cells))
        texte = "\n".join(parties)
    elif ext == ".pdf":
        from pypdf import PdfReader
        r = PdfReader(str(p))
        texte = "\n".join(f"--- page {i} ---\n{pg.extract_text() or ''}" for i, pg in enumerate(r.pages, 1))
        if len(re.sub(r"--- page \d+ ---", "", texte).strip()) < 5 * len(r.pages):
            texte += "\n(Peu de texte extrait : le PDF est peut-être scanné. Utilise le contrôle de l'écran pour le regarder.)"
    elif ext in (".ods", ".odt", ".odp"):
        texte = _texte_odf(p)
    elif ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"):
        return f"__IMAGE__:{p}"
    else:
        try:
            texte = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                texte = p.read_text(encoding="cp1252")
            except Exception:
                return f"{p.name} est un fichier binaire ({ext}) que je ne sais pas lire directement."
    if len(texte) > LIMITE_TEXTE:
        texte = texte[:LIMITE_TEXTE] + f"\n… (tronqué : {len(texte)} caractères au total)"
    return texte


# ---------------------------------------------------------------- écriture

def existe(chemin: str) -> bool:
    try:
        return verifier_chemin(chemin).exists()
    except RefusAcces:
        return False


def ecrire_texte(chemin: str, contenu: str) -> str:
    p = verifier_chemin(chemin)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(contenu, encoding="utf-8")
    return f"Fichier écrit : {p}"


def creer_dossier(chemin: str) -> str:
    p = verifier_chemin(chemin)
    p.mkdir(parents=True, exist_ok=True)
    return f"Dossier prêt : {p}"


def copier(source: str, destination: str) -> str:
    s, d = verifier_chemin(source), verifier_chemin(destination)
    if s.is_dir():
        shutil.copytree(s, d, dirs_exist_ok=True)
    else:
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(s, d)
    return f"Copié : {s} → {d}"


def deplacer(source: str, destination: str) -> str:
    s, d = verifier_chemin(source), verifier_chemin(destination)
    d.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(s), str(d))
    return f"Déplacé : {s} → {d}"


def mettre_a_la_corbeille(chemin: str) -> str:
    p = verifier_chemin(chemin)
    if not p.exists():
        return f"Introuvable : {p}"
    corbeille = config.DOSSIER_DONNEES / "corbeille" / datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    corbeille.mkdir(parents=True, exist_ok=True)
    cible = corbeille / p.name
    shutil.move(str(p), str(cible))
    (corbeille / "origine.txt").write_text(str(p), encoding="utf-8")
    return f"Mis à la corbeille de l'agent : {p} (récupérable dans {corbeille})"


def ouvrir(chemin: str) -> str:
    p = verifier_chemin(chemin)
    if sys.platform == "win32":
        os.startfile(str(p))  # noqa
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p)])
    return f"Ouvert : {p}"


# ---------------------------------------------------------------- Excel

def creer_excel(chemin: str, feuilles: list) -> str:
    """feuilles = [{"nom": str, "lignes": [[...], ...], "largeurs": {"A": 40}, "entete": true,
                    "formats": {"D2:E20": "#,##0.00"}, "gras": ["A10:E10"]}]
    Une valeur texte commençant par « = » est une formule Excel."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    p = verifier_chemin(chemin)
    if p.suffix.lower() not in (".xlsx", ".xlsm"):
        p = p.with_suffix(".xlsx")
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    fin = Side(style="thin", color="BBBBBB")
    for f in feuilles:
        ws = wb.create_sheet(str(f.get("nom", "Feuille"))[:31])
        for ligne in f.get("lignes", []):
            ws.append(ligne)
        if f.get("entete", True) and ws.max_row >= 1:
            for c in ws[1]:
                c.font = Font(bold=True, color="FFFFFF")
                c.fill = PatternFill("solid", fgColor="1F4E78")
                c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            ws.freeze_panes = "A2"
        for row in ws.iter_rows():
            for c in row:
                if c.value is not None:
                    c.border = Border(top=fin, bottom=fin, left=fin, right=fin)
        for plage, fmt in (f.get("formats") or {}).items():
            for row in ws[plage]:
                for c in (row if isinstance(row, tuple) else (row,)):
                    c.number_format = fmt
        for plage in f.get("gras") or []:
            for row in ws[plage]:
                for c in (row if isinstance(row, tuple) else (row,)):
                    c.font = Font(bold=True)
        largeurs = f.get("largeurs") or {}
        for col_cells in ws.columns:
            lettre = col_cells[0].column_letter
            if lettre in largeurs:
                ws.column_dimensions[lettre].width = largeurs[lettre]
            else:
                long = max((len(str(c.value)) for c in col_cells if c.value is not None and not str(c.value).startswith("=")), default=8)
                ws.column_dimensions[lettre].width = min(max(10, long + 2), 60)
    p.parent.mkdir(parents=True, exist_ok=True)
    wb.save(p)
    return f"Classeur Excel créé : {p}"


def modifier_excel(chemin: str, modifications: list, feuille: str = "") -> str:
    """modifications = [{"cellule": "B4", "valeur": 12}, ...] ; ajoute la feuille si elle n'existe pas."""
    import openpyxl
    p = verifier_chemin(chemin)
    wb = openpyxl.load_workbook(p)
    if feuille and feuille not in wb.sheetnames:
        wb.create_sheet(feuille)
    ws = wb[feuille] if feuille else wb.active
    for m in modifications:
        ws[m["cellule"]] = m.get("valeur")
    wb.save(p)
    return f"{len(modifications)} cellule(s) modifiée(s) dans {p.name} / {ws.title}"


# ---------------------------------------------------------------- Word

def creer_word(chemin: str, blocs: list) -> str:
    """blocs = [{"type": "titre"|"sous-titre"|"paragraphe"|"liste"|"tableau"|"saut_de_page",
                 "texte": str, "elements": [..], "lignes": [[..], ..], "gras": bool}]"""
    import docx
    from docx.shared import Pt, RGBColor
    p = verifier_chemin(chemin)
    if p.suffix.lower() != ".docx":
        p = p.with_suffix(".docx")
    d = docx.Document()
    style = d.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)
    for b in blocs:
        t = b.get("type", "paragraphe")
        if t == "titre":
            h = d.add_heading(b.get("texte", ""), level=1)
            for r in h.runs:
                r.font.color.rgb = RGBColor(0x1F, 0x4E, 0x78)
        elif t == "sous-titre":
            d.add_heading(b.get("texte", ""), level=2)
        elif t == "liste":
            for e in b.get("elements", []):
                d.add_paragraph(str(e), style="List Bullet")
        elif t == "tableau":
            lignes = b.get("lignes", [])
            if lignes:
                tab = d.add_table(rows=0, cols=max(len(l) for l in lignes))
                tab.style = "Table Grid"
                for i, l in enumerate(lignes):
                    cells = tab.add_row().cells
                    for j, v in enumerate(l):
                        cells[j].text = "" if v is None else str(v)
                        if i == 0:
                            for r in cells[j].paragraphs[0].runs:
                                r.bold = True
                d.add_paragraph()
        elif t == "saut_de_page":
            d.add_page_break()
        else:
            para = d.add_paragraph()
            run = para.add_run(b.get("texte", ""))
            run.bold = bool(b.get("gras"))
    p.parent.mkdir(parents=True, exist_ok=True)
    d.save(p)
    return f"Document Word créé : {p}"


# ---------------------------------------------------------------- PDF

def convertir_en_pdf(chemin: str) -> str:
    p = verifier_chemin(chemin)
    sortie = p.with_suffix(".pdf")
    ext = p.suffix.lower()
    if ext == ".docx" and sys.platform in ("win32", "darwin"):
        try:
            code = ("import sys; from docx2pdf import convert; convert(sys.argv[1], sys.argv[2])")
            subprocess.run([sys.executable, "-c", code, str(p), str(sortie)],
                           check=True, timeout=180, capture_output=True)
            if sortie.exists():
                return f"PDF créé avec Word : {sortie}"
        except Exception:
            pass
    so = shutil.which("soffice") or shutil.which("libreoffice")
    if not so and sys.platform == "win32":
        for c in (r"C:\Program Files\LibreOffice\program\soffice.exe",
                  r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"):
            if Path(c).exists():
                so = c
    if so:
        try:
            subprocess.run([so, "--headless", "--convert-to", "pdf", "--outdir", str(p.parent), str(p)],
                           check=True, timeout=180, capture_output=True)
            if sortie.exists():
                return f"PDF créé avec LibreOffice : {sortie}"
        except Exception:
            pass
    if ext in (".docx", ".txt", ".md"):
        texte = lire_fichier(str(p))
        blocs = [{"type": "paragraphe", "texte": l} for l in texte.splitlines()]
        creer_pdf(str(sortie), blocs)
        return f"PDF créé (mise en page simple, ni Word ni LibreOffice trouvés) : {sortie}"
    return "Impossible de convertir : installe Microsoft Word ou LibreOffice."


def creer_pdf(chemin: str, blocs: list) -> str:
    """Mêmes blocs que creer_word."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, ListFlowable, ListItem
    from xml.sax.saxutils import escape
    p = verifier_chemin(chemin)
    if p.suffix.lower() != ".pdf":
        p = p.with_suffix(".pdf")
    s = getSampleStyleSheet()
    elements = []
    for b in blocs:
        t = b.get("type", "paragraphe")
        texte = escape(str(b.get("texte", "")))
        if t == "titre":
            elements += [Paragraph(texte, s["Title"]), Spacer(1, 0.3 * cm)]
        elif t == "sous-titre":
            elements.append(Paragraph(texte, s["Heading2"]))
        elif t == "liste":
            elements.append(ListFlowable([ListItem(Paragraph(escape(str(e)), s["BodyText"])) for e in b.get("elements", [])], bulletType="bullet"))
        elif t == "tableau":
            lignes = [[Paragraph(escape("" if v is None else str(v)), s["BodyText"]) for v in l] for l in b.get("lignes", [])]
            if lignes:
                tab = Table(lignes, repeatRows=1)
                tab.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                                         ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E78")),
                                         ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                                         ("VALIGN", (0, 0), (-1, -1), "TOP")]))
                elements += [tab, Spacer(1, 0.4 * cm)]
        elif t == "saut_de_page":
            elements.append(PageBreak())
        else:
            elements.append(Paragraph(f"<b>{texte}</b>" if b.get("gras") else (texte or "&nbsp;"), s["BodyText"]))
    p.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(str(p), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                      topMargin=2 * cm, bottomMargin=2 * cm).build(elements)
    return f"PDF créé : {p}"


# ---------------------------------------------------------------- commandes

def executer_commande(commande: str, dossier: str = "", delai: int = 120) -> str:
    cwd = str(verifier_chemin(dossier)) if dossier else str(_dossiers_autorises()[0])
    if sys.platform == "win32":
        args = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + commande]
    else:
        args = ["bash", "-lc", commande]
    try:
        r = subprocess.run(args, cwd=cwd, capture_output=True, timeout=delai,
                           encoding="utf-8", errors="replace",
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return f"La commande a dépassé {delai} s et a été arrêtée."
    sortie = (r.stdout or "") + (("\n[erreurs]\n" + r.stderr) if r.stderr else "")
    if len(sortie) > 20_000:
        sortie = sortie[:20_000] + "\n… (tronqué)"
    return f"Code de sortie {r.returncode}\n{sortie}".strip()


def ouvrir_application(nom_ou_adresse: str) -> str:
    import webbrowser
    reglages = config.charger_reglages()
    for app in reglages.get("applications", []):
        if app["nom"].lower() == nom_ou_adresse.lower():
            nom_ou_adresse = app["adresse"]
            break
    if re.match(r"^https?://", nom_ou_adresse):
        webbrowser.open(nom_ou_adresse)
        return f"Ouvert dans le navigateur : {nom_ou_adresse}"
    if sys.platform == "win32":
        try:
            os.startfile(nom_ou_adresse)  # noqa  (programme, raccourci ou fichier)
            return f"Lancé : {nom_ou_adresse}"
        except OSError:
            subprocess.Popen(["cmd", "/c", "start", "", nom_ou_adresse], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return f"Demande de lancement envoyée : {nom_ou_adresse}"
    subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", nom_ou_adresse])
    return f"Lancé : {nom_ou_adresse}"
