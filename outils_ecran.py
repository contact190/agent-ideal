"""Contrôle de l'écran (souris, clavier, captures) pour l'outil « computer » de Claude.

Format : toolset `computer_toolset_20260801` (pas d'en-tête bêta). Chaque appel est un
bloc tool_use dont le `name` est l'action (screenshot, left_click, type, key…).

Sécurité : déplacer la souris dans le coin en haut à gauche de l'écran arrête immédiatement
l'agent (FAILSAFE de pyautogui), et le bouton « Stop » de l'interface aussi.
"""

import base64
import io
import sys
import time

TOOLSET = {"type": "computer_toolset_20260801"}

ACTIONS = {"screenshot", "zoom", "left_click", "right_click", "middle_click", "double_click", "triple_click",
           "left_click_drag", "mouse_move", "left_mouse_down", "left_mouse_up", "cursor_position",
           "scroll", "type", "key", "hold_key", "wait"}

COTE_MAX = 1366          # taille maximale envoyée à Claude (précision et coût)

_echelle = 1.0           # écran réel / image envoyée
_pret = False


def _preparer():
    global _pret
    if _pret:
        return
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)   # coordonnées en vrais pixels (écrans à 125 %, 150 %…)
        except Exception:
            try:
                import ctypes
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05
    _pret = True


def _capture_brute():
    _preparer()
    from PIL import ImageGrab
    return ImageGrab.grab()


def capture():
    """Renvoie (png_base64, largeur, hauteur) de l'image envoyée à Claude."""
    global _echelle
    from PIL import Image
    img = _capture_brute()
    w, h = img.size
    _echelle = max(w, h) / COTE_MAX if max(w, h) > COTE_MAX else 1.0
    if _echelle != 1.0:
        img = img.resize((round(w / _echelle), round(h / _echelle)), Image.LANCZOS)
    tampon = io.BytesIO()
    img.convert("RGB").save(tampon, format="PNG", optimize=True)
    return base64.b64encode(tampon.getvalue()).decode(), img.size[0], img.size[1]


def _reel(coord):
    return round(coord[0] * _echelle), round(coord[1] * _echelle)


TOUCHES = {"return": "enter", "enter": "enter", "escape": "esc", "esc": "esc", "backspace": "backspace",
           "delete": "delete", "tab": "tab", "space": "space", "super": "win", "cmd": "win", "meta": "win",
           "windows": "win", "win": "win", "ctrl": "ctrl", "control": "ctrl", "alt": "alt", "shift": "shift",
           "up": "up", "down": "down", "left": "left", "right": "right", "page_up": "pageup", "prior": "pageup",
           "page_down": "pagedown", "next": "pagedown", "home": "home", "end": "end", "insert": "insert",
           "print": "printscreen", "kp_enter": "enter", "menu": "apps"}


def _touche(nom):
    n = nom.strip().lower()
    return TOUCHES.get(n, n)


def _modifs(texte):
    return [_touche(t) for t in (texte or "").split("+") if t.strip()]


def _taper(texte):
    """Tape le texte. Passe par le presse-papiers pour les accents et l'arabe (pyautogui ne sait taper que l'ASCII)."""
    import pyautogui
    if texte.isascii():
        pyautogui.write(texte, interval=0.01)
        return
    import pyperclip
    try:
        ancien = pyperclip.paste()
    except Exception:
        ancien = None
    pyperclip.copy(texte)
    pyautogui.hotkey("command" if sys.platform == "darwin" else "ctrl", "v")
    time.sleep(0.2)
    if ancien is not None:
        try:
            pyperclip.copy(ancien)
        except Exception:
            pass


def executer(action: str, params: dict):
    """Exécute une action. Renvoie une liste de blocs de contenu pour le tool_result."""
    _preparer()
    import pyautogui
    p = params or {}

    def avec_modifs(fonction):
        mods = _modifs(p.get("text"))
        for m in mods:
            pyautogui.keyDown(m)
        try:
            fonction()
        finally:
            for m in reversed(mods):
                pyautogui.keyUp(m)

    if action == "screenshot":
        b64, w, h = capture()
        return [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}}]

    if action == "zoom":
        from PIL import Image
        x0, y0, x1, y1 = p["region"]
        img = _capture_brute()
        X0, Y0 = _reel((x0, y0))
        X1, Y1 = _reel((x1, y1))
        crop = img.crop((X0, Y0, X1, Y1))
        if max(crop.size) > COTE_MAX:
            r = COTE_MAX / max(crop.size)
            crop = crop.resize((round(crop.size[0] * r), round(crop.size[1] * r)), Image.LANCZOS)
        t = io.BytesIO()
        crop.convert("RGB").save(t, format="PNG")
        return [{"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                             "data": base64.b64encode(t.getvalue()).decode()}}]

    clics = {"left_click": ("left", 1), "right_click": ("right", 1), "middle_click": ("middle", 1),
             "double_click": ("left", 2), "triple_click": ("left", 3)}
    if action in clics:
        bouton, n = clics[action]

        def clic():
            if p.get("coordinate"):
                x, y = _reel(p["coordinate"])
                pyautogui.click(x, y, clicks=n, interval=0.08, button=bouton)
            else:
                pyautogui.click(clicks=n, interval=0.08, button=bouton)
        avec_modifs(clic)
    elif action == "left_click_drag":
        def glisser():
            x0, y0 = _reel(p["start_coordinate"])
            x1, y1 = _reel(p["coordinate"])
            pyautogui.moveTo(x0, y0)
            pyautogui.dragTo(x1, y1, duration=0.4, button="left")
        avec_modifs(glisser)
    elif action == "mouse_move":
        pyautogui.moveTo(*_reel(p["coordinate"]), duration=0.15)
    elif action == "left_mouse_down":
        pyautogui.mouseDown()
    elif action == "left_mouse_up":
        pyautogui.mouseUp()
    elif action == "cursor_position":
        x, y = pyautogui.position()
        return [{"type": "text", "text": f"X={round(x / _echelle)}, Y={round(y / _echelle)}"}]
    elif action == "scroll":
        if p.get("coordinate"):
            pyautogui.moveTo(*_reel(p["coordinate"]))
        n = int(p.get("scroll_amount", 3))
        sens = p.get("scroll_direction", "down")

        def defiler():
            if sens in ("up", "down"):
                pyautogui.scroll(n * 120 * (1 if sens == "up" else -1))
            else:
                pyautogui.hscroll(n * 120 * (1 if sens == "right" else -1))
        avec_modifs(defiler)
    elif action == "type":
        _taper(p.get("text", ""))
    elif action == "key":
        touches = _modifs(p.get("text", ""))
        for _ in range(int(p.get("repeat", 1))):
            pyautogui.hotkey(*touches) if len(touches) > 1 else pyautogui.press(touches[0])
    elif action == "hold_key":
        touches = _modifs(p.get("text", ""))
        for t in touches:
            pyautogui.keyDown(t)
        time.sleep(min(float(p.get("duration", 1)), 300))
        for t in reversed(touches):
            pyautogui.keyUp(t)
    elif action == "wait":
        time.sleep(min(float(p.get("duration", 1)), 300))
    else:
        return [{"type": "text", "text": f"Action inconnue : {action}"}]

    time.sleep(0.4)
    b64, _, _ = capture()
    return [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}}]
