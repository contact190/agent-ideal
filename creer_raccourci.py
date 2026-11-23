"""Crée les raccourcis Windows :
- « Agent Idéal » sur le Bureau (ouvre l'interface) ;
- « Agent Idéal » dans le dossier Démarrage : l'agent démarre discrètement avec Windows,
  pour que les tâches automatiques s'exécutent même si personne ne l'a ouvert.
`python creer_raccourci.py --sans-demarrage` pour ne pas créer le second.
"""
import subprocess
import sys
from pathlib import Path

ici = Path(__file__).resolve().parent
pythonw = ici / ".venv" / "Scripts" / "pythonw.exe"
app = ici / "app.py"


def ps(texte):
    return "'" + str(texte).replace("'", "''") + "'"


def raccourci(dossier_ps, arguments):
    return (
        f"$d={dossier_ps};"
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'Agent Idéal.lnk'));"
        f"$s.TargetPath={ps(pythonw)};"
        f"$s.Arguments={ps(arguments)};"
        f"$s.WorkingDirectory={ps(ici)};"
        "$s.IconLocation=\"$env:SystemRoot\\System32\\imageres.dll,109\";"
        "$s.Description='Agent Idéal';$s.Save();"
    )


script = raccourci("[Environment]::GetFolderPath('Desktop')", f'"{app}"')
if "--sans-demarrage" not in sys.argv:
    script += raccourci("[Environment]::GetFolderPath('Startup')", f'"{app}" --sans-navigateur')

if sys.platform != "win32":
    print(script)
    sys.exit(0)
r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], capture_output=True, text=True)
if r.returncode == 0:
    print("Raccourci « Agent Idéal » créé sur le Bureau.")
    if "--sans-demarrage" not in sys.argv:
        print("L'agent démarrera aussi automatiquement avec Windows (pour les tâches automatiques).")
else:
    print(f"Raccourci non créé : {r.stderr.strip()}\nUtilise 2_LANCER_AGENT.bat à la place.")
