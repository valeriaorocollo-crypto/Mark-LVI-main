
from __future__ import annotations

import asyncio
import concurrent.futures
import importlib.util
import json
import os
import re
import platform
import shutil
import subprocess
import threading
import time
import webbrowser
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Optional
from urllib.parse import urlsplit

from core import action_policy, outcome

# Importing playwright cost 198 ms at every launch, paid by action discovery
# whether or not a browser was ever opened. It is the second-largest import in
# the project after pyautogui, and together the two were 78% of all module
# import time on the boot path.
#
# WHY THIS STILL RAISES WHEN PLAYWRIGHT IS MISSING
#     The eager import had a second job nobody wrote down: when playwright was
#     absent this module failed to load, action_loader dropped it, and the model
#     was never offered a browser tool it could not serve. Deferring the import
#     without keeping that would declare `browser_control` on a machine that
#     cannot run it — the model would call it, get an exception, and describe a
#     page it never opened. Exactly the failure mode this project spent Mark LVI
#     removing from local engines.
#
#     So the check stays at module scope and still stops the module loading; it
#     just asks find_spec instead of executing the package. 1 ms instead of 198,
#     same outcome, and a sentence that says what to install.
if importlib.util.find_spec("playwright") is None:      # pragma: no cover
    raise ImportError(
        "browser_control needs playwright, which is not installed. "
        "Run: pip install playwright  &&  playwright install chromium"
    )

# Annotations only — `from __future__ import annotations` above makes every one
# of them a string, so these names are never looked up at runtime and cost
# nothing outside a type checker.
if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page, Playwright

# WHY THIS FILE DOES NOT USE core/lazyimport.py's LazyModule LIKE THE OTHERS
#     Every other deferral in this project stands a proxy in for a whole module,
#     because the call sites say `pyautogui.press(...)` and a proxy answers that
#     the same way the module would. What this file needs are two SYMBOLS out of
#     a module: a factory function, and an exception class used in `except`.
#
#     `except` will not take a proxy. It requires a real class inheriting from
#     BaseException, checked by the interpreter at the moment the exception is
#     raised, and a LazyModule there raises TypeError instead of catching
#     anything — the original error then disappears underneath a complaint about
#     the except clause. So these two are bound as real globals instead.
#
# PlaywrightTimeout starts as a private class that is never raised, so an
# `except PlaywrightTimeout:` somehow reached before a session exists catches
# nothing rather than failing that same way.
class _PlaywrightNotLoaded(Exception):
    """Placeholder exception — declared so `except` clauses stay valid, and
    deliberately never raised anywhere."""


async_playwright = None
PlaywrightTimeout: type[BaseException] = _PlaywrightNotLoaded


def _load_playwright() -> None:
    """Import playwright and bind the two runtime symbols. Idempotent."""
    global async_playwright, PlaywrightTimeout
    if async_playwright is not None:
        return
    from playwright.async_api import (          # noqa: PLC0415 — deliberate
        async_playwright as _ap,
        TimeoutError as _timeout,
    )
    async_playwright = _ap
    PlaywrightTimeout = _timeout


_OS = platform.system()   # "Windows" | "Darwin" | "Linux"

def _normalize_url(url: str) -> str:
    """
    Bare words like "instagram" → "https://instagram.com"
    Domains like "instagram.com" → "https://instagram.com"
    Full URLs pass through unchanged.
    """
    url = str(url or "").strip()
    if not url:
        return "about:blank"
    if len(url) > 2048:
        raise ValueError("address exceeds the 2048-character limit")
    if any(ord(char) < 32 or char.isspace() for char in url) or "\\" in url:
        raise ValueError("address contains whitespace or control characters")
    if url.lower() == "about:blank":
        return "about:blank"

    if "://" in url:
        normalized = url
    else:
        if re.match(r"^(javascript|data|file|vbscript|about|blob|intent|ftp):",
                    url, re.IGNORECASE):
            raise ValueError("only HTTP and HTTPS addresses are supported")
        if ":" not in url and "." not in url:
            # Bare words like "instagram" keep the existing .com convenience.
            url += ".com"
        normalized = "https://" + url

    parsed = urlsplit(normalized)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("only HTTP and HTTPS addresses are supported")
    if not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise ValueError("address must have a host and must not contain credentials")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("address contains an invalid port") from exc
    return normalized


