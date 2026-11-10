"""Geheimnisse (z. B. DevOps-Token) mit der Windows-Benutzerverschlüsselung (DPAPI) ablegen.

Der Text ist nur im Konto des angemeldeten Windows-Benutzers wieder entschlüsselbar, die
Datenbankdatei allein verrät das Token nicht.
"""
from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _run(fn, data: bytes) -> bytes:
    kernel32 = ctypes.windll.kernel32
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    buf = ctypes.create_string_buffer(data, len(data))
    blob = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out = _Blob()
    if not fn(ctypes.byref(blob), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("Ver-/Entschlüsselung fehlgeschlagen")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def protect(text: str) -> str:
    if not text:
        return ""
    return base64.b64encode(_run(ctypes.windll.crypt32.CryptProtectData, text.encode("utf-8"))).decode("ascii")


def unprotect(token: str) -> str:
    if not token:
        return ""
    try:
        return _run(ctypes.windll.crypt32.CryptUnprotectData, base64.b64decode(token)).decode("utf-8")
    except (OSError, ValueError):
        return ""
