from __future__ import annotations

from typing import Any


ALIASES = {
    "CONTROL": "CTRL",
    "OPTION": "ALT",
    "COMMAND": "CMD",
    "SUPER": "WIN",
    "RETURN": "ENTER",
    "ESCAPE": "ESC",
    "PGUP": "PAGE_UP",
    "PGDN": "PAGE_DOWN",
    "SPACEBAR": "SPACE",
}

PYNPUT_SPECIAL_KEYS = {
    "ALT": "alt",
    "ALT_GR": "alt_gr",
    "BACKSPACE": "backspace",
    "CAPS_LOCK": "caps_lock",
    "CMD": "cmd",
    "CTRL": "ctrl",
    "DELETE": "delete",
    "DOWN": "down",
    "END": "end",
    "ENTER": "enter",
    "ESC": "esc",
    "F1": "f1",
    "F2": "f2",
    "F3": "f3",
    "F4": "f4",
    "F5": "f5",
    "F6": "f6",
    "F7": "f7",
    "F8": "f8",
    "F9": "f9",
    "F10": "f10",
    "F11": "f11",
    "F12": "f12",
    "HOME": "home",
    "LEFT": "left",
    "PAGE_DOWN": "page_down",
    "PAGE_UP": "page_up",
    "RIGHT": "right",
    "SHIFT": "shift",
    "SPACE": "space",
    "TAB": "tab",
    "UP": "up",
    "WIN": "cmd",
}


def normalize_key_token(token: Any) -> str:
    if token is None:
        return ""
    if isinstance(token, str):
        raw = token
    elif hasattr(token, "char") and getattr(token, "char"):
        raw = str(getattr(token, "char"))
    elif hasattr(token, "name") and getattr(token, "name"):
        raw = str(getattr(token, "name"))
    else:
        raw = str(token)
    raw = raw.replace("Key.", "").replace("'", "").replace('"', "").strip().upper()
    return ALIASES.get(raw, raw)


def normalize_key_combo(keys: list[str]) -> str:
    return "+".join(normalize_key_token(key) for key in keys if normalize_key_token(key))


def resolve_pynput_key(token: str):
    from pynput import keyboard

    normalized = normalize_key_token(token)
    if len(normalized) == 1:
        return normalized.lower()
    attr_name = PYNPUT_SPECIAL_KEYS.get(normalized)
    if not attr_name:
        raise ValueError(f"Unsupported key token: {token}")
    return getattr(keyboard.Key, attr_name)

