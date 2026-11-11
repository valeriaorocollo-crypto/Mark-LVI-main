"""
MARK LIV — one-time setup.

Installs the base Python dependencies for THIS operating system only: the
OS-specific packages in requirements-base.txt carry `sys_platform` markers, so
a macOS or Linux user never pulls Windows-only libraries. Optional integrations
are listed separately in requirements-optional.txt and are not installed here.

Two things it deliberately does NOT install:
  * the optional local wake word ("Hey Jarvis") — one-click, opt-in, from
    ⚙ → WAKE WORD inside the app;
  * anything for the avatar — the holographic head renders in software on the
    PyQt6 and numpy already listed here. No GPU, no OpenGL, no extra packages.
"""
import platform
import subprocess
import sys
from pathlib import Path

OS = platform.system()  # "Windows" | "Darwin" | "Linux"
HERE = Path(__file__).resolve().parent

MIN_PY = (3, 11)        # hard floor: below this the syntax used here won't parse
MAX_PY = (3, 13)        # highest version this is actually tested on
OPTIONAL_GROUPS = {
    "integrations": "requirements-optional-integrations.txt",
    "documents": "requirements-optional-documents.txt",
    "local-voice": "requirements-optional-local-voice.txt",
}


def _run(label: str, args: list[str]) -> None:
    print(f"\n> {label}")
    subprocess.run(args, check=True)


def _check_python() -> None:
    """Fail immediately and clearly rather than deep inside a pip resolver.

    A wrong interpreter is the single most common way this install goes sideways,
    and the error it produces on its own names a wheel, not the real problem.
    """
    v = sys.version_info[:2]
    if v > MAX_PY:
        # Newer is a warning, not a wall. Turning away someone who installed
        # today's Python is a worse first impression than a version that
        # turns out to work fine, and if a wheel really is missing pip says
        # so plainly.
        print(f"\n[!]  Python {v[0]}.{v[1]} is newer than the "
              f"{MAX_PY[0]}.{MAX_PY[1]} this is tested on. Continuing - if a "
              f"package has no wheel yet, install Python "
              f"{MAX_PY[0]}.{MAX_PY[1]} and run setup with that.")
        return
    if v < MIN_PY:
        print(f"\n[X] Python {v[0]}.{v[1]} detected - MARK LIV needs at "
              f"least Python {MIN_PY[0]}.{MIN_PY[1]}.")
        print("   Install a supported version and run setup with it, e.g.:")
        print(f"     py -{MIN_PY[0]}.{MIN_PY[1]} setup.py        (Windows)")
        print(f"     python{MIN_PY[0]}.{MIN_PY[1]} setup.py      (macOS / Linux)")
        sys.exit(1)


def _configure_output() -> None:
    """Make setup output decodable by ANY parent process.

    Two independent encoding decisions used to meet here and disagree:

      * this script's stdout encoding, which Python derives from the ambient
        locale and from PYTHONUTF8 / PYTHONIOENCODING — so it changed with the
        machine and the shell;
      * the parent's decoder, which derives its own locale encoding.

    When the two disagreed, the parent raised UnicodeDecodeError while reading
    this process's output and the whole installer looked broken — including
    the clean-copy check, which is exactly where a broken output matters most.

    Forcing the streams to ASCII makes every byte this script writes decodable
    under any encoding a parent might use. The messages below are written in
    ASCII for the same reason: a status marker has no business being the
    reason an installer cannot be read.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="ascii", errors="replace")
            except (ValueError, OSError):
                # A stream that cannot be reconfigured (a pipe with a fixed
                # encoding, a captured stream in a test harness) still has to
                # work. Fall back to replacing only the unencodable
                # characters rather than failing the install.
                try:
                    reconfigure(errors="replace")
                except (ValueError, OSError):
                    pass


def _check_assets() -> bool:
    """The avatar's face is a shipped file; a truncated clone should say so."""
    face = HERE / "core" / "face_model.obj"
    if not face.exists() or face.stat().st_size < 4096:
        print(
            "\n[!]  core/face_model.obj is missing or truncated - the avatar "
            "will fall back to the plain glowing core.\n"
            "    Re-clone the repository, or fetch that one file again."
        )
        return False
    return True


def _check_manifests() -> None:
    """Verify that the clean-copy installation inputs are present."""
    required = (
        "requirements.txt",
        "requirements-base.txt",
        "requirements-optional.txt",
        *OPTIONAL_GROUPS.values(),
    )
    missing = [name for name in required if not (HERE / name).is_file()]
    if missing:
        raise SystemExit(
            "[X] Installation manifests missing: " + ", ".join(missing)
        )


def _show_plan() -> None:
    """Print the installation and network plan without changing the system."""
    def show_manifest(path: Path, indent: str) -> None:
        for line in path.read_text(encoding="utf-8").splitlines():
            requirement = line.strip()
            if requirement and not requirement.startswith("#") and not requirement.startswith("-r "):
                print(f"{indent}{requirement}")

    print("\nMARK setup plan (no changes will be made)")
    print("  Base packages (requirements-base.txt):")
    show_manifest(HERE / "requirements-base.txt", "    - ")
    print("  Optional groups (not selected; explicit install required):")
    for group, manifest in OPTIONAL_GROUPS.items():
        print(f"    {group} ({manifest}):")
        show_manifest(HERE / manifest, "      - ")
    print("  Python package source: pip configuration")
    print("  Network: package downloads only if setup is run normally;")
    print("           optional groups are installed only when selected and confirmed")
    print("  Playwright browsers: not selected")
    print("  Credentials/OAuth: not requested or stored")
    print("  Native tools and permissions: reported by startup diagnostics")


