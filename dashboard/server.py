"""
dashboard/server.py — JARVIS Local HTTP Dashboard

HTTPS on port 8000 with a self-signed certificate generated on first run, plus
a second layer inside it: commands are encrypted with AES-256-GCM under a key
derived from the pairing code with PBKDF2. Both layers are required — the
server refuses to start without TLS rather than quietly serving in clear.

Install deps:  pip install fastapi "uvicorn[standard]" cryptography
"""

import asyncio
import base64
import hashlib
import json
import re
import secrets
import socket
import string
import threading
import time
from pathlib import Path

_DEPS_OK = False
try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
    from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
    import uvicorn
    _DEPS_OK = True
except ImportError:
    pass

# python-multipart is required for file uploads — optional dependency
_UPLOAD_OK = False
try:
    from fastapi import UploadFile, File as FastAPIFile
    _UPLOAD_OK = True
except Exception:
    pass

BASE_DIR    = Path(__file__).resolve().parent.parent
STATIC_DIR  = Path(__file__).parent / "static"
# The port people TYPE, and the port the app actually runs on.
#
# They are not the same, and that is the fix for the most confusing failure
# this dashboard had. A bare `192.168.1.108:8000` typed into a phone browser is
# tried over HTTP; against a TLS listener that means the connection is accepted,
# found to carry no handshake, and closed — which Chrome reports as "refused to
# connect". The server is running perfectly and the user is told it is off.
#
# So the port people reach for answers in the protocol they reach for it with,
# and sends them one hop to the secure one. The QR code carries the secure URL
# directly, so it never takes the hop.
PORT        = 8000      # HTTP, redirects to SECURE_PORT
SECURE_PORT = 8001      # HTTPS, the dashboard itself
MAX_UPLOAD_MB = 500
_MAX_COMMAND_CHARS = 4_000
_MAX_COMMAND_BYTES = 16 * 1024
_MAX_COMMAND_BODY_BYTES = 32 * 1024
_COMMANDS_PER_MINUTE = 30
_COMMAND_QUEUE_SIZE = 100
_DEVICE_LOGINS_PER_MINUTE = 10
_DEVICE_LOGIN_BODY_BYTES = 1_024
_LOGIN_BODY_BYTES = 1_024


def _make_uploads_dir() -> Path:
    """Return (and create) the cross-platform uploads folder."""
    for candidate in [
        Path.home() / "Downloads" / "JARVIS Uploads",
        Path.home() / "Documents" / "JARVIS Uploads",
        BASE_DIR / "uploads",
    ]:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except Exception:
            pass
    return BASE_DIR / "uploads"


UPLOADS_DIR = _make_uploads_dir()

def _get_gemini_key() -> str | None:
    from memory.config_manager import get_gemini_key

    return get_gemini_key()

_KEY_CHARS = [c for c in (string.ascii_uppercase + string.digits)
              if c not in ('O', 'I', 'L', '0', '1')]

# ── AES-256-CBC ───────────────────────────────────────────────────────────────
_AES_SALT = b'JARVIS-DASHBOARD-v1'


# Rounds for the pairing key -> AES key derivation.
#
# WHY THIS IS NOT ONE ROUND OF SHA-256, WHICH IS WHAT IT WAS
#     The pairing key is short because a person has to read it off a screen and
#     type it into a phone. Eight characters from a 31-letter alphabet is about
#     forty bits — fine against someone guessing at the login endpoint, which
#     is rate limited below, and NOT fine against someone who captured one
#     encrypted command and can guess offline as fast as their GPU allows.
#
#     At one round of SHA-256 that offline search is seconds. PBKDF2 at 200k
#     rounds makes each guess about five orders of magnitude more expensive
#     while costing this server ~80 ms once per session, at pairing time, where
#     nobody is waiting on a millisecond.
_KDF_ROUNDS = 200_000


def _derive_key(session_key: str) -> bytes:
    """Pairing key → 32-byte AES-256 key, deliberately slowly. See _KDF_ROUNDS."""
    return hashlib.pbkdf2_hmac(
        "sha256", session_key.encode("utf-8"), _AES_SALT, _KDF_ROUNDS, dklen=32
    )