def _user_agent() -> str:
    if _OS == "Windows":
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    if _OS == "Darwin":
        return (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    return (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )


def _automation_profile_dir(browser: str) -> str:
    """Return a persistent profile that never contains browser user data."""
    if not isinstance(browser, str) or not browser.strip():
        raise ValueError("browser name is required")
    profile = Path.home() / ".jarvis_profiles" / browser.strip().lower()
    profile.mkdir(parents=True, exist_ok=True)
    return str(profile)

def _find_opera_windows() -> Optional[str]:
    local  = os.environ.get("LOCALAPPDATA", "")
    prog   = os.environ.get("PROGRAMFILES", "")
    prog86 = os.environ.get("PROGRAMFILES(X86)", "")

    candidates = [
        Path(local)  / "Programs" / "Opera"    / "opera.exe",
        Path(local)  / "Programs" / "Opera GX" / "opera.exe",
        Path(prog)   / "Opera"    / "opera.exe",
        Path(prog86) / "Opera"    / "opera.exe",
    ]
    for p in candidates:
        if p.exists():
            print(f"[Browser] Opera found at: {p}")
            return str(p)

    try:
        import winreg
        keys = [
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\opera.exe",
            r"SOFTWARE\Clients\StartMenuInternet\OperaStable\shell\open\command",
            r"SOFTWARE\Clients\StartMenuInternet\OperaGXStable\shell\open\command",
            r"SOFTWARE\Clients\StartMenuInternet\opera\shell\open\command",
        ]
        for key_path in keys:
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    k   = winreg.OpenKey(hive, key_path)
                    val = winreg.QueryValue(k, None)
                    winreg.CloseKey(k)
                    exe = val.strip().strip('"').split('"')[0].split(" --")[0].strip()
                    if exe and Path(exe).exists():
                        print(f"[Browser] Opera found via registry: {exe}")
                        return exe
                except Exception:
                    continue
    except Exception:
        pass

    return shutil.which("opera") or None

def _find_exe_windows(prog_name: str) -> Optional[str]:
    try:
        import winreg
        paths_to_try = [
            rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{prog_name}.exe",
            rf"SOFTWARE\Clients\StartMenuInternet\{prog_name}\shell\open\command",
        ]
        for key_path in paths_to_try:
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    k   = winreg.OpenKey(hive, key_path)
                    val = winreg.QueryValue(k, None)
                    winreg.CloseKey(k)
                    exe = val.strip().strip('"').split('"')[0].split(" --")[0].strip()
                    if exe and Path(exe).exists():
                        return exe
                except Exception:
                    continue
    except Exception:
        pass
    return None

_BROWSER_SPECS: dict[str, dict] = {
    "Windows": {
        "chrome":   {"engine": "chromium", "channel": "chrome",  "bins": []},
        "edge":     {"engine": "chromium", "channel": "msedge",  "bins": []},
        "firefox":  {"engine": "firefox",  "channel": None,      "bins": ["firefox.exe"]},
        "opera":    {"engine": "chromium", "channel": None,      "bins": ["opera.exe"],  "special": "opera_windows"},
        "operagx":  {"engine": "chromium", "channel": None,      "bins": [],             "special": "opera_windows"},
        "brave":    {"engine": "chromium", "channel": None,      "bins": ["brave.exe"]},
        "vivaldi":  {"engine": "chromium", "channel": None,      "bins": ["vivaldi.exe"]},
        "safari":   None,
    },
    "Darwin": {
        "chrome":   {"engine": "chromium", "channel": "chrome",  "bins": []},
        "edge":     {"engine": "chromium", "channel": "msedge",  "bins": ["microsoft-edge"]},
        "firefox":  {"engine": "firefox",  "channel": None,      "bins": ["firefox"]},
        "opera":    {"engine": "chromium", "channel": None,      "bins": ["opera"]},
        "operagx":  {"engine": "chromium", "channel": None,      "bins": ["opera"]},
        "brave":    {"engine": "chromium", "channel": None,      "bins": ["brave browser", "brave"]},
        "vivaldi":  {"engine": "chromium", "channel": None,      "bins": ["vivaldi"]},
        "safari":   {"engine": "webkit",   "channel": None,      "bins": []},
    },
    "Linux": {
        "chrome":   {"engine": "chromium", "channel": None,
                     "bins": ["google-chrome", "google-chrome-stable", "chromium-browser", "chromium"]},
        "edge":     {"engine": "chromium", "channel": None,
                     "bins": ["microsoft-edge", "microsoft-edge-stable"]},
        "firefox":  {"engine": "firefox",  "channel": None, "bins": ["firefox"]},
        "opera":    {"engine": "chromium", "channel": None, "bins": ["opera", "opera-stable"]},
        "operagx":  {"engine": "chromium", "channel": None, "bins": ["opera", "opera-stable"]},
        "brave":    {"engine": "chromium", "channel": None, "bins": ["brave-browser", "brave"]},
        "vivaldi":  {"engine": "chromium", "channel": None, "bins": ["vivaldi-stable", "vivaldi"]},
        "safari":   None,
    },
}

_ALIASES: dict[str, str] = {
    "google chrome":   "chrome",
    "google-chrome":   "chrome",
    "microsoft edge":  "edge",
    "ms edge":         "edge",
    "msedge":          "edge",
    "mozilla firefox": "firefox",
    "opera gx":        "operagx",
    "opera_gx":        "operagx",
}


def _resolve_browser(name: str) -> dict | None:
    name   = _ALIASES.get(name.lower().strip(), name.lower().strip())
    os_map = _BROWSER_SPECS.get(_OS, {})
    spec   = os_map.get(name)
    if spec is None:
        return None

    engine  = spec["engine"]
    channel = spec.get("channel")
    bins    = spec.get("bins", [])
    exe     = None

    if spec.get("special") == "opera_windows":
        exe = _find_opera_windows()
        if not exe:
            print(f"[Browser] ⚠️  Opera executable not found on Windows.")
        return {"engine": engine, "exe": exe, "channel": channel}

    for b in bins:
        found = shutil.which(b)
        if found:
            exe = found
            break

    if not exe and _OS == "Darwin":
        app_names = {
            "chrome":  ["Google Chrome.app"],
            "edge":    ["Microsoft Edge.app"],
            "firefox": ["Firefox.app"],
            "opera":   ["Opera.app", "Opera GX.app"],
            "brave":   ["Brave Browser.app"],
            "vivaldi": ["Vivaldi.app"],
        }
        for app in app_names.get(name, []):
            app_dir = Path("/Applications") / app / "Contents" / "MacOS"
            if app_dir.exists():
                found_bins = list(app_dir.iterdir())
                if found_bins:
                    exe = str(found_bins[0])
                    break

    if not exe and _OS == "Windows" and not channel:
        exe = _find_exe_windows(name)

    return {"engine": engine, "exe": exe, "channel": channel}


def _detect_default_browser() -> str:
    try:
        if _OS == "Windows":
            import winreg
            k = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\Shell\Associations"
                r"\UrlAssociations\http\UserChoice",
            )
            prog_id = winreg.QueryValueEx(k, "ProgId")[0].lower()
            winreg.CloseKey(k)
            for kw in ("edge", "firefox", "opera", "brave", "vivaldi", "chrome"):
                if kw in prog_id:
                    return kw
        elif _OS == "Darwin":
            out = subprocess.run(
                ["defaults", "read",
                 "com.apple.LaunchServices/com.apple.launchservices.secure",
                 "LSHandlers"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5,
            ).stdout.lower()
            for kw in ("firefox", "opera", "brave", "vivaldi", "safari", "chrome", "edge"):
                if kw in out:
                    return kw
        elif _OS == "Linux":
            out = subprocess.run(
                ["xdg-settings", "get", "default-web-browser"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5,
            ).stdout.lower()
            for kw in ("firefox", "opera", "brave", "vivaldi", "chrome", "edge"):
                if kw in out:
                    return kw
    except Exception:
        pass
    return "chrome"


_SEARCH_ENGINES: dict[str, str] = {
    "google":     "https://www.google.com/search?q=",
    "bing":       "https://www.bing.com/search?q=",
    "duckduckgo": "https://duckduckgo.com/?q=",
    "yandex":     "https://yandex.com/search/?text=",
}

_MAC_APP_NAMES: dict[str, str] = {
    "chrome":  "Google Chrome",
    "edge":    "Microsoft Edge",
    "firefox": "Firefox",
    "opera":   "Opera",
    "operagx": "Opera GX",
    "brave":   "Brave Browser",
    "vivaldi": "Vivaldi",
    "safari":  "Safari",
}

# Windows registry lookup names for browsers whose spec has no explicit binary
_WIN_EXE_HINTS: dict[str, str] = {"chrome": "chrome", "edge": "msedge"}


def _open_native(url: str, browser_name: Optional[str]) -> str:
    """
    Opens the user's REAL browser normally — with their own profile,
    logged-in accounts and extensions. No automation attaches, so an
    about:blank tab or a blank profile NEVER shows up.
    If url is empty the browser starts with no URL (its own start page /
    session restore) — exactly as if the user had opened it themselves.
    Works on all three of Windows / macOS / Linux.
    """
    try:
        url = _normalize_url(url) if url and url.strip() else ""
    except ValueError as exc:
        return outcome.failed("browser_control", str(exc))
    if url == "about:blank":
        url = ""

    name = None
    if browser_name:
        name = _ALIASES.get(browser_name.lower().strip(), browser_name.lower().strip())
    elif not url:
        # No URL → only a window will open; needs the default browser's exe
        name = _detect_default_browser()

    # Specific browser → launch its own executable, exactly like the user would.
    if name:
        if _OS == "Darwin":
            app = _MAC_APP_NAMES.get(name)
            if app:
                cmd = ["open", "-a", app] + ([url] if url else [])
                try:
                    subprocess.run(cmd, check=True, timeout=10)
                    return f"Opened in {name}: {url}" if url else f"Opened {name}."
                except Exception as e:
                    print(f"[Browser] 'open -a {app}' failed ({e}), trying binary…")

        spec = _resolve_browser(name)
        exe  = spec.get("exe") if spec else None
        if not exe and _OS == "Windows":
            if name in ("opera", "operagx"):
                exe = _find_opera_windows()
            else:
                exe = _find_exe_windows(_WIN_EXE_HINTS.get(name, name))
        if exe:
            try:
                subprocess.Popen(
                    [exe, url] if url else [exe],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                return f"Opened in {name}: {url}" if url else f"Opened {name}."
            except Exception as e:
                print(f"[Browser] Native launch failed for {name}: {e}")
        print(f"[Browser] '{name}' not found — falling back to default browser.")

    if not url:
        return outcome.failed(
            "browser_control",
            "no browser was found and no address was given to open")

    # Default browser via the OS — exactly like the user clicking a link.
    try:
        if _OS == "Windows":
            os.startfile(url)                       # ShellExecute → default browser
        elif _OS == "Darwin":
            subprocess.run(["open", url], check=True, timeout=10)
        else:
            subprocess.Popen(
                ["xdg-open", url],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        # HANDED TO THE OPERATING SYSTEM, NOT CONFIRMED.
        #
        # os.startfile / open / xdg-open all return as soon as the request is
        # accepted. None of them waits for a browser, and none reports whether
        # the page loaded — the same gap that made open_app say "Opened
        # Spotify." off the back of a shell starting. Unlike the playwright
        # path above there is no page object here to read a url from, so this
        # says what it actually knows.
        return outcome.unverified(
            "browser_control",
            "the address was handed to the system's default browser, which "
            "does not report back - the page is not confirmed open",
            url=url)
    except Exception:
        try:
            if webbrowser.open(url):
                return outcome.unverified(
                    "browser_control",
                    "the address was handed to the default browser, which does "
                    "not report back - the page is not confirmed open",
                    url=url)
        except Exception:
            pass
        return outcome.failed(
            "browser_control",
            "no browser on this system could be opened", url=url)


class _AmbiguousLocator(ValueError):
    """Raised when a semantic selector does not identify one element."""

    def __init__(self, description: str, count: int):
        self.count = count
        super().__init__(
            f"{description} matched {count} elements; refusing to guess"
        )

    @property
    def recovery(self) -> str:
        return "control_missing" if self.count == 0 else "target_ambiguous"


class _PageContextChanged(RuntimeError):
    """Raised when an interactive action's previously active page is gone."""


_INTERACTION_WINDOW_SECONDS = 30.0
_INTERACTION_MAXIMUM = 6


async def _require_unique(locator, description: str):
    """Return a locator only when it identifies exactly one element."""
    count = await locator.count()
    if count != 1:
        raise _AmbiguousLocator(description, count)
    return locator


class _BrowserSession:
    """
    A full session for one browser instance.
    All automated browsers use a dedicated profile via launch_persistent_context.
    """

    def __init__(self, browser_name: str):
        self.browser_name = browser_name
        self._spec        = _resolve_browser(browser_name)

        self._loop:    asyncio.AbstractEventLoop | None = None
        self._thread:  threading.Thread | None          = None
        self._ready    = threading.Event()

        self._pw:      Playwright     | None = None
        self._context: BrowserContext | None = None
        self._page:    Page           | None = None
        self.profile_kind: str = "separate"
        self._interaction_history: deque[float] = deque()
        self._interaction_lock = threading.Lock()
        self._run_state_lock = threading.Lock()
        self._active_future = None
        self._active_timed_out = False

    def _reserve_interaction(self, amount: int = 1) -> bool:
        now = time.monotonic()
        history = getattr(self, "_interaction_history", None)
        lock = getattr(self, "_interaction_lock", None)
        if history is None or lock is None:
            history = deque()
            lock = threading.Lock()
            self._interaction_history = history
            self._interaction_lock = lock
        with lock:
            while (
                history
                and now - history[0] >= _INTERACTION_WINDOW_SECONDS
            ):
                history.popleft()
            if amount < 1 or len(history) + amount > _INTERACTION_MAXIMUM:
                return False
            history.extend([now] * amount)
            return True

    def _interaction_limit_result(self) -> str:
        return outcome.failed(
            "browser_control",
            "browser interaction rate limit reached; no further effect was sent",
            maximum=_INTERACTION_MAXIMUM,
            window_seconds=_INTERACTION_WINDOW_SECONDS,
        )

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name=f"BrowserThread-{self.browser_name}",
        )
        self._thread.start()
        self._ready.wait(timeout=20)

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._async_init())
        self._ready.set()
        self._loop.run_forever()

    async def _async_init(self):
        # The one door into a live session: nothing in this class reaches
        # async_playwright or PlaywrightTimeout without coming through here
        # first, so binding them at this point is enough for the whole file.
        _load_playwright()
        self._pw = await async_playwright().start()

    def run(self, coro, timeout: int = 60) -> str:
        if not self._loop:
            raise RuntimeError(f"Session for '{self.browser_name}' not started.")
        with self._run_state_lock:
            active = self._active_future
            if active is not None and not active.done():
                close = getattr(coro, "close", None)
                if callable(close):
                    close()
                return outcome.unverified(
                    "browser_control",
                    "a browser operation is still running; no new operation "
                    "was sent",
                    recovery=(
                        "timeout"
                        if self._active_timed_out
                        else "effect_ambiguous"
                    ),
                )
            future = asyncio.run_coroutine_threadsafe(coro, self._loop)
            self._active_future = future
            self._active_timed_out = False
        try:
            return future.result(timeout=timeout)
        except _PageContextChanged:
            return outcome.failed(
                "browser_control",
                "the active page changed or disappeared; no action was sent",
                recovery="page_changed",
            )
        except concurrent.futures.TimeoutError:
            with self._run_state_lock:
                self._active_timed_out = not future.done()
            return outcome.unverified(
                "browser_control",
                "browser operation exceeded its time limit and may still be "
                "running; do not repeat it",
                recovery="timeout",
            )
        except Exception as exc:
            return outcome.unverified(
                "browser_control",
                "browser operation raised after dispatch may have begun "
                f"({type(exc).__name__}); do not repeat it",
                recovery="effect_ambiguous",
            )
        finally:
            if future.done():
                with self._run_state_lock:
                    if self._active_future is future:
                        self._active_future = None
                        self._active_timed_out = False

    def close(self):
        if self._loop:
            asyncio.run_coroutine_threadsafe(self._async_close(), self._loop).result(10)

    async def _async_close(self):
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
        if self._pw:
            try:
                await self._pw.stop()
            except Exception:
                pass
        self._context = self._page = None

    async def _adopt_page(self) -> Page:
        """
        launch_persistent_context already opens a starting tab.
        Instead of opening a new blank tab (about:blank), it adopts that tab —
        so the user never sees an extra blank tab.
        """
        await asyncio.sleep(0.3)
        pages = self._context.pages
        return pages[0] if pages else await self._context.new_page()

    async def _launch(self):
        """
        Launches the browser with a dedicated automation profile.
        Does nothing if the context is already open.
        """
        if self._context is not None:
            return

        if self._spec is None:
            raise RuntimeError(
                f"'{self.browser_name}' bu platformda ({_OS}) desteklenmiyor."
            )

        engine_name = self._spec["engine"]
        exe         = self._spec["exe"]
        channel     = self._spec["channel"]
        engine_obj  = getattr(self._pw, engine_name)

        if engine_name == "firefox":
            profile = _automation_profile_dir("firefox_" + self.browser_name)
            kwargs: dict = {
                "headless":    False,
                "slow_mo":     0,
                "viewport":    None,
                "no_viewport": True,
                "timeout":     25_000,
            }
            if exe:
                kwargs["executable_path"] = exe
            self._context = await engine_obj.launch_persistent_context(profile, **kwargs)
            self._page = await self._adopt_page()
            print(f"[Browser] ✅ Firefox launched with separate profile")
            return

        if engine_name == "webkit":
            safari_profile = str(Path.home() / ".jarvis_profiles" / "safari")
            Path(safari_profile).mkdir(parents=True, exist_ok=True)
            kwargs = {
                "headless":    False,
                "slow_mo":     0,
                "viewport":    None,
                "no_viewport": True,
                "timeout":     25_000,
            }
            self._context = await engine_obj.launch_persistent_context(safari_profile, **kwargs)
            self._page = await self._adopt_page()
            print(f"[Browser] ✅ Safari launched")
            return

        profile = _automation_profile_dir(self.browser_name)

        kwargs = {
            "headless":    False,
            "slow_mo":     0,
            "viewport":    None,
            "no_viewport": True,
            "timeout":     25_000,
            "args": [
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--disable-default-apps",
                "--no-default-browser-check",
            ],
        }

        if exe:
            kwargs["executable_path"] = exe
        elif channel:
            kwargs["channel"] = channel

        label = (
            f"{self.browser_name}"
            + (f"/{channel}" if channel else "")
            + (f" @ {exe}" if exe else "")
        )

        self._context = await engine_obj.launch_persistent_context(profile, **kwargs)
        self._page = await self._adopt_page()
        print(f"[Browser] ✅ Launched [{label}] with separate profile={profile}")


    async def _get_page(self, *, allow_new: bool = False) -> Page:
        await self._launch()
        try:
            page_missing = self._page is None or self._page.is_closed()
        except Exception as exc:
            raise _PageContextChanged(
                f"the active page state could not be read "
                f"({type(exc).__name__})"
            ) from None
        if page_missing:
            if not allow_new:
                raise _PageContextChanged(
                    "the active page closed or changed; no action was sent"
                )
            if self._context is None:
                raise RuntimeError("browser context is unavailable")
            self._page = await self._context.new_page()
            await asyncio.sleep(0.2)
        return self._page

    @staticmethod
    def _page_closed(page: Page) -> bool:
        try:
            return bool(page.is_closed())
        except (AttributeError, TypeError):
            return False

    async def go_to(self, url: str) -> str:
        if not isinstance(url, str) or not url.strip():
            return outcome.failed("browser_control", "url must be a non-empty string")
        url      = _normalize_url(url)
        page     = await self._get_page(allow_new=True)
        prev_url = page.url
        if not self._reserve_interaction():
            return self._interaction_limit_result()

        async def _do_goto(p: Page) -> tuple[str, str | None, bool]:
            """Attempt navigation and return its URL plus any non-timeout error."""
            try:
                await p.goto(url, wait_until="domcontentloaded", timeout=30_000)
                await asyncio.sleep(0.3)
            except PlaywrightTimeout:
                return p.url, None, True
            except Exception as e:
                print(f"[Browser] goto exception (non-fatal): {e}")
                return p.url, str(e), False
            return p.url, None, False

        result_url, navigation_error, navigation_timed_out = await _do_goto(page)

        if result_url in ("about:blank", "", None, prev_url) and prev_url in ("about:blank", "", None):
            print(f"[Browser] Still blank after goto — retrying on new tab: {url}")
            try:
                if not self._reserve_interaction():
                    return self._interaction_limit_result()
                new_page   = await self._context.new_page()
                self._page = new_page
                result_url, navigation_error, navigation_timed_out = await _do_goto(
                    new_page
                )
            except Exception as e:
                print(f"[Browser] New-tab retry failed: {e}")
                navigation_error = str(e)

        if navigation_error and result_url == prev_url:
            return outcome.failed(
                "browser_control",
                f"navigation failed: {navigation_error}",
                url=url,
                current_url=result_url,
            )

        if result_url and result_url not in ("about:blank", "", None):
            # Verified, and cheaply: this is the page's OWN url read back after
            # navigation, not the one we asked for. A redirect, a login wall or
            # a captive portal all show up here as a different address, which
            # is exactly what the user needs to hear about.
            #
            return outcome.unverified(
                "browser_control",
                f"the page opened at {result_url}, but automation always uses "
                f"a separate profile where the user is not signed in",
                opened=result_url,
                profile="separate",
                recovery=(
                    "timeout"
                    if navigation_timed_out
                    else "page_changed"
                    if result_url != url
                    else "effect_ambiguous"
                ),
            )
        return outcome.failed(
            "browser_control",
            "the page stayed blank - the address may be wrong, or the site may "
            "not have answered", url=url)

    async def search(self, query: str, engine: str = "google") -> str:
        base = _SEARCH_ENGINES.get(engine.lower(), _SEARCH_ENGINES["google"])
        return await self.go_to(base + query.replace(" ", "+"))

    async def click(self, selector: str = None, text: str = None) -> str:
        page = await self._get_page()
        page_url = page.url
        if not text and not selector:
            return outcome.failed(
                "browser_control",
                "no element was named to click",
            )
        if text and (
            not isinstance(text, str) or not text.strip() or len(text) > 500
        ):
            return outcome.failed(
                "browser_control",
                "click text must contain 1-500 characters",
            )
        if selector and (
            not isinstance(selector, str) or len(selector) > 500
        ):
            return outcome.failed(
                "browser_control",
                "click selector must contain at most 500 characters",
            )
        try:
            if text:
                locator = await _require_unique(
                    page.get_by_text(text, exact=False), "click text"
                )
            else:
                locator = await _require_unique(
                    page.locator(selector), "click selector"
                )
        except _AmbiguousLocator as exc:
            return outcome.failed(
                "browser_control",
                str(exc),
                recovery=exc.recovery,
            )
        except PlaywrightTimeout:
            return outcome.failed(
                "browser_control",
                "the click target could not be located before timeout",
                selector=selector or text,
                recovery="timeout",
            )
        except Exception as e:
            return outcome.failed(
                "browser_control",
                f"click target could not be inspected: {type(e).__name__}",
                recovery="state_unreadable",
            )
        if page.url != page_url:
            return outcome.failed(
                "browser_control",
                "page changed while locating the click target; no click was sent",
                before_url=page_url,
                current_url=page.url,
                recovery="page_changed",
            )
        if not self._reserve_interaction():
            return self._interaction_limit_result()
        try:
            await locator.click(timeout=8_000)
        except PlaywrightTimeout:
            return outcome.unverified(
                "browser_control",
                "click timed out after dispatch may have begun; do not repeat it",
                selector=selector or text,
                recovery="timeout",
            )
        except Exception as e:
            return outcome.unverified(
                "browser_control",
                f"click may have been dispatched before {type(e).__name__}; "
                "do not repeat it",
                recovery="effect_ambiguous",
            )
        return (
            f"Clicked text: '{text}'"
            if text
            else f"Clicked selector: {selector}"
        )

    async def type_text(self, selector: str = None, text: str = "",
                        clear_first: bool = True) -> str:
        page = await self._get_page()
        page_url = page.url
        try:
            if not isinstance(text, str) or len(text) > 10_000:
                return outcome.failed(
                    "browser_control",
                    "typed text must not exceed 10000 characters",
                )
            if selector:
                if not isinstance(selector, str) or len(selector) > 500:
                    return outcome.failed(
                        "browser_control",
                        "type selector must contain at most 500 characters",
                    )
                el = await _require_unique(
                    page.locator(selector), "type selector"
                )
            else:
                el = await _require_unique(page.locator(":focus"), "focused field")
        except _AmbiguousLocator as exc:
            return outcome.failed(
                "browser_control",
                str(exc),
                recovery=exc.recovery,
            )
        except PlaywrightTimeout:
            return outcome.failed(
                "browser_control",
                "the input target could not be located before timeout",
                recovery="timeout",
            )
        except Exception as e:
            return outcome.failed(
                "browser_control",
                f"input target could not be inspected: {type(e).__name__}",
                recovery="state_unreadable",
            )
        if page.url != page_url:
            return outcome.failed(
                "browser_control",
                "page changed while locating the input target; no text was sent",
                before_url=page_url,
                current_url=page.url,
                recovery="page_changed",
            )
        if not self._reserve_interaction():
            return self._interaction_limit_result()
        try:
            if clear_first:
                await el.clear()
            await el.type(text, delay=50)
        except PlaywrightTimeout:
            return outcome.unverified(
                "browser_control",
                "typing timed out after a field change may have begun; do not repeat it",
                recovery="timeout",
            )
        except Exception as e:
            return outcome.unverified(
                "browser_control",
                f"typing may have changed the field before {type(e).__name__}; "
                "do not repeat it",
                recovery="effect_ambiguous",
            )
        return outcome.done("browser_control", typed=True, verified=True)

    async def scroll(self, direction: str = "down", amount: int = 500) -> str:
        page = await self._get_page()
        page_url = page.url
        try:
            if direction not in {"up", "down"}:
                return outcome.failed(
                    "browser_control",
                    "scroll direction must be up or down",
                )
            if not isinstance(amount, int) or isinstance(amount, bool) or not 1 <= amount <= 2_000:
                return outcome.failed(
                    "browser_control",
                    "scroll amount must be an integer between 1 and 2000",
                )
            if not self._reserve_interaction():
                return self._interaction_limit_result()
            y = amount if direction == "down" else -amount
            await page.mouse.wheel(0, y)
            if self._page_closed(page):
                return outcome.failed(
                    "browser_control",
                    "scroll target page disappeared during the action",
                    recovery="page_changed",
                )
            if page.url != page_url:
                return outcome.unverified(
                    "browser_control",
                    "scroll completed but the page URL changed",
                    before_url=page_url,
                    current_url=page.url,
                    recovery="page_changed",
                )
            return f"Scrolled {direction}."
        except Exception as e:
            return outcome.unverified(
                "browser_control",
                f"scroll may have been sent before {type(e).__name__}; "
                "do not repeat it",
                recovery="effect_ambiguous",
            )

    async def press(self, key: str) -> str:
        page = await self._get_page()
        page_url = page.url
        try:
            if not isinstance(key, str) or not 1 <= len(key) <= 32:
                return outcome.failed(
                    "browser_control",
                    "key must contain 1-32 characters",
                )
            if not self._reserve_interaction():
                return self._interaction_limit_result()
            await page.keyboard.press(key)
            if self._page_closed(page):
                return outcome.failed(
                    "browser_control",
                    "key press target page disappeared during the action",
                    recovery="page_changed",
                )
            if page.url != page_url:
                return outcome.unverified(
                    "browser_control",
                    "key press completed but the page URL changed",
                    before_url=page_url,
                    current_url=page.url,
                    recovery="page_changed",
                )
            return f"Pressed: {key}"
        except Exception as e:
            return outcome.unverified(
                "browser_control",
                f"key press may have been sent before {type(e).__name__}; "
                "do not repeat it",
                recovery="effect_ambiguous",
            )

    async def get_text(self) -> str:
        page = await self._get_page()
        try:
            text = await page.inner_text("body")
            return json.dumps(
                {
                    "status": "done",
                    "action": "get_text",
                    "text": outcome.untrusted("webpage", text[:4_000]),
                    "verified": True,
                },
                ensure_ascii=False,
            )
        except Exception as e:
            return outcome.failed(
                "browser_control",
                "page text could not be read",
                action="get_text",
                error=type(e).__name__,
            )

    async def get_url(self) -> str:
        page = await self._get_page()
        return json.dumps(
            {
                "status": "done",
                "action": "get_url",
                "url": outcome.untrusted("webpage_url", page.url),
                "verified": True,
            },
            ensure_ascii=False,
        )

    async def fill_form(self, fields: dict) -> str:
        page    = await self._get_page()
        page_url = page.url
        completed_fields = 0
        if not isinstance(fields, dict) or not fields or len(fields) > 20:
            return outcome.failed(
                "browser_control",
                "form fields must be a non-empty object with at most 20 entries",
            )
        if len(fields) > _INTERACTION_MAXIMUM:
            return outcome.failed(
                "browser_control",
                "form exceeds the per-session interaction budget",
                maximum=_INTERACTION_MAXIMUM,
            )
        if not self._reserve_interaction(len(fields)):
            return self._interaction_limit_result()

        def stopped(
            field: int,
            reason: str,
            *,
            recovery: str | None = None,
            error: str | None = None,
            effect_started: bool = False,
        ) -> str:
            facts = {
                "action": "fill_form",
                "field": field,
                "changed_fields": completed_fields,
                "error": error,
            }
            if effect_started or completed_fields:
                return outcome.unverified(
                    "browser_control",
                    "form filling stopped; one or more fields may already "
                    "have changed",
                    recovery=recovery or "effect_ambiguous",
                    **facts,
                )
            return outcome.failed(
                "browser_control",
                reason,
                recovery=recovery,
                **facts,
            )

        for index, (selector, value) in enumerate(fields.items(), 1):
            effect_started = False
            try:
                if page.url != page_url:
                    return stopped(
                        index,
                        "page changed before the form field was modified",
                        recovery="page_changed",
                    )
                if not isinstance(selector, str) or len(selector) > 500:
                    raise ValueError("form selector must contain at most 500 characters")
                if not isinstance(value, str) or len(value) > 10_000:
                    raise ValueError("form value must contain at most 10000 characters")
                if action_policy.is_sensitive_name(selector):
                    return stopped(
                        index,
                        "credential and one-time-code fields cannot be filled "
                        "by the general form action",
                    )
                el = await _require_unique(page.locator(selector), "form selector")
                input_type = await el.get_attribute("type")
                autocomplete = set(
                    (await el.get_attribute("autocomplete") or "")
                    .casefold()
                    .split()
                )
                if (input_type or "").casefold() == "password" or (
                    autocomplete & {
                        "current-password",
                        "new-password",
                        "one-time-code",
                    }
                ):
                    return stopped(
                        index,
                        "credential and one-time-code fields cannot be filled "
                        "by the general form action",
                    )
                effect_started = True
                await el.clear()
                await el.type(value, delay=40)
                readback = await el.input_value()
                if readback != value:
                    return outcome.unverified(
                        "browser_control",
                        "a form field changed but its value could not be "
                        "verified; do not claim the form was filled",
                        action="fill_form",
                        field=index,
                        recovery="effect_ambiguous",
                    )
                completed_fields += 1
            except PlaywrightTimeout as exc:
                return stopped(
                    index,
                    "form field lookup timed out before it could be changed",
                    recovery="timeout",
                    error=type(exc).__name__,
                    effect_started=effect_started,
                )
            except _AmbiguousLocator as exc:
                return stopped(
                    index,
                    str(exc),
                    recovery=exc.recovery,
                    error=type(exc).__name__,
                )
            except Exception as exc:
                return stopped(
                    index,
                    "form filling stopped before any field was changed",
                    recovery="effect_ambiguous" if effect_started else None,
                    error=type(exc).__name__,
                    effect_started=effect_started,
                )
        return outcome.done(
            "browser_control",
            action="fill_form",
            fields=len(fields),
            verified=True,
        )

    async def smart_click(self, description: str) -> str:
        page = await self._get_page()
        page_url = page.url
        if not isinstance(description, str) or not description.strip() or len(description) > 500:
            return outcome.failed(
                "browser_control",
                "smart click description must contain 1-500 characters",
            )
        for role in ("button", "link", "searchbox", "textbox", "menuitem", "tab"):
            try:
                loc = page.get_by_role(role, name=description)
                count = await loc.count()
            except Exception:
                continue
            if count > 1:
                return outcome.failed(
                    "browser_control",
                    f"smart click role matched {count} elements; refusing to guess",
                    recovery="target_ambiguous",
                )
            if count == 1:
                if page.url != page_url:
                    return outcome.failed(
                        "browser_control",
                        "page changed while locating the smart click target; "
                        "no click was sent",
                        recovery="page_changed",
                    )
                if not self._reserve_interaction():
                    return self._interaction_limit_result()
                try:
                    await loc.click(timeout=5_000)
                except PlaywrightTimeout:
                    return outcome.unverified(
                        "browser_control",
                        "smart click timed out after dispatch may have begun; "
                        "do not repeat it",
                        recovery="timeout",
                    )
                except Exception as exc:
                    return outcome.unverified(
                        "browser_control",
                        "smart click may have been dispatched before "
                        f"{type(exc).__name__}; do not repeat it",
                        recovery="effect_ambiguous",
                    )
                return f"Clicked ({role}): '{description}'"
        for attempt in (
            lambda: page.get_by_text(description, exact=False),
            lambda: page.get_by_placeholder(description, exact=False),
            lambda: page.locator(
                f'[alt*="{description}" i],[title*="{description}" i],'
                f'[aria-label*="{description}" i]'
            ),
        ):
            try:
                candidate = attempt()
                count = await candidate.count()
            except _AmbiguousLocator as exc:
                return outcome.failed(
                    "browser_control",
                    str(exc),
                    recovery="target_ambiguous",
                )
            except Exception:
                continue
            if count > 1:
                return outcome.failed(
                    "browser_control",
                    f"smart click matched {count} elements; refusing to guess",
                    recovery="target_ambiguous",
                )
            if count == 0:
                continue
            if page.url != page_url:
                return outcome.failed(
                    "browser_control",
                    "page changed while locating the smart click target; "
                    "no click was sent",
                    recovery="page_changed",
                )
            if not self._reserve_interaction():
                return self._interaction_limit_result()
            try:
                await candidate.click(timeout=5_000)
            except PlaywrightTimeout:
                return outcome.unverified(
                    "browser_control",
                    "smart click timed out after dispatch may have begun; "
                    "do not repeat it",
                    recovery="timeout",
                )
            except Exception as exc:
                return outcome.unverified(
                    "browser_control",
                    "smart click may have been dispatched before "
                    f"{type(exc).__name__}; do not repeat it",
                    recovery="effect_ambiguous",
                )
            return f"Clicked: '{description}'"
        return outcome.failed(
            "browser_control",
            "no unique smart-click target was found",
            recovery="control_missing",
        )

    async def smart_type(self, description: str, text: str) -> str:
        page = await self._get_page()
        page_url = page.url
        if (
            not isinstance(description, str)
            or not description.strip()
            or len(description) > 500
            or not isinstance(text, str)
            or len(text) > 10_000
        ):
            return outcome.failed(
                "browser_control",
                "smart type description/text exceeds the allowed limits",
            )
        candidates = [
            ("placeholder", page.get_by_placeholder(description, exact=False)),
            ("label",       page.get_by_label(description, exact=False)),
            ("role",        page.get_by_role("textbox", name=description)),
            ("searchbox",   page.get_by_role("searchbox")),
            ("combobox",    page.get_by_role("combobox", name=description)),
        ]
        for method, loc in candidates:
            try:
                count = await loc.count()
            except Exception:
                continue
            if count > 1:
                return outcome.failed(
                    "browser_control",
                    f"smart type {method} matched {count} elements; refusing to guess",
                    recovery="target_ambiguous",
                )
            if count == 0:
                continue
            if page.url != page_url:
                return outcome.failed(
                    "browser_control",
                    "page changed while locating the smart type target; "
                    "no text was sent",
                    recovery="page_changed",
                )
            if not self._reserve_interaction():
                return self._interaction_limit_result()
            try:
                await loc.clear()
                await loc.type(text, delay=50)
            except PlaywrightTimeout:
                return outcome.unverified(
                    "browser_control",
                    "smart typing timed out after a field change may have begun; "
                    "do not repeat it",
                    recovery="timeout",
                )
            except Exception as exc:
                return outcome.unverified(
                    "browser_control",
                    "smart typing may have changed the field before "
                    f"{type(exc).__name__}; do not repeat it",
                    recovery="effect_ambiguous",
                )
            return f"Typed into ({method}): '{description}'"
        return outcome.failed(
            "browser_control",
            "no unique smart-typing target was found",
            recovery="control_missing",
        )

    async def new_tab(self, url: str = "") -> str:
        if not self._reserve_interaction():
            return self._interaction_limit_result()
        if self._page is None or self._page.is_closed():
            await self._get_page(allow_new=True)
            if url:
                return await self.go_to(url)
            return "New tab opened."
        page = await self._get_page()
        ctx  = page.context
        new  = await ctx.new_page()
        self._page = new
        if url:
            return await self.go_to(url)
        return "New tab opened."

    async def close_tab(self) -> str:
        page = self._page
        if page and not page.is_closed():
            if not self._reserve_interaction():
                return self._interaction_limit_result()
            ctx   = page.context
            await page.close()
            pages = ctx.pages
            self._page = pages[-1] if pages else None
            return "Tab closed."
        return "No active tab to close."

    async def screenshot(self, path: str = None) -> str:
        page = await self._get_page()
        try:
            save_path = path or str(Path.home() / "Desktop" / "jarvis_screenshot.png")
            await page.screenshot(path=save_path, full_page=False)
            return f"Screenshot saved: {save_path}"
        except Exception as e:
            return f"Screenshot error: {e}"

    async def back(self) -> str:
        page = await self._get_page()
        try:
            if not self._reserve_interaction():
                return self._interaction_limit_result()
            await page.go_back(timeout=10_000)
            if self._page_closed(page):
                return outcome.failed(
                    "browser_control",
                    "back navigation target page disappeared",
                    recovery="page_changed",
                )
            return outcome.unverified(
                "browser_control",
                "back navigation completed; verify the destination before continuing",
                current_url=page.url,
                recovery="page_changed",
            )
        except Exception as e:
            return outcome.unverified(
                "browser_control",
                f"back navigation may have changed the page before "
                f"{type(e).__name__}; do not repeat it",
                recovery="effect_ambiguous",
            )

    async def forward(self) -> str:
        page = await self._get_page()
        try:
            if not self._reserve_interaction():
                return self._interaction_limit_result()
            await page.go_forward(timeout=10_000)
            if self._page_closed(page):
                return outcome.failed(
                    "browser_control",
                    "forward navigation target page disappeared",
                    recovery="page_changed",
                )
            return outcome.unverified(
                "browser_control",
                "forward navigation completed; verify the destination before continuing",
                current_url=page.url,
                recovery="page_changed",
            )
        except Exception as e:
            return outcome.unverified(
                "browser_control",
                f"forward navigation may have changed the page before "
                f"{type(e).__name__}; do not repeat it",
                recovery="effect_ambiguous",
            )

    async def reload(self) -> str:
        page = await self._get_page()
        try:
            if not self._reserve_interaction():
                return self._interaction_limit_result()
            await page.reload(timeout=15_000)
            if self._page_closed(page):
                return outcome.failed(
                    "browser_control",
                    "reload target page disappeared",
                    recovery="page_changed",
                )
            return outcome.unverified(
                "browser_control",
                "reload completed; verify the page state before continuing",
                current_url=page.url,
                recovery="page_changed",
            )
        except Exception as e:
            return outcome.unverified(
                "browser_control",
                f"reload may have changed the page before {type(e).__name__}; "
                "do not repeat it",
                recovery="effect_ambiguous",
            )

    async def close_browser(self) -> str:
        await self._async_close()
        return f"{self.browser_name} closed."

class _SessionRegistry:
    """Manages all active browser sessions."""

    def __init__(self):
        self._sessions:        dict[str, _BrowserSession] = {}
        self._active_browser:  str                        = ""
        self._lock             = threading.Lock()
        self._last_native_url: str                        = ""

    def has(self, browser_name: str | None = None) -> bool:
        """Is there an active automation session for this browser (or any)?"""
        with self._lock:
            if not browser_name:
                return bool(self._sessions)
            name = _ALIASES.get(browser_name.lower().strip(), browser_name.lower().strip())
            return name in self._sessions

    def note_native_url(self, url: str) -> None:
        self._last_native_url = url

    def pop_native_url(self) -> str:
        """Returns the last natively-opened URL once (consumed to avoid repeats)."""
        url, self._last_native_url = self._last_native_url, ""
        return url

    def _get_or_create(self, browser_name: str) -> _BrowserSession:
        with self._lock:
            if browser_name not in self._sessions:
                sess = _BrowserSession(browser_name)
                sess.start()
                self._sessions[browser_name] = sess
                print(f"[Registry] New session: {browser_name}")
            return self._sessions[browser_name]

    def get(self, browser_name: str | None = None) -> _BrowserSession:
        if not browser_name:
            browser_name = self._active_browser or _detect_default_browser()
        browser_name = _ALIASES.get(browser_name.lower().strip(), browser_name.lower().strip())
        sess = self._get_or_create(browser_name)
        self._active_browser = browser_name
        return sess

    def switch(self, browser_name: str) -> str:
        browser_name = _ALIASES.get(browser_name.lower().strip(), browser_name.lower().strip())
        self._get_or_create(browser_name)
        self._active_browser = browser_name
        return f"Active browser → {browser_name}"

    def close_one(self, browser_name: str) -> str:
        with self._lock:
            sess = self._sessions.pop(browser_name, None)
        if sess:
            sess.close()
            if self._active_browser == browser_name:
                self._active_browser = ""
            return f"{browser_name} closed."
        return f"No active session for: {browser_name}"

    def close_all(self) -> str:
        with self._lock:
            names    = list(self._sessions.keys())
            sessions = list(self._sessions.values())
            self._sessions.clear()
            self._active_browser = ""
        for s in sessions:
            try:
                s.close()
            except Exception:
                pass
        return "All browsers closed: " + (", ".join(names) if names else "none")

    def list_sessions(self) -> str:
        with self._lock:
            if not self._sessions:
                return "No active browser sessions."
            lines = []
            for name in self._sessions:
                marker = " ◀ active" if name == self._active_browser else ""
                lines.append(f"  • {name}{marker}")
            return "Open browsers:\n" + "\n".join(lines)


_registry = _SessionRegistry()

def browser_control(
    parameters:    dict = None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params  = parameters or {}
    action  = str(params.get("action") or "").lower().strip()
    browser = params.get("browser", "").lower().strip() or None
    result  = "Unknown action."

    # Older prompts sometimes call URL navigation "open". Keep that common
    # wording safe and deterministic rather than falling through to Playwright.
    if action == "open":
        if not str(params.get("url") or "").strip():
            return "Cannot open a browser page without a URL."
        action = "go_to"

    if action == "switch":
        target = browser or params.get("target", "").lower().strip()
        result = _registry.switch(target) if target else "Please specify a browser."
        _log(player, result)
        return result

    if action == "list_browsers":
        result = _registry.list_sessions()
        _log(player, result)
        return result

    if action == "close_all":
        result = _registry.close_all()
        _log(player, result)
        return result

    if action == "close":
        target = browser or _registry._active_browser
        result = _registry.close_one(target) if target else "No browser specified."
        _log(player, result)
        return result

    # ── Navigation is ALWAYS native ──────────────────────────────────────────
    # go_to / search / new_tab open the site in the user's own browser —
    # their own profile, logged-in accounts and start page; exactly as if the
    # user had opened it themselves. A controlled window with about:blank never
    # opens here. The only exception: if an automation flow is already running,
    # navigation continues in that window (so multi-step tasks aren't split).
    if action in ("go_to", "search", "new_tab"):
        if _registry.has(browser):
            sess = _registry.get(browser)
            try:
                if action == "search":
                    result = sess.run(sess.search(params.get("query", ""),
                                                  params.get("engine", "google")))
                elif action == "new_tab":
                    result = sess.run(sess.new_tab(params.get("url", "")))
                else:
                    result = sess.run(sess.go_to(params.get("url", "")))
            except concurrent.futures.TimeoutError:
                result = f"Browser action '{action}' timed out (60s)."
            except Exception as e:
                result = f"Browser error ({action}): {e}"
            _log(player, result)
            return result

        if action == "search":
            base    = _SEARCH_ENGINES.get(params.get("engine", "google").lower(),
                                          _SEARCH_ENGINES["google"])
            nav_url = base + params.get("query", "").replace(" ", "+")
        else:
            nav_url = params.get("url", "").strip()

        result = _open_native(nav_url, browser)
        if result.startswith("Opened") and nav_url:
            _registry.note_native_url(_normalize_url(nav_url))
        _log(player, result)
        return result

    # ── Interactive actions (click/type/read…) ───────────────────────────────
    # These require a physically controllable browser; the automation window
    # only opens here, and as soon as it opens it goes to the user's last
    # navigated page — it doesn't sit on a blank page.
    try:
        sess = _registry.get(browser)
    except Exception as e:
        result = f"Could not start browser session: {e}"
        _log(player, result)
        return result

    try:
        last = _registry.pop_native_url()
        if last:
            try:
                sess.run(sess.go_to(last))
            except Exception as e:
                print(f"[Browser] Could not resume last page ({last}): {e}")

        if action == "click":
            result = sess.run(sess.click(params.get("selector"), params.get("text")))
        elif action == "type":
            result = sess.run(sess.type_text(
                params.get("selector"), params.get("text", ""), params.get("clear_first", True)))
        elif action == "scroll":
            result = sess.run(sess.scroll(params.get("direction", "down"), int(params.get("amount", 500))))
        elif action == "fill_form":
            result = sess.run(sess.fill_form(params.get("fields", {})))
        elif action == "smart_click":
            result = sess.run(sess.smart_click(params.get("description", "")))
        elif action == "smart_type":
            result = sess.run(sess.smart_type(params.get("description", ""), params.get("text", "")))
        elif action == "get_text":
            result = sess.run(sess.get_text())
        elif action == "get_url":
            result = sess.run(sess.get_url())
        elif action == "press":
            result = sess.run(sess.press(params.get("key", "Enter")))
        elif action == "close_tab":
            result = sess.run(sess.close_tab())
        elif action == "screenshot":
            result = sess.run(sess.screenshot(params.get("path")))
        elif action == "back":
            result = sess.run(sess.back())
        elif action == "forward":
            result = sess.run(sess.forward())
        elif action == "reload":
            result = sess.run(sess.reload())
        else:
            result = f"Unknown browser action: '{action}'"

    except concurrent.futures.TimeoutError:
        result = f"Browser action '{action}' timed out (60s)."
    except Exception as e:
        result = f"Browser error ({action}): {e}"

    _log(player, result)
    return result


def _log(player, text: str):
    short = str(text)[:80]
    print(f"[Browser] {short}")
    if player:
        print(f"[Browser] {short[:80]}")          # terminal, not the HUD


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "browser_control",
    "description": (
        "Controls the web browser: open or navigate to an address (use "
        "action='go_to'), search, click, type, "
        "scroll, read the page, manage tabs, go back and forward. "
        "THIS TOOL OPENS THE BROWSER ITSELF. Never call open_app for the "
        "browser first - doing both launches it twice, the second copy on a "
        "different profile with none of the user's sign-ins. 'Open Chrome and "
        "go to YouTube' is ONE call to this tool. "
        "Read the status it returns. 'done' means it was confirmed - for an "
        "open, the url reported back is the page's OWN address, so if it "
        "differs from what was asked for the site redirected and the user "
        "should be told. 'unverified' means the address was handed to the "
        "system's default browser, which never reports back: say it was opened "
        "but not confirmed, never that the page is up. 'failed' means nothing "
        "happened."
    ),
    "brief": (
        "Controls the web browser: open a URL, navigate, click, read the page."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "go_to | search | click | type | scroll | fill_form | smart_click | smart_type | get_text | get_url | press | new_tab | close_tab | screenshot | back | forward | reload | switch | list_browsers | close | close_all"
            },
            "browser": {
                "type": "STRING",
                "description": "Target browser: chrome | edge | firefox | opera | operagx | brave | vivaldi | safari. Omit to use the currently active browser."
            },
            "url": {
                "type": "STRING",
                "description": "URL for go_to / new_tab action"
            },
            "query": {
                "type": "STRING",
                "description": "Search query for search action"
            },
            "engine": {
                "type": "STRING",
                "description": "Search engine: google | bing | duckduckgo | yandex (default: google)"
            },
            "selector": {
                "type": "STRING",
                "description": "CSS selector for click/type"
            },
            "text": {
                "type": "STRING",
                "description": "Text to click or type"
            },
            "description": {
                "type": "STRING",
                "description": "Element description for smart_click/smart_type"
            },
            "direction": {
                "type": "STRING",
                "description": "up | down for scroll"
            },
            "amount": {
                "type": "INTEGER",
                "description": "Scroll amount in pixels (default: 500)"
            },
            "key": {
                "type": "STRING",
                "description": "Key name for press action (e.g. Enter, Escape, F5)"
            },
            "path": {
                "type": "STRING",
                "description": "Save path for screenshot"
            },
            "incognito": {
                "type": "BOOLEAN",
                "description": "Open in private/incognito mode"
            },
            "clear_first": {
                "type": "BOOLEAN",
                "description": "Clear field before typing (default: true)"
            }
        },
        "required": [
            "action"
        ]
    },
    "handler": browser_control,
}