def _selected_optional_groups() -> list[str]:
    values: list[str] = []
    for index, argument in enumerate(sys.argv[1:]):
        if argument == "--install-optional":
            if index + 1 >= len(sys.argv[1:]):
                raise SystemExit(
                    "[X] --install-optional requires a comma-separated group list."
                )
            values.extend(
                item.strip().lower()
                for item in sys.argv[1:][index + 1].split(",")
                if item.strip()
            )
            break
    unknown = sorted(set(values) - set(OPTIONAL_GROUPS))
    if unknown:
        raise SystemExit(
            "[X] Unknown optional group(s): " + ", ".join(unknown)
            + ". Choose: " + ", ".join(OPTIONAL_GROUPS)
        )
    return list(dict.fromkeys(values))


def main() -> None:
    _configure_output()
    print(f"[*]  MARK LIV setup - detected OS: {OS or 'unknown'}, "
          f"Python {sys.version_info[0]}.{sys.version_info[1]}")
    _check_python()
    _check_manifests()

    if "--plan" in sys.argv[1:]:
        _check_assets()
        _show_plan()
        return

    dry_run = "--dry-run" in sys.argv[1:]
    if dry_run:
        if not _check_assets():
            raise SystemExit(
                "[X] Dry run failed: required assets are missing or truncated."
            )
        print(
            "\n[OK] Dry run complete. Manifests and assets are present; no "
            "packages, browsers, network connections, or files were changed."
        )
        return

    optional_groups = _selected_optional_groups()
    if optional_groups and "--confirm" not in sys.argv[1:]:
        raise SystemExit(
            "[X] Optional installation is disabled without --confirm. "
            "Review with --plan, then rerun with "
            "`--install-optional group[,group] --confirm`."
        )

    # requirements.txt includes only the base set; optional integrations remain
    # opt-in and are documented in requirements-optional.txt.
    _run("Installing Python dependencies (OS-specific extras auto-filtered)...",
         [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])

    for group in optional_groups:
        _run(
            f"Installing optional group: {group}",
            [sys.executable, "-m", "pip", "install", "-r",
             str(HERE / OPTIONAL_GROUPS[group])],
        )

    # Chromium covers Chrome/Edge/Opera/Brave/Vivaldi; Firefox for Firefox.
    # (Safari automation additionally needs: python -m playwright install webkit)
    # Not fatal: these are a few hundred megabytes from a CDN that a corporate
    # network or a flaky connection can refuse, and everything except browser
    # automation works without them. Failing the whole install there would send
    # a user away from a working app.
    if "--install-browsers" in sys.argv[1:]:
        try:
            _run("Installing Playwright browsers (chromium + firefox)...",
                 [sys.executable, "-m", "playwright", "install",
                  "chromium", "firefox"])
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"\n[!]  Playwright browsers were not installed ({e}).")
            print("    Retry later with: python setup.py --install-browsers")
    else:
        print(
            "\n[i]  Playwright browsers were not downloaded. Browser automation "
            "is optional; rerun with --install-browsers if you explicitly need it."
        )

    _check_assets()

    # ── OS-specific post-install notes ────────────────────────────────────────
    if OS == "Windows":
        try:
            import win32com.client  # noqa: F401
        except ImportError:
            postinstall = Path(sys.executable).parent / "Scripts" / "pywin32_postinstall.py"
            print(
                "\n[!]  pywin32 did not register correctly - desktop-shortcut "
                "creation will use a slower fallback. To fix it, run:\n"
                f'    "{sys.executable}" -m pip install --force-reinstall pywin32\n'
                f'    "{sys.executable}" "{postinstall}" -install'
            )
    elif OS == "Linux":
        print(
            "\n[i]  Linux note - a few voice-controlled OS actions shell out "
            "to native tools. Install the ones you'll use via your package "
            "manager:\n"
            "    - volume      -> pulseaudio-utils   (pactl)\n"
            "    - brightness  -> brightnessctl\n"
            "    - reminders   -> systemd (systemd-run) or 'at'\n"
            "    - open URLs   -> xdg-utils          (xdg-open)"
        )
    elif OS == "Darwin":
        print(
            "\n[i]  macOS note - volume, brightness and reminders use the "
            "built-in "
            "'osascript' / LaunchAgents, so no extra tools are required.\n"
            "    For Safari automation only: python -m playwright install webkit"
        )

    print("\n[OK] Setup complete!")
    print("   1) Launch it:  python main.py")
    print("   2) Paste your free Gemini API key when the setup screen appears.")
    print("   3) (Optional) Enable 'Hey Jarvis' from SETTINGS -> WAKE WORD.")


if __name__ == "__main__":
    main()