def _decrypt(aes_key: bytes, enc_b64: str) -> str:
    """Decrypt base64(nonce[12] ‖ ciphertext‖tag) with AES-256-GCM.

    GCM RATHER THAN THE CBC THIS REPLACES
        CBC has no authentication. It hides a message and does nothing to stop
        one being CHANGED: an attacker on the same network can flip bits in the
        ciphertext and the server decrypts whatever falls out, with no way to
        tell. For a channel whose whole purpose is carrying commands to an
        assistant that opens applications and sends messages, "the text was
        secret" is the smaller half of what matters — "the text is the one that
        was sent" is the other half, and CBC never provided it.

        GCM authenticates as it decrypts. A single altered byte raises
        InvalidTag and the request is refused rather than obeyed.

    The old CBC path is not kept as a fallback on purpose. An attacker who can
    choose which format the server accepts can simply choose the weak one, and
    a downgrade left available is a downgrade that will be used.
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    raw = base64.b64decode(enc_b64)
    if len(raw) < 13:
        raise ValueError("ciphertext too short to contain a nonce")
    nonce, payload = raw[:12], raw[12:]
    return AESGCM(aes_key).decrypt(nonce, payload, None).decode("utf-8")


_BLOCK_CACHE = None


def blocking_firewall_rules() -> list:
    """Inbound Windows BLOCK rules aimed at the interpreter running this app.

    Public, read-only and never elevated, so the interface can warn about the
    one failure that is invisible from inside the app: a block rule overrides
    every allow rule, so the server listens correctly and the phone still
    cannot reach it. Empty on every other platform and whenever nothing is
    blocked.

    -> [(rule name, program path), ...]
    """
    import sys
    if sys.platform != "win32":
        return []

    # Cached for the process. Reading every inbound rule costs about a second,
    # and this is called from the Qt thread when the Remote Control panel
    # opens — a second of frozen interface every time, for an answer that only
    # changes when somebody edits their firewall.
    global _BLOCK_CACHE
    if _BLOCK_CACHE is not None:
        return _BLOCK_CACHE
    import os
    import subprocess

    py_exe = sys.executable
    sibling = os.path.join(
        os.path.dirname(py_exe),
        "pythonw.exe" if py_exe.lower().endswith("python.exe") else "python.exe")
    wanted = {py_exe.lower()}
    if os.path.exists(sibling):
        wanted.add(sibling.lower())

    found: list = []
    try:
        r = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule",
             "name=all", "dir=in", "verbose"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=20,
        )
        name = program = None
        for line in r.stdout.splitlines():
            if line.startswith("Rule Name:"):
                name = line.split(":", 1)[1].strip()
                program = None
            elif line.startswith("Program:"):
                program = line.split(":", 1)[1].strip().lower()
            elif line.startswith("Action:"):
                if (name and program and program in wanted
                        and line.split(":", 1)[1].strip().lower() == "block"
                        and (name, program) not in found):
                    found.append((name, program))
    except Exception as exc:
        print(f"[Dashboard] could not read the firewall rules: {exc}")
    _BLOCK_CACHE = found
    return found


def _local_ip() -> str:
    """Return the best LAN-facing IPv4 address, no internet required."""
    # Method 1: route trick (fast, works when internet is available)
    for probe in ("8.8.8.8", "1.1.1.1", "192.168.1.1"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.5)
            s.connect((probe, 80))
            ip = s.getsockname()[0]
            s.close()
            if not ip.startswith("127."):
                return ip
        except Exception:
            pass

    # Method 2: hostname resolution (works offline on most systems)
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if not ip.startswith("127."):
            return ip
    except Exception:
        pass

    # Method 3: enumerate all interfaces (fully offline, no external deps)
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and not ip.startswith("169.254."):
                return ip
    except Exception:
        pass

    return "127.0.0.1"


def _ensure_certs() -> bool:
    """
    Make sure config/certs holds a TLS key pair, generating a self-signed one the
    first time the dashboard runs.

    The pair is deliberately NOT shipped in the repository. A private key that
    every user downloads is the same as having no private key at all: anyone can
    present a certificate that matches it. Generating locally gives each install
    its own key, costs about a second, and happens exactly once.

    Returns True when a usable pair exists afterwards. HTTPS callers must not
    fall back to cleartext if certificate generation fails.
    """
    certs = BASE_DIR / "config" / "certs"
    key_p = certs / "jarvis.key"
    crt_p = certs / "jarvis.crt"
    if key_p.exists() and crt_p.exists():
        return True

    try:
        import datetime
        import ipaddress
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError:
        print("[Dashboard] cryptography not installed — cannot serve HTTPS.")
        print("[Dashboard] For HTTPS run:  pip install cryptography")
        return False

    try:
        certs.mkdir(parents=True, exist_ok=True)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

        who = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "JARVIS Dashboard"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "JARVIS"),
        ])

        # The SAN has to cover every address the phone might use: the LAN IP the
        # QR code encodes, plus localhost when testing on the machine itself.
        alt = [x509.DNSName("localhost"),
               x509.IPAddress(ipaddress.IPv4Address("127.0.0.1"))]
        try:
            lan = _local_ip()
            if not lan.startswith("127."):
                alt.append(x509.IPAddress(ipaddress.IPv4Address(lan)))
        except Exception:
            pass          # no LAN address resolvable — localhost entries still work

        # Timezone-aware UTC: datetime.utcnow() is deprecated from Python 3.12 on,
        # and the builder normalises aware values to UTC itself.
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(who)
            .issuer_name(who)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName(alt), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(key, hashes.SHA256())
        )

        key_p.write_bytes(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))
        crt_p.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

        try:
            import os as _os
            _os.chmod(key_p, 0o600)   # best effort — largely a no-op on Windows
        except Exception:
            pass

        print(f"[Dashboard] Generated a self-signed certificate for this machine: {certs}")
        return True
    except Exception as e:
        print(f"[Dashboard] Certificate generation failed ({e}).")
        return False


def _read(name: str) -> str:
    return (STATIC_DIR / name).read_text(encoding="utf-8")


def _dashboard_language() -> str:
    try:
        from memory.config_manager import get_language
        return get_language()
    except Exception as exc:
        print(f"[Dashboard] Could not load the saved language preference: {exc}")
        return "auto"


def _localize_dashboard(html: str, language: str) -> str:
    if language != "es":
        return html
    translations = {
        "JARVIS Dashboard": "Panel de JARVIS",
        "Remote Access": "Acceso remoto",
        "Reconnecting…": "Reconectando…",
        "Press ": "Pulsa ",
        "Remote Control": "Control remoto",
        " in the JARVIS desktop app to get a QR code or session key.":
            " en la aplicación de escritorio JARVIS para obtener un código QR o una clave de sesión.",
        "CONNECT": "CONECTAR",
        "Connection error": "Error de conexión",
        "Invalid or expired key": "Clave no válida o caducada",
        "Voice commands:": "Órdenes por voz:",
        " open": " abre",
        " on your phone, search": " en tu teléfono, busca",
        ", add your JARVIS URL, tap Relaunch.":
            ", añade la dirección de JARVIS y pulsa Reiniciar.",
        "Relaunch": "Reiniciar",
        "Insecure origins treated as secure":
            "Insecure origins treated as secure (orígenes no seguros como seguros)",
        "Connecting": "Conectando",
        "Active": "Activo",
        "Sleeping": "En reposo",
        "Send a command to JARVIS…": "Envía una orden a JARVIS…",
        "Send file": "Enviar archivo",
        "Voice command": "Orden por voz",
        "WAKE": "DESPERTAR",
        "SEND": "ENVIAR",
        '<div class="lbl">You</div>': '<div class="lbl">Tú</div>',
        "Remote session active.": "Sesión remota activa.",
        "Connected to JARVIS": "Conectado a JARVIS",
        "Connection lost — refresh to reconnect.":
            "Se perdió la conexión; actualiza la página para conectarte de nuevo.",
        "Wake word detected — connecting…":
            "Se detectó la palabra de activación; conectando…",
        "Sending": "Enviando",
        "Sent": "Enviado",
        "Received": "Recibido",
        "⬇ Download back": "⬇ Descargar de nuevo",
        "⬇ Download": "⬇ Descargar",
        "Upload failed": "Error al subir el archivo",
        "File sent!": "¡Archivo enviado!",
        "One-time voice setup": "Configuración de voz (solo una vez)",
        "Open a new tab → go to ": "Abre otra pestaña y ve a ",
        "Search: ": "Busca: ",
        "Paste this URL into the box:": "Pega esta dirección en el cuadro:",
        "Enabled": "Activado",
        "Return here and tap 🎤": "Vuelve aquí y pulsa 🎤",
        "Set to ": "Selecciona ",
    }
    for source, translated in translations.items():
        html = html.replace(source, translated)
    return html


# ── DashboardServer ───────────────────────────────────────────────────────────

# How long an auth token stays valid, and how many failed logins an address
# gets before it has to wait.
#
# The old code had neither. A token, once issued, worked until the process
# ended — no expiry, no logout — and /login accepted unlimited guesses at the
# pairing key as fast as a script could send them. Eight characters is a large
# space, but "large" is not the same as "let them try forever": the point of a
# limit is that an attacker's cost grows while a person who mistypes their key
# twice never notices it exists.
_TOKEN_TTL_SECONDS = 12 * 3600
_LOGIN_MAX_TRIES   = 6
_LOGIN_WINDOW      = 300.0      # seconds the counter looks back over
_LOGIN_LOCKOUT     = 300.0      # seconds an address waits after using them up


class _Throttle:
    """Failed-attempt counter, per client address.

    Deliberately tiny and in memory: it protects a pairing key that is itself
    only alive for ten minutes, so nothing here needs to survive a restart.
    Successful logins clear the count, which keeps a household on one address
    from locking itself out because somebody fumbled the code once.
    """

    def __init__(self):
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def blocked_for(self, who: str) -> float:
        """Seconds this address must wait, or 0."""
        now = time.time()
        with self._lock:
            tries = [t for t in self._fails.get(who, []) if now - t < _LOGIN_WINDOW]
            self._fails[who] = tries
            if len(tries) < _LOGIN_MAX_TRIES:
                return 0.0
            return max(0.0, _LOGIN_LOCKOUT - (now - tries[-1]))

    def record_failure(self, who: str) -> None:
        with self._lock:
            self._fails.setdefault(who, []).append(time.time())

    def clear(self, who: str) -> None:
        with self._lock:
            self._fails.pop(who, None)


class _CommandThrottle:
    """Bound remote requests per client address."""

    def __init__(self, limit: int):
        self._limit = limit
        self._commands: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def consume(self, who: str) -> bool:
        now = time.time()
        with self._lock:
            for address, timestamps in list(self._commands.items()):
                active = [t for t in timestamps if now - t < 60.0]
                if active:
                    self._commands[address] = active
                else:
                    self._commands.pop(address, None)
            timestamps = self._commands.get(who, [])
            if len(timestamps) >= self._limit:
                return False
            timestamps.append(now)
            self._commands[who] = timestamps
            return True


class DashboardServer:

    def __init__(self):
        self._ip                          = _local_ip()
        # token -> issued-at. A set had no way to expire anything; this does,
        # and `_auth` sweeps as it reads so nothing has to run a timer.
        self._tokens: dict[str, float]    = {}
        self._token_keys: dict[str, str]  = {}   # auth_token → session_key
        self._aes_cache:  dict[str, bytes]= {}   # session_key → AES bytes
        self._clients: set[WebSocket]     = set()
        self._history: list[dict]         = []
        self._command_queue               = asyncio.Queue(maxsize=_COMMAND_QUEUE_SIZE)
        self._command_throttle            = _CommandThrottle(_COMMANDS_PER_MINUTE)
        self._device_login_throttle       = _CommandThrottle(
            _DEVICE_LOGINS_PER_MINUTE
        )
        self._wake_callback               = None
        self._connect_callback            = None
        self._pending_keys: dict[str, float] = {}
        self._throttle                    = _Throttle()
        self._device_sessions: dict[str, dict] = {}  # device_token → {session_key}
        self._phone_audio_queue: asyncio.Queue    = asyncio.Queue(maxsize=200)
        self._uploads_dir                 = UPLOADS_DIR
        # Set by serve() when the port could not be taken, so the UI can say
        # why the QR code leads nowhere instead of showing it regardless.
        self._bind_error: str = ""
        self._login_html                  = _read("login.html")
        self._app_html                    = _read("app.html")
        self.app                          = self._build_app()

    # ── one-time key management ───────────────────────────────────────────

    def new_key(self, expiry_secs: int = 600) -> str:
        now = time.time()
        self._pending_keys = {k: v for k, v in self._pending_keys.items() if v > now}
        key = ''.join(secrets.choice(_KEY_CHARS) for _ in range(8))
        self._pending_keys[key] = now + expiry_secs
        return key

    @staticmethod
    def _https_requested() -> bool:
        """HTTPS is the default; HTTP requires an explicit false setting."""
        try:
            import json as _json
            with open(BASE_DIR / "config" / "api_keys.json", "r",
                      encoding="utf-8") as f:
                settings = _json.load(f)
                if isinstance(settings, dict):
                    return settings.get("dashboard_https", True) is not False
                return True
        except (OSError, ValueError):
            return True

    @staticmethod
    def _ssl_enabled() -> bool:
        """Use TLS unless the user explicitly opted into cleartext HTTP."""
        return DashboardServer._https_requested()

    def get_url(self) -> str:
        """The full URL the QR code carries — always with its scheme, so a
        scanner never has to guess."""
        if self._ssl_enabled():
            return f"https://{self._ip}:{SECURE_PORT}"
        return f"http://{self._ip}:{PORT}"

    def get_manual_url(self) -> str:
        """What to type into a phone browser by hand.

        Points at the redirect port when TLS is on, because a bare `ip:port`
        typed into a browser is tried over HTTP — and HTTP against the TLS port
        looks exactly like the server being switched off. The redirector speaks
        HTTP, so it answers, and sends the browser on to the secure page.
        """
        return f"{self._ip}:{PORT}"

    def _aes_key(self, session_key: str) -> bytes:
        if session_key not in self._aes_cache:
            self._aes_cache[session_key] = _derive_key(session_key)
        return self._aes_cache[session_key]

    def _decrypt(self, token: str, enc_b64: str) -> str | None:
        sk = self._token_keys.get(token)
        if not sk:
            return None
        try:
            return _decrypt(self._aes_key(sk), enc_b64)
        except Exception:
            return None

    # ── callbacks ────────────────────────────────────────────────────────

    def set_wake_callback(self, fn) -> None:
        self._wake_callback = fn

    def set_connect_callback(self, fn) -> None:
        self._connect_callback = fn

    # ── broadcast ────────────────────────────────────────────────────────

    async def broadcast(self, msg: dict) -> None:
        self._history.append(msg)
        if len(self._history) > 300:
            self._history = self._history[-300:]
        dead: set[WebSocket] = set()
        for ws in list(self._clients):
            try:
                await ws.send_json(msg)
            except Exception:
                dead.add(ws)
        self._clients -= dead

    # ── FastAPI app ───────────────────────────────────────────────────────

    def _build_app(self) -> "FastAPI":
        app = FastAPI(docs_url=None, redoc_url=None)

        def _valid(tok: str) -> bool:
            """Is this token live? Expired ones are dropped as they are found,
            which keeps the sweep free and needs no background timer."""
            if not tok:
                return False
            issued = self._tokens.get(tok)
            if issued is None:
                return False
            if time.time() - issued > _TOKEN_TTL_SECONDS:
                self._tokens.pop(tok, None)
                self._token_keys.pop(tok, None)
                return False
            return True

        def _auth(req: Request) -> bool:
            return _valid(req.headers.get("authorization", "")
                          .removeprefix("Bearer ").strip())

        def _who(req: Request) -> str:
            """The client address a throttle counts against."""
            return (getattr(getattr(req, "client", None), "host", "") or "unknown")

        def _queue_command(text: str, who: str) -> tuple[int, str] | None:
            if not text:
                return None
            if (len(text) > _MAX_COMMAND_CHARS
                    or len(text.encode("utf-8")) > _MAX_COMMAND_BYTES):
                return 413, "Command is too long"
            if self._command_queue.full():
                return 503, "Command queue is full"
            if not self._command_throttle.consume(who):
                return 429, "Too many commands; wait before sending more"
            try:
                self._command_queue.put_nowait(text)
            except asyncio.QueueFull:
                return 503, "Command queue is full"
            if self._wake_callback:
                self._wake_callback()
            return None

        async def _read_json_object(
            req: Request, max_bytes: int = _MAX_COMMAND_BODY_BYTES
        ) -> tuple[dict | None, int | None]:
            content_length = req.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > max_bytes:
                        return None, 413
                except ValueError:
                    return None, 400

            chunks = bytearray()
            async for chunk in req.stream():
                chunks.extend(chunk)
                if len(chunks) > max_bytes:
                    return None, 413
            try:
                body = json.loads(chunks)
            except (json.JSONDecodeError, UnicodeDecodeError):
                return None, 400
            if not isinstance(body, dict):
                return None, 400
            return body, None

        @app.get("/login", response_class=HTMLResponse)
        async def login_page():
            return HTMLResponse(_localize_dashboard(
                self._login_html, _dashboard_language()
            ))

        @app.get("/", response_class=HTMLResponse)
        async def index():
            # Auth is handled client-side via sessionStorage bearer token.
            # Server-side header auth can't work here because browser navigations
            # don't send custom headers (location.href doesn't carry Authorization).
            html = (self._app_html
                    .replace("__IP__", self._ip)
                    .replace("__PORT__", str(PORT)))
            language = _dashboard_language()
            html = html.replace("__LANG__", language)
            html = _localize_dashboard(html, language)
            return HTMLResponse(html)

        @app.post("/login")
        async def login(req: Request):
            who  = _who(req)
            wait = self._throttle.blocked_for(who)
            if wait > 0:
                # 429 rather than 401 on purpose: it tells an honest user why
                # their correct key was refused, and it tells a script that
                # guessing is not working.
                return JSONResponse(
                    {"ok": False,
                     "error": f"Too many attempts. Try again in "
                              f"{int(wait) + 1} seconds."},
                    status_code=429,
                )
            body, error_status = await _read_json_object(req, _LOGIN_BODY_BYTES)
            if error_status is not None:
                return JSONResponse(
                    {"ok": False, "error": "Invalid login request"},
                    status_code=error_status,
                )
            entered = body.get("pin", "")
            if not isinstance(entered, str):
                return JSONResponse(
                    {"ok": False, "error": "Invalid login request"},
                    status_code=400,
                )
            entered = entered.strip().upper()
            now     = time.time()
            if entered in self._pending_keys and self._pending_keys[entered] > now:
                self._throttle.clear(who)
                del self._pending_keys[entered]          # one-time use
                tok = secrets.token_urlsafe(32)
                self._tokens[tok] = time.time()
                self._token_keys[tok] = entered
                self._aes_key(entered)                   # pre-derive & cache
                if self._connect_callback:
                    self._connect_callback()
                asyncio.create_task(self.broadcast(
                    {"type": "sys", "text": "Remote connection established."}
                ))
                # Bearer token in response body — no cookies needed (works on any browser/HTTP)
                return JSONResponse(
                    {"ok": True, "token": tok},
                    headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
                )
            self._throttle.record_failure(who)
            return JSONResponse({"ok": False, "error": "Invalid or expired key"},
                                status_code=401)

        @app.get("/auto-login")
        async def auto_login(req: Request, key: str = ""):
            """QR code target — validates one-time key, creates session, redirects phone."""
            who = _who(req)
            wait = self._throttle.blocked_for(who)
            security_headers = {
                "Cache-Control": "no-store",
                "Pragma": "no-cache",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
            }
            if wait > 0:
                return HTMLResponse(
                    "<!DOCTYPE html><html><body><h2>Too many attempts</h2>"
                    "<p>Wait before scanning or entering a new pairing link.</p>"
                    "</body></html>",
                    status_code=429,
                    headers=security_headers,
                )

            now = time.time()
            if not key or key not in self._pending_keys or self._pending_keys[key] <= now:
                self._throttle.record_failure(who)
                return HTMLResponse("""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width">
