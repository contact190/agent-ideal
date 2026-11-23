"""Vérifie que toutes les bibliothèques de l'agent sont installées. Code de sortie 1 s'il en manque."""
import importlib
import sys

modules = {"anthropic": "anthropic", "googleapiclient": "google-api-python-client", "google_auth_oauthlib": "google-auth-oauthlib",
           "google_auth_httplib2": "google-auth-httplib2", "openpyxl": "openpyxl", "docx": "python-docx", "reportlab": "reportlab",
           "pypdf": "pypdf", "PIL": "pillow", "pyautogui": "pyautogui", "pyperclip": "pyperclip", "keyring": "keyring", "tzdata": "tzdata"}
if sys.platform in ("win32", "darwin"):
    modules["docx2pdf"] = "docx2pdf"
print(f"Python {sys.version.split()[0]}")
manquants = []
for mod, paquet in modules.items():
    try:
        importlib.import_module(mod)
        print(f"  OK        {paquet}")
    except Exception as e:
        print(f"  MANQUANT  {paquet}  ({type(e).__name__}: {e})")
        manquants.append(paquet)
if manquants:
    print("\n❌ Installation incomplète. Manquant : " + ", ".join(manquants))
    print("Fais une capture de cette fenêtre et envoie-la.")
    sys.exit(1)
print("\n✅ Toutes les bibliothèques sont installées.")
