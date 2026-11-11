"""Read-only startup capability diagnostics.

This module deliberately does not install packages, contact services, open
applications, or write files. It reports what the current environment can
provide so setup decisions remain explicit and user-controlled.
"""
from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any


_REQUIRED_IMPORTS = {
    "PyQt6": "PyQt6",
    "numpy": "numpy",
    "sounddevice": "sounddevice",
    "google-genai": "google.genai",
    "keyring": "keyring",
    "playwright": "playwright",
    "requests": "requests",
    "psutil": "psutil",
    "pyautogui": "pyautogui",
    "Pillow": "PIL",
}

_OPTIONAL_CAPABILITIES = {
    "integrations": {
        "google-api-python-client": "googleapiclient",
        "google-auth-oauthlib": "google_auth_oauthlib",
        "tinytuya": "tinytuya",
        "paho-mqtt": "paho.mqtt",
        "openpyxl": "openpyxl",
        "youtube-transcript-api": "youtube_transcript_api",
        "pygetwindow": "pygetwindow",
    },
    "documents": {
        "pdfplumber": "pdfplumber",
        "PyPDF2": "PyPDF2",
        "python-docx": "docx",
        "pynvml": "pynvml",
        "pandas": "pandas",
        "pydub": "pydub",
        "mediapipe": "mediapipe",
    },
    "local-voice": {
        "faster-whisper": "faster_whisper",
        "piper-tts": "piper",
        "vosk": "vosk",
        "edge-tts": "edge_tts",
        "kokoro": "kokoro",
    },
}


def _module_available(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _audio_available() -> bool:
    if not _module_available("sounddevice"):
        return False
    try:
        import sounddevice

        sounddevice.query_devices()
    except (ImportError, OSError, RuntimeError):
        return False
    return True


def _path_readable(path: Path) -> bool:
    return path.exists() and os.access(path, os.R_OK)


def _playwright_cache_dir(system: str) -> Path:
    configured = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if configured:
        return Path(configured)
    if system == "Windows":
        return Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    if system == "Darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    return Path.home() / ".cache" / "ms-playwright"


def _browser_status(system: str, package_available: bool) -> dict[str, Any]:
    cache = _playwright_cache_dir(system)
    names = {
        "chromium": any(cache.glob("chromium-*")),
        "firefox": any(cache.glob("firefox-*")),
        "webkit": any(cache.glob("webkit-*")),
    }
    return {
        "package": package_available,
        "cache_present": _path_readable(cache),
        "installed": names,
    }


def _native_tools(system: str) -> dict[str, bool]:
    if system == "Windows":
        names = ("powershell", "cmd", "where")
    elif system == "Darwin":
        names = ("osascript", "open", "afplay")
    else:
        names = ("xdg-open", "wmctrl", "pactl")
    return {name: shutil.which(name) is not None for name in names}


def _optional_status() -> dict[str, dict[str, bool]]:
    return {
        group: {
            package: _module_available(module)
            for package, module in packages.items()
        }
        for group, packages in _OPTIONAL_CAPABILITIES.items()
    }


def _secure_storage_status() -> dict[str, bool]:
    if not _module_available("keyring"):
        return {"package": False, "backend": False}
    try:
        from memory.config_manager import _secure_keyring

        _secure_keyring()
    except (ImportError, RuntimeError, AttributeError):
        return {"package": True, "backend": False}
    return {"package": True, "backend": True}


def run_diagnostics(base_dir: Path | None = None) -> dict[str, Any]:
    """Return a JSON-serializable, local-only capability report."""
    root = (base_dir or Path(__file__).resolve().parent.parent).resolve()
    system = platform.system() or "unknown"
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    dependencies = {
        package: _module_available(module)
        for package, module in _REQUIRED_IMPORTS.items()
    }

    accessibility = {
        "available": False,
        "provider": "none",
    }
    if system == "Windows" and _module_available("pywinauto"):
        accessibility = {"available": True, "provider": "pywinauto"}
    elif system == "Darwin" and shutil.which("osascript"):
        accessibility = {"available": True, "provider": "osascript"}
    elif system == "Linux":
        provider = next(
            (name for name in ("ydotool", "xdotool", "wmctrl")
             if shutil.which(name)),
            None,
        )
        if provider:
            accessibility = {"available": True, "provider": provider}

    config_dir = root / "config"
    temp_dir = Path(tempfile.gettempdir())
    config_permission_path = config_dir if config_dir.exists() else root
    browser = _browser_status(system, dependencies["playwright"])
    return {
        "system": system,
        "python": {
            "version": python_version,
            "supported": (3, 11) <= sys.version_info[:2] <= (3, 13),
        },
        "dependencies": dependencies,
        "playwright": browser,
        "accessibility": accessibility,
        "audio": {
            "package": dependencies["sounddevice"],
            "devices_queryable": _audio_available(),
        },
        "native_tools": _native_tools(system),
        "optional": _optional_status(),
        "secure_storage": _secure_storage_status(),
        "ui_automation": _ui_automation_status(),
        "paths": {
            "project_readable": _path_readable(root),
            "project_writable": os.access(root, os.W_OK),
            "config_readable": _path_readable(config_dir),
            "config_writable": os.access(config_permission_path, os.W_OK),
            "temp_readable": _path_readable(temp_dir),
            "temp_writable": os.access(temp_dir, os.W_OK),
        },
    }


def _ui_automation_status() -> dict[str, Any]:
    try:
        from core.ui_adapter import capabilities

        return capabilities().as_dict()
    except (ImportError, AttributeError, OSError, RuntimeError):
        return {
            "platform": platform.system() or "unknown",
            "available": False,
            "read_only": True,
            "capabilities": [],
            "reason": "UI Automation adapter unavailable.",
        }


def summarize_diagnostics(report: dict[str, Any]) -> str:
    """Create a short status line without exposing paths, keys, or telemetry."""
    missing = [
        package for package, available in report["dependencies"].items()
        if not available
    ]
    unavailable = []
    if not report["python"]["supported"]:
        unavailable.append("Python")
    if not report["audio"]["devices_queryable"]:
        unavailable.append("audio")
    if not report["accessibility"]["available"]:
        unavailable.append("accessibility")
    if not any(report["playwright"]["installed"].values()):
        unavailable.append("browser engine")
    if not any(report["native_tools"].values()):
        unavailable.append("native tools")
    if missing:
        unavailable.append(f"packages: {', '.join(missing)}")
    if not unavailable:
        return "DIAG: local capabilities ready; no installation or network checks performed."
    return "DIAG: unavailable locally — " + "; ".join(unavailable) + "."