<style>
  body{background:#07090f;color:#dde3ed;font-family:sans-serif;
       display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center}
  h2{color:#f87171;margin-bottom:12px}p{color:#5e6a7e;font-size:14px}
</style></head>
<body><div><h2>Link Expired</h2>
<p>Press <strong style="color:#dde3ed">Remote Control</strong> in JARVIS to get a new QR code.</p>
</div></body></html>""", headers=security_headers)

            self._throttle.clear(who)
            del self._pending_keys[key]
            tok     = secrets.token_urlsafe(32)
            dev_tok = secrets.token_urlsafe(32)
            self._tokens[tok] = time.time()
            self._token_keys[tok] = key
            self._aes_key(key)
            self._device_sessions[dev_tok] = {"session_key": key}

            if self._connect_callback:
                self._connect_callback()
            asyncio.create_task(self.broadcast(
                {"type": "sys", "text": "Remote connection established via QR code."}
            ))

            return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width">
<style>
  body{{background:#07090f;color:#dde3ed;font-family:sans-serif;
       display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center}}
  p{{color:#5e6a7e;font-size:14px}}
</style></head>
<body>
<script>
  sessionStorage.setItem('jarvis_token','{tok}');
  sessionStorage.setItem('jarvis_key','{key}');
  localStorage.setItem('jarvis_device_token','{dev_tok}');
  setTimeout(function(){{location.replace('/')}},400);
</script>
<p>Connecting to JARVIS…</p>
</body></html>""", headers=security_headers)

        @app.post("/api/device-login")
        async def device_login_ep(req: Request):
            """Return a fresh auth token for a previously paired device token."""
            who = _who(req)
            if not self._device_login_throttle.consume(who):
                return JSONResponse(
                    {"ok": False, "error": "Too many device login attempts"},
                    status_code=429,
                    headers={"Retry-After": "60"},
                )
            body, error_status = await _read_json_object(
                req, _DEVICE_LOGIN_BODY_BYTES
            )
            if error_status is not None:
                return JSONResponse(
                    {"ok": False, "error": "Invalid device login request"},
                    status_code=error_status,
                )
            dev_tok = body.get("device_token", "")
            if not isinstance(dev_tok, str):
                return JSONResponse({"ok": False}, status_code=400)
            dev_tok = dev_tok.strip()
            if (len(dev_tok) != 43
                    or not re.fullmatch(r"[A-Za-z0-9_-]{43}", dev_tok)):
                return JSONResponse({"ok": False}, status_code=401)
            if not dev_tok or dev_tok not in self._device_sessions:
                return JSONResponse({"ok": False}, status_code=401)
            session_key = self._device_sessions[dev_tok]["session_key"]
            tok = secrets.token_urlsafe(32)
            self._tokens[tok] = time.time()
            self._token_keys[tok] = session_key
            self._aes_key(session_key)
            if self._connect_callback:
                self._connect_callback()
            asyncio.create_task(self.broadcast(
                {"type": "sys", "text": "Known device reconnected automatically."}
            ))
            return JSONResponse(
                {"ok": True, "token": tok, "key": session_key},
                headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
            )

        @app.post("/api/revoke-devices")
        async def revoke_devices(req: Request):
            """Invalidate all persistent device tokens (admin action)."""
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            # ALSO drop the live tokens, which this did not do.
            #
            # It cleared the remembered devices and left every session those
            # devices had already opened working until the app restarted — so
            # "revoke all devices" revoked nothing anybody was currently using,
            # which is the one case somebody presses it for.
            #
            # The caller's own token is kept, or pressing the button would log
            # out the person who pressed it.
            mine  = req.headers.get("authorization", "").removeprefix("Bearer ").strip()
            count = len(self._device_sessions)
            live  = len(self._tokens) - (1 if mine in self._tokens else 0)
            self._device_sessions.clear()
            keep = self._tokens.get(mine)
            self._tokens.clear()
            self._token_keys = {k: v for k, v in self._token_keys.items() if k == mine}
            if keep is not None:
                self._tokens[mine] = keep
            return JSONResponse({"ok": True, "revoked": count, "sessions_ended": live})

        @app.post("/api/command")
        async def command(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            body, error_status = await _read_json_object(req)
            if error_status is not None:
                return JSONResponse(
                    {"error": "Invalid or oversized command request"},
                    status_code=error_status,
                )
            token = req.headers.get("authorization", "").removeprefix("Bearer ").strip()
            enc   = body.get("enc", "")
            if not isinstance(enc, str):
                return JSONResponse({"error": "Invalid command request"},
                                    status_code=400)
            if enc:
                text = self._decrypt(token, enc)
                if text is None:
                    return JSONResponse({"error": "Decryption failed"}, status_code=400)
            else:
                text = body.get("text", "")
                if not isinstance(text, str):
                    return JSONResponse({"error": "Invalid command request"},
                                        status_code=400)
                text = text.strip()
            queued_error = _queue_command(text, _who(req))
            if queued_error:
                status, error = queued_error
                return JSONResponse({"error": error}, status_code=status)
            return JSONResponse({"ok": True})

        @app.post("/api/wake")
        async def wake_ep(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            if self._wake_callback:
                self._wake_callback()
            return JSONResponse({"ok": True})

        # ── Phone mic real-time audio → Gemini Live ──────────────────────────

        @app.websocket("/ws/phone-audio")
        async def phone_audio_ws(websocket: WebSocket, token: str = ""):
            tok = token.strip()
            if not _valid(tok):
                await websocket.close(code=4001)
                return
            await websocket.accept()
            asyncio.create_task(self.broadcast(
                {"type": "sys", "text": "Phone microphone live."}
            ))
            try:
                while True:
                    data = await websocket.receive_bytes()
                    try:
                        self._phone_audio_queue.put_nowait(
                            {"data": data, "mime_type": "audio/pcm"}
                        )
                    except asyncio.QueueFull:
                        pass  # drop frame rather than block
            except WebSocketDisconnect:
                pass
            finally:
                asyncio.create_task(self.broadcast(
                    {"type": "sys", "text": "Phone microphone stopped."}
                ))

        # ── File sharing ──────────────────────────────────────────────────────

        def _safe_filename(raw: str) -> str:
            name = Path(raw).name                          # strip path components
            name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(". ")
            return name or "upload"

        if _UPLOAD_OK:
            @app.post("/api/upload")
            async def upload_file(req: Request, file: UploadFile = FastAPIFile(...)):
                if not _auth(req):
                    return JSONResponse({"error": "Unauthorized"}, status_code=401)

                safe = _safe_filename(file.filename or "upload")
                dest = self._uploads_dir / safe
                stem, suffix = Path(safe).stem, Path(safe).suffix
                counter = 1
                while dest.exists():
                    dest = self._uploads_dir / f"{stem}_{counter}{suffix}"
                    counter += 1

                size = 0
                max_bytes = MAX_UPLOAD_MB * 1024 * 1024
                try:
                    with open(dest, "wb") as fout:
                        while True:
                            chunk = await file.read(65536)
                            if not chunk:
                                break
                            size += len(chunk)
                            if size > max_bytes:
                                fout.close()
                                dest.unlink(missing_ok=True)
                                return JSONResponse(
                                    {"error": f"File too large (max {MAX_UPLOAD_MB} MB)"},
                                    status_code=413,
                                )
                            fout.write(chunk)
                except Exception as exc:
                    try:
                        dest.unlink(missing_ok=True)
                    except Exception:
                        pass
                    return JSONResponse({"error": str(exc)}, status_code=500)

                asyncio.create_task(self.broadcast({
                    "type": "file_received",
                    "name": dest.name,
                    "size": size,
                    "saved_to": str(self._uploads_dir),
                }))
                return JSONResponse({"ok": True, "name": dest.name, "size": size})
        else:
            @app.post("/api/upload")
            async def upload_unavailable(req: Request):
                return JSONResponse(
                    {"error": "File uploads require: pip install python-multipart"},
                    status_code=503,
                )

        @app.get("/api/files")
        async def list_files(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            files = []
            try:
                for f in sorted(
                    (p for p in self._uploads_dir.iterdir() if p.is_file()),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                ):
                    files.append({"name": f.name, "size": f.stat().st_size})
            except Exception:
                pass
            return JSONResponse({"files": files})

        @app.get("/uploads/{filename}")
        async def download_file(filename: str, token: str = ""):
            # Auth via query param — browser <a download> can't send custom headers
            tok = token.strip()
            if not _valid(tok):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            safe = re.sub(r'[/\\]', '', filename)
            path = self._uploads_dir / safe
            if not path.exists() or not path.is_file():
                return JSONResponse({"error": "Not found"}, status_code=404)
            return FileResponse(str(path), filename=safe)

        @app.websocket("/ws")
        async def ws_ep(websocket: WebSocket, token: str = ""):
            tok = token.strip()
            if not _valid(tok):
                await websocket.close(code=4001)
                return
            await websocket.accept()
            self._clients.add(websocket)
            for entry in self._history[-50:]:
                try:
                    await websocket.send_json(entry)
                except Exception:
                    break
            try:
                while True:
                    raw = await websocket.receive_text()
                    if len(raw.encode("utf-8")) > _MAX_COMMAND_BODY_BYTES:
                        await websocket.send_json(
                            {"type": "error", "error": "Command request is too large"}
                        )
                        continue
                    try:
                        data = json.loads(raw)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        await websocket.send_json(
                            {"type": "error", "error": "Invalid command request"}
                        )
                        continue
                    if not isinstance(data, dict):
                        await websocket.send_json(
                            {"type": "error", "error": "Invalid command request"}
                        )
                        continue
                    if data.get("type") == "command":
                        enc = data.get("enc", "")
                        if not isinstance(enc, str):
                            await websocket.send_json(
                                {"type": "error", "error": "Invalid command request"}
                            )
                            continue
                        if enc:
                            t = self._decrypt(tok, enc)
                            if t is None:
                                await websocket.send_json(
                                    {"type": "error", "error": "Decryption failed"}
                                )
                                continue
                        else:
                            t = data.get("text", "")
                            if not isinstance(t, str):
                                await websocket.send_json(
                                    {"type": "error", "error": "Invalid command request"}
                                )
                                continue
                            t = t.strip()
                        queued_error = _queue_command(
                            t, websocket.client.host if websocket.client else "unknown"
                        )
                        if queued_error:
                            _, error = queued_error
                            await websocket.send_json(
                                {"type": "error", "error": error}
                            )
            except WebSocketDisconnect:
                pass
            finally:
                self._clients.discard(websocket)

        return app

    # ── serve ─────────────────────────────────────────────────────────────

    async def _serve_redirector(self) -> None:
        """A plain-HTTP listener whose only job is to send people to HTTPS.

        THE PROBLEM THIS SOLVES, WHICH LOOKED LIKE THE SERVER BEING DOWN
            Type `192.168.1.108:8000` into a phone browser and it tries HTTP.
            The TLS server accepts the connection, finds no handshake and
            closes it — which Chrome reports as "This site can't be reached,
            192.168.1.108 refused to connect". The server is running perfectly
            and the user is told it is off.

            The port that used to sit here was a SECOND HTTPS server, added on
            the belief that browsers upgrade a bare `ip:port` to https. Some
            do. Android Chrome does not, so the second port had exactly the
            same failure as the first.

        So this speaks HTTP, and answers everything with a redirect to the same
        path on the HTTPS port. Typing the address by hand now works, which is
        what people do when a QR code is inconvenient.
        """
        from fastapi.responses import RedirectResponse

        bounce = FastAPI(docs_url=None, redoc_url=None)

        @bounce.get("/{path:path}")
        async def _to_https(path: str, request: Request):
            query = f"?{request.url.query}" if request.url.query else ""
            return RedirectResponse(
                f"https://{self._ip}:{SECURE_PORT}/{path}{query}",
                status_code=307)

        cfg = uvicorn.Config(bounce, host="0.0.0.0", port=PORT,
                             log_level="warning")
        print(f"[Dashboard] Type by hand:  {self._ip}:{PORT}  "
              f"(sends you to the secure page)")
        await uvicorn.Server(cfg).serve()

    async def serve(self) -> None:
        if not _DEPS_OK:
            print("[Dashboard] fastapi/uvicorn not installed — dashboard disabled.")
            print("[Dashboard] Run:  pip install fastapi 'uvicorn[standard]' cryptography")
            return

        use_tls = self._https_requested()
        if use_tls and not _ensure_certs():
            self._bind_error = (
                "HTTPS certificate generation failed; the dashboard was not "
                "started to avoid exposing commands and tokens over HTTP. "
                "Install/repair cryptography or explicitly set "
                '"dashboard_https": false to opt into unencrypted HTTP.'
            )
            print(f"[Dashboard] {self._bind_error}")
            return

        use_ssl  = self._ssl_enabled()
        ssl_key  = BASE_DIR / "config" / "certs" / "jarvis.key"
        ssl_cert = BASE_DIR / "config" / "certs" / "jarvis.crt"

        if use_ssl:
            asyncio.create_task(self._serve_redirector())
        else:
            print("[Dashboard] WARNING: dashboard is using unencrypted HTTP. "
                  "Commands and tokens can be observed on the network.")

        cfg = uvicorn.Config(
            self.app, host="0.0.0.0",
            port=SECURE_PORT if use_ssl else PORT, log_level="warning",
            **({"ssl_keyfile": str(ssl_key), "ssl_certfile": str(ssl_cert)}
               if use_ssl else {}),
        )

        # CAN THIS PORT ACTUALLY BE TAKEN?
        #
        # uvicorn raises when the port is busy, and under pythonw.exe there is
        # no console for that to be seen in — so a second JARVIS, or anything
        # else already on 8000, produced a dashboard that was silently dead
        # while the HUD went on showing a QR code pointing at it. The phone
        # then reports ERR_CONNECTION_REFUSED, which is true and impossible to
        # act on.
        #
        # Asking first costs a millisecond and turns that into a sentence.
        import socket as _socket
        # No SO_REUSEADDR. On Windows that option lets a second socket bind a
        # port another socket already holds — which is exactly the condition
        # being tested for, so setting it made the probe always succeed.
        _probe = _socket.socket()
        try:
            _probe.bind(("0.0.0.0", SECURE_PORT if use_ssl else PORT))
        except OSError as exc:
            _probe.close()
            self._bind_error = (
                f"port {SECURE_PORT if use_ssl else PORT} is already in use — "
                f"another copy of JARVIS is probably running. Close it and "
                f"restart, or the phone dashboard will stay unreachable "
                f"({exc.__class__.__name__})")
            print(f"[Dashboard] {self._bind_error}")
            return
        _probe.close()

        print(f"[Dashboard] {self.get_url()}")
        print("[Dashboard] Press 'Remote Control' in JARVIS UI to get the QR code.")
        await uvicorn.Server(cfg).serve()
