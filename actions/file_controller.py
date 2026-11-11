import hashlib
import os
import shutil
import platform
import tempfile
from pathlib import Path
from datetime import datetime

try:
    import send2trash
    _SEND2TRASH = True
except ImportError:
    _SEND2TRASH = False

from core import action_policy, confirm, outcome
from core.undo import push_undo

_OS = platform.system()  # "Windows" | "Darwin" | "Linux"

# Undo keeps a file's previous contents in memory so `write` can be reversed.
# Above this size it does not — a 200 MB log would sit in RAM for the rest of
# the session to protect an edit nobody is going to take back.
_UNDO_CONTENT_LIMIT = 1_000_000


def _undo_move(
    src: Path,
    dst: Path,
    expected_identity: tuple[int, int, int, int],
):
    """Reverse of a move: put it back where it came from."""
    def _fn():
        if not dst.exists():
            return f"'{dst.name}' is no longer there — nothing moved back."
        if src.exists() or src.is_symlink():
            return f"'{src.name}' already exists — leaving both paths untouched."
        try:
            if _file_identity(dst.stat()) != expected_identity:
                return f"'{dst.name}' was replaced — leaving it untouched."
        except OSError:
            return f"'{dst.name}' could not be checked — leaving it untouched."
        src.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(dst), str(src))
        return f"'{src.name}' is back in {src.parent.name}/."
    return _fn


def _undo_create(target: Path):
    """Reverse of a create: remove what we made — and only if we still made it.

    Deliberately refuses to touch a directory that has since been filled: the
    undo for 'create a folder' is not 'delete whatever ended up in it'."""
    def _fn():
        if not target.exists():
            return f"'{target.name}' is already gone."
        if target.is_dir():
            if any(target.iterdir()):
                return (f"'{target.name}' is not empty any more — "
                        f"leaving it alone rather than deleting your files.")
            target.rmdir()
        else:
            target.unlink()
        return f"Removed '{target.name}'."
    return _fn


def _file_identity(info) -> tuple[int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _file_digest(target: Path) -> bytes:
    digest = hashlib.sha256()
    with target.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.digest()


def _snapshot_existing_text(
    target: Path,
) -> tuple[bytes | None, tuple[int, int, int, int] | None, str | None]:
    """Capture a bounded, restorable UTF-8 file state before changing it."""
    if target.is_symlink():
        return None, None, "symbolic links cannot be replaced safely"
    try:
        before = target.stat()
    except FileNotFoundError:
        return None, None, None
    except OSError:
        return None, None, "the existing file could not be inspected"

    if not target.is_file():
        return None, None, "the existing target is not a regular file"
    if before.st_size > _UNDO_CONTENT_LIMIT:
        return None, None, "the existing file is too large to back up safely"
    try:
        with target.open("rb") as source_file:
            previous = source_file.read(_UNDO_CONTENT_LIMIT + 1)
    except OSError:
        return None, None, "the existing file could not be backed up"
    if len(previous) > _UNDO_CONTENT_LIMIT:
        return None, None, "the existing file is too large to back up safely"
    try:
        previous.decode("utf-8")
    except UnicodeDecodeError:
        return None, None, "the existing file is not valid UTF-8 text"
    if b"\x00" in previous:
        return None, None, "the existing file contains binary data"

    try:
        after = target.stat()
    except OSError:
        return None, None, "the existing file changed while it was backed up"
    if _file_identity(before) != _file_identity(after):
        return None, None, "the existing file changed while it was backed up"
    return previous, _file_identity(after), None


def _write_bytes_atomically(
    target: Path,
    content: bytes,
    expected_identity: tuple[int, int, int, int] | None,
) -> tuple[int, int, int, int]:
    """Replace an existing snapshot or create a new file without clobbering."""
    descriptor, temp_name = tempfile.mkstemp(
        dir=target.parent, prefix=".mark-write-", suffix=".tmp"
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())

        if expected_identity is None:
            written_identity = _file_identity(temp_path.stat())
            os.link(temp_path, target)
            return written_identity
        else:
            if target.is_symlink():
                raise OSError("the target became a symbolic link")
            current_identity = _file_identity(target.stat())
            if current_identity != expected_identity:
                raise OSError("the target changed before replacement")
            shutil.copystat(target, temp_path)
            os.utime(temp_path, None)
            os.replace(temp_path, target)
            written_identity = _file_identity(target.stat())
            return written_identity
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _undo_write(
    target: Path,
    previous: bytes | None,
    expected_digest: bytes,
    expected_identity: tuple[int, int, int, int],
):
    """Restore only if the assistant's written contents are still present."""
    def _fn():
        if target.is_symlink():
            return f"'{target.name}' became a symbolic link — leaving it untouched."
        if not target.exists():
            return f"'{target.name}' is already gone."
        try:
            before = target.stat()
            if before.st_size > _UNDO_CONTENT_LIMIT * 2:
                return f"'{target.name}' changed since the write — leaving it untouched."
            with target.open("rb") as current_file:
                current = current_file.read(_UNDO_CONTENT_LIMIT * 2 + 1)
            after = target.stat()
        except OSError:
            return f"'{target.name}' could not be checked — leaving it untouched."
        if (
            len(current) > _UNDO_CONTENT_LIMIT * 2
            or _file_identity(before) != _file_identity(after)
        ):
            return f"'{target.name}' changed since the write — leaving it untouched."
        if _file_identity(after) != expected_identity:
            return f"'{target.name}' was replaced since the write — leaving it untouched."
        if hashlib.sha256(current).digest() != expected_digest:
            return f"'{target.name}' changed since the write — leaving it untouched."
        if previous is None:
            target.unlink()
            return f"Removed '{target.name}' — it did not exist before."
        try:
            _write_bytes_atomically(target, previous, _file_identity(after))
        except OSError:
            return f"'{target.name}' could not be restored safely."
        return f"Restored the previous contents of '{target.name}'."
    return _fn


def _restore_from_trash(original: Path) -> str:
    """Best-effort undelete.

    delete_file uses send2trash, which is the right call: the file lands in the
    Recycle Bin / Trash where the person can also find it themselves. Getting it
    back out again is shell work and only reliable on Windows, where pywin32 is
    already a dependency. Everywhere else this says where the file is instead of
    pretending it failed — the file is not lost either way."""
    if _OS == "Windows":
        try:
            import win32com.client
            shell = win32com.client.Dispatch("Shell.Application")
            bin_folder = shell.NameSpace(10)      # ssfBITBUCKET
            for item in bin_folder.Items():
                if str(bin_folder.GetDetailsOf(item, 1)).strip().lower() == \
                        str(original.parent).strip().lower():
                    if str(item.Name).strip().lower() == original.name.strip().lower():
                        item.InvokeVerb("UNDELETE")
                        return f"'{original.name}' restored from the Recycle Bin."
        except Exception as e:
            print(f"[file] Recycle Bin restore failed: {e}")
    return (f"'{original.name}' is in the Recycle Bin — I could not pull it back "
            f"automatically, but it is there and can be restored by hand.")


_SAFE_ROOTS: list[Path] = [
    Path.home(),
]

def _is_safe_path(target: Path) -> bool:
    """Is the given path inside _SAFE_ROOTS? If not, reject the operation."""
    try:
        resolved = target.resolve()
        return any(
            resolved == root.resolve() or resolved.is_relative_to(root.resolve())
            for root in _SAFE_ROOTS
        )
    except Exception:
        return False

def _get_desktop() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_DESKTOP_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    return Path.home() / "Desktop"

def _get_downloads() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_DOWNLOAD_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    return Path.home() / "Downloads"

def _get_documents() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_DOCUMENTS_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    return Path.home() / "Documents"

def _get_pictures() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_PICTURES_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    return Path.home() / "Pictures"

def _get_music() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_MUSIC_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    return Path.home() / "Music"

def _get_videos() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_VIDEOS_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    return Path.home() / "Videos"


def _resolve_path(raw: str) -> Path:
    shortcuts: dict[str, Path] = {
        "desktop":   _get_desktop(),
        "downloads": _get_downloads(),
        "documents": _get_documents(),
        "pictures":  _get_pictures(),
        "music":     _get_music(),
        "videos":    _get_videos(),
        "home":      Path.home(),
    }
    raw   = raw.strip().strip('"').strip("'")
    lower = raw.lower()
    if lower in shortcuts:
        return shortcuts[lower]

    # "desktop/notes/a.md" and "desktop\notes\a.md" — a shortcut followed by a
    # sub-path.  Without this branch the whole string falls through to the
    # relative-path return below and is resolved against the process CWD instead
    # of the real Desktop: an "Access denied" when the project lives outside the
    # home directory, or — worse — a silent write into a stray "desktop" folder
    # inside the project when it lives inside it.
    head, sep, rest = raw.replace("\\", "/").partition("/")
    if sep and head.lower() in shortcuts:
        rest = rest.strip("/")
        return shortcuts[head.lower()] / rest if rest else shortcuts[head.lower()]

    return Path(raw).expanduser()

def _format_size(b: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"

def _safe_trash(target: Path) -> str:

    if not _SEND2TRASH:
        return (
            "send2trash is not installed. "
            "Run: pip install send2trash — "
            "Permanent deletion is disabled for safety."
        )
    send2trash.send2trash(str(target))
    return f"Moved to Trash: {target.name}"


def list_files(path: str = "desktop", show_hidden: bool = False) -> str:
    try:
        target = _resolve_path(path)
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        if not target.exists():
            return f"Path not found: {target}"
        if not target.is_dir():
            return f"Not a directory: {target}"

        items = []
        for item in sorted(target.iterdir()):
            if not show_hidden and item.name.startswith("."):
                continue
            if item.is_dir():
                items.append(f"📁 {item.name}/")
            else:
                size = _format_size(item.stat().st_size)
                items.append(f"📄 {item.name} ({size})")

        if not items:
            return f"Directory is empty: {target.name}/"

        return f"Contents of {target.name}/ ({len(items)} items):\n" + "\n".join(items)

    except PermissionError:
        return f"Permission denied: {path}"
    except Exception as e:
        return f"Error listing files: {e}"


def create_file(path: str, name: str = "", content: str = "") -> str:
    try:
        if not isinstance(content, str) or len(content) > 1_000_000:
            return "Could not create file: content must be text no larger than 1000000 characters."
        base   = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        previous, identity, error = _snapshot_existing_text(target)
        if error:
            return f"Could not create file: {error}; nothing was changed."
        target.parent.mkdir(parents=True, exist_ok=True)
        encoded = content.encode("utf-8")
        written_identity = _write_bytes_atomically(target, encoded, identity)
        push_undo(f"created {target.name}",
                  _undo_write(
                      target,
                      previous,
                      hashlib.sha256(encoded).digest(),
                      written_identity,
                  ))
        return f"File created: {target.name}"
    except Exception as e:
        return f"Could not create file: {e}"


def create_folder(path: str, name: str = "") -> str:
    try:
        base   = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        if target.exists():
            return f"Folder already exists: {target.name}"
        target.mkdir(parents=True, exist_ok=False)
        # Only offer to undo a folder we actually made. "mkdir -p" on something
        # that was already there is not a change, and undoing it would delete a
        # directory the user has had for years.
        push_undo(f"created folder {target.name}", _undo_create(target))
        return f"Folder created: {target.name}"
    except Exception as e:
        return f"Could not create folder: {e}"


def delete_file(path: str, name: str = "") -> str:
    try:
        base   = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        if not target.exists():
            return f"Not found: {target.name}"

        # Safe-directory check — protect critical user folders
        protected = {
            _get_desktop(), _get_downloads(), _get_documents(),
            _get_pictures(), _get_music(), _get_videos(), Path.home()
        }
        if target.resolve() in {p.resolve() for p in protected}:
            return f"Protected directory, cannot delete: {target.name}"

        original = target.resolve()
        result   = _safe_trash(target)
        if result.startswith("Moved to Trash"):
            push_undo(f"deleted {original.name}",
                      lambda p=original: _restore_from_trash(p))
        return result

    except PermissionError:
        return f"Permission denied: {path}"
    except Exception as e:
        return f"Could not delete: {e}"


def move_file(path: str, name: str = "", destination: str = "") -> str:
    try:
        base   = _resolve_path(path)
        src    = (base / name) if name else base
        dst    = _resolve_path(destination) if destination else None

        if not src.exists():
            return f"Source not found: {src.name}"
        if dst is None:
            return "No destination specified."
        if not _is_safe_path(src):
            return f"Access denied (source): {src}"
        if not _is_safe_path(dst):
            return f"Access denied (destination): {dst}"

        if dst.is_dir():
            dst = dst / src.name
        if dst.exists() or dst.is_symlink():
            return f"Destination already exists: {dst}"

        dst.parent.mkdir(parents=True, exist_ok=True)
        origin = src.resolve()
        shutil.move(str(src), str(dst))
        moved_identity = _file_identity(dst.stat())
        push_undo(f"moved {origin.name} to {dst.parent.name}/",
                  _undo_move(origin, dst.resolve(), moved_identity))
        return f"Moved: {src.name} → {dst.parent.name}/"

    except Exception as e:
        return f"Could not move: {e}"


def copy_file(path: str, name: str = "", destination: str = "") -> str:
    try:
        base = _resolve_path(path)
        src  = (base / name) if name else base
        dst  = _resolve_path(destination) if destination else None

        if not src.exists():
            return f"Source not found: {src.name}"
        if dst is None:
            return "No destination specified."
        if not _is_safe_path(src):
            return f"Access denied (source): {src}"
        if not _is_safe_path(dst):
            return f"Access denied (destination): {dst}"

        if dst.is_dir():
            dst = dst / src.name
        if dst.exists() or dst.is_symlink():
            return f"Destination already exists: {dst}"
        if src.is_dir():
            return (
                "Directory copies are temporarily disabled because MARK cannot "
                "safely verify an undo snapshot for their full contents."
            )

        dst.parent.mkdir(parents=True, exist_ok=True)

        created_identity = None
        try:
            with src.open("rb") as source_file, dst.open("xb") as destination_file:
                created_identity = _file_identity(os.fstat(destination_file.fileno()))
                shutil.copyfileobj(source_file, destination_file)
            shutil.copystat(src, dst)
        except Exception:
            if created_identity is not None:
                try:
                    current_identity = _file_identity(dst.stat())
                    if (
                        current_identity[0:2] == created_identity[0:2]
                    ):
                        dst.unlink()
                except OSError:
                    pass
            raise

        copied_identity = _file_identity(dst.stat())
        copied_digest = _file_digest(dst)
        _copy = dst.resolve()
        def _undo_copy():
            if not _copy.exists():
                return f"The copy '{_copy.name}' is already gone."
            if _copy.is_symlink() or not _copy.is_file():
                return f"The copy '{_copy.name}' changed type — leaving it untouched."
            try:
                if _file_identity(_copy.stat()) != copied_identity:
                    return f"The copy '{_copy.name}' changed — leaving it untouched."
                if _file_digest(_copy) != copied_digest:
                    return f"The copy '{_copy.name}' changed — leaving it untouched."
                _copy.unlink()
            except OSError:
                return f"The copy '{_copy.name}' could not be checked — leaving it untouched."
            return f"Removed the copy in {_copy.parent.name}/."
        push_undo(f"copied {src.name} to {dst.parent.name}/", _undo_copy)

        return f"Copied: {src.name} → {dst.parent.name}/"

    except Exception as e:
        return f"Could not copy: {e}"


def rename_file(path: str, name: str = "", new_name: str = "") -> str:
    try:
        base     = _resolve_path(path)
        target   = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        if not target.exists():
            return f"Not found: {target.name}"
        if (
            not isinstance(new_name, str)
            or not new_name
            or new_name in {".", ".."}
            or len(new_name) > 255
            or any(separator in new_name for separator in ("/", "\\", ":"))
            or new_name.endswith((" ", "."))
        ):
            return "New name must be a single safe filename of at most 255 characters."

        new_path = target.parent / new_name
        if not _is_safe_path(new_path):
            return f"Access denied (destination): {new_path}"
        if new_path.exists():
            return f"A file named '{new_name}' already exists here."

        old_path = target.resolve()
        target.rename(new_path)
        push_undo(
            f"renamed {old_path.name} to {new_name}",
            _undo_move(
                old_path,
                new_path.resolve(),
                _file_identity(new_path.stat()),
            ),
        )
        return f"Renamed: {target.name} → {new_name}"

    except Exception as e:
        return f"Could not rename: {e}"


def read_file(path: str, name: str = "", max_chars: int = 4000) -> str:
    try:
        base   = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        if not target.exists():
            return f"File not found: {target.name}"
        if not target.is_file():
            return f"Not a file: {target.name}"

        content = target.read_text(encoding="utf-8", errors="ignore")
        if len(content) > max_chars:
            content = content[:max_chars] + f"\n\n[Truncated — {len(content)} total chars]"
        return content

    except Exception as e:
        return f"Could not read file: {e}"


def write_file(path: str, name: str = "", content: str = "",
               append: bool = False) -> str:
    try:
        if not isinstance(content, str) or len(content) > 1_000_000:
            return "Could not write file: content must be text no larger than 1000000 characters."
        if not isinstance(append, bool):
            return "Could not write file: append must be a boolean."
        base   = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        previous, identity, error = _snapshot_existing_text(target)
        if error:
            return f"Could not write file: {error}; nothing was changed."
        target.parent.mkdir(parents=True, exist_ok=True)
        encoded = content.encode("utf-8")
        new_content = (previous or b"") + encoded if append else encoded
        written_identity = _write_bytes_atomically(target, new_content, identity)

        action = "Appended to" if append else "Written to"
        push_undo(
            f"wrote to {target.name}",
            _undo_write(
                target,
                previous,
                hashlib.sha256(new_content).digest(),
                written_identity,
            ),
        )
        return f"{action}: {target.name}"
    except Exception as e:
        return f"Could not write file: {e}"


def find_files(name: str = "", extension: str = "",
               path: str = "home", max_results: int = 20) -> str:
    try:
        search_path = _resolve_path(path)
        if not _is_safe_path(search_path):
            return f"Access denied: {search_path}"
        if not search_path.exists():
            return f"Search path not found: {path}"

        results    = []
        dir_count  = 0
        max_dirs   = 500  # performance + safety limit

        for item in search_path.rglob("*"):
            if item.is_dir():
                dir_count += 1
                if dir_count > max_dirs:
                    break
                continue
            if not item.is_file():
                continue
            if extension and item.suffix.lower() != extension.lower():
                continue
            if name and name.lower() not in item.name.lower():
                continue
            size = _format_size(item.stat().st_size)
            results.append(f"📄 {item.name} ({size}) — {item.parent}")
            if len(results) >= max_results:
                break

        if not results:
            query = name or extension or "files"
            return f"No {query} found in {search_path.name}/"

        return f"Found {len(results)} file(s):\n" + "\n".join(results)

    except Exception as e:
        return f"Search error: {e}"


def get_largest_files(path: str = "downloads", count: int = 10) -> str:
    count = min(count, 50)  # maksimum 50
    try:
        search_path = _resolve_path(path)
        if not _is_safe_path(search_path):
            return f"Access denied: {search_path}"
        if not search_path.exists():
            return f"Path not found: {path}"

        files = []
        for item in search_path.rglob("*"):
            if item.is_file():
                try:
                    files.append((item.stat().st_size, item))
                except Exception:
                    continue

        files.sort(reverse=True)
        top = files[:count]

        if not top:
            return "No files found."

        lines = [f"Top {len(top)} largest files in {search_path.name}/:"]
        for size, f in top:
            lines.append(f"  {_format_size(size):>10}  {f.name}  ({f.parent})")

        return "\n".join(lines)

    except Exception as e:
        return f"Error: {e}"


def get_disk_usage(path: str = "home") -> str:
    try:
        target = _resolve_path(path)
        usage  = shutil.disk_usage(target)
        pct    = usage.used / usage.total * 100
        return (
            f"Disk usage ({target}):\n"
            f"  Total : {_format_size(usage.total)}\n"
            f"  Used  : {_format_size(usage.used)} ({pct:.1f}%)\n"
            f"  Free  : {_format_size(usage.free)}"
        )
    except Exception as e:
        return f"Could not get disk usage: {e}"


def organize_desktop() -> str:
    type_map = {
        "Images":    {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico", ".heic"},
        "Documents": {".pdf", ".doc", ".docx", ".txt", ".xls", ".xlsx",
                      ".ppt", ".pptx", ".csv", ".odt", ".ods", ".odp"},
        "Videos":    {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v"},
        "Music":     {".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a"},
        "Archives":  {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"},
        "Code":      {".py", ".js", ".ts", ".html", ".css", ".json", ".xml",
                      ".cpp", ".java", ".cs", ".go", ".rs", ".sh"},
    }

    desktop = _get_desktop()
    moved, skipped = [], []
    journal: list[tuple[Path, Path]] = []   # (where it was, where it went)

    try:
        for item in desktop.iterdir():
            # Leave folders, hidden files and organize-folders untouched
            if item.is_dir() or item.name.startswith("."):
                continue
            if item.name in {k for k in type_map}:
                continue

            ext        = item.suffix.lower()
            target_dir = desktop / "Others"
            for folder, exts in type_map.items():
                if ext in exts:
                    target_dir = desktop / folder
                    break

            target_dir.mkdir(exist_ok=True)
            new_path = target_dir / item.name

            if new_path.exists():
                skipped.append(item.name)
                continue

            origin = item.resolve()
            shutil.move(str(item), str(new_path))
            journal.append((origin, new_path.resolve()))
            moved.append(f"{item.name} → {target_dir.name}/")

        # One command, dozens of moves — so one undo that reverses all of them.
        # Without this, "organize my desktop" is the single least reversible
        # thing the assistant can do to a person's files, and it was completely
        # ungated.
        if journal:
            def _undo_organize(entries=tuple(journal)):
                restored = 0
                for origin, moved_to in entries:
                    try:
                        if moved_to.exists():
                            origin.parent.mkdir(parents=True, exist_ok=True)
                            shutil.move(str(moved_to), str(origin))
                            restored += 1
                    except Exception as e:
                        print(f"[file] undo organize: {moved_to.name}: {e}")
                # Clear away the folders we created, but only while they are
                # empty — anything the user put in since stays.
                for folder in {m.parent for _o, m in entries}:
                    try:
                        if folder.exists() and folder.is_dir() and not any(folder.iterdir()):
                            folder.rmdir()
                    except Exception:
                        pass
                return f"{restored} file(s) put back on the desktop."
            push_undo(f"organized the desktop ({len(journal)} files)", _undo_organize)

        result = f"Desktop organized: {len(moved)} files moved."
        if moved:
            preview = moved[:8]
            result += "\n" + "\n".join(preview)
            if len(moved) > 8:
                result += f"\n... and {len(moved) - 8} more."
        if skipped:
            result += f"\n{len(skipped)} file(s) skipped (name conflict)."
        return result

    except Exception as e:
        return f"Could not organize desktop: {e}"


def get_file_info(path: str, name: str = "") -> str:
    try:
        base   = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        if not target.exists():
            return f"Not found: {target.name}"

        stat = target.stat()
        info = {
            "Name":      target.name,
            "Type":      "Folder" if target.is_dir() else "File",
            "Size":      _format_size(stat.st_size),
            "Location":  str(target.parent),
            "Created":   datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M"),
            "Modified":  datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "Extension": target.suffix or "—",
        }
        return "\n".join(f"  {k}: {v}" for k, v in info.items())

    except Exception as e:
        return f"Could not get file info: {e}"

def file_controller(
    parameters: dict = None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters or {}
    raw_action = params.get("action", "")
    path = params.get("path", "desktop")
    name = params.get("name", "")
    if not isinstance(raw_action, str):
        return outcome.failed("file_controller", "action must be text")
    if not isinstance(path, str) or not isinstance(name, str):
        return outcome.failed("file_controller", "path and name must be text")
    if len(path) > 4096 or len(name) > 255:
        return outcome.failed(
            "file_controller", "path is limited to 4096 characters and name to 255"
        )
    action = raw_action.lower().strip()

    if player:
        print(f"[File] {action}")

    try:
        if action == "list":
            return list_files(path)

        elif action == "create_file":
            content = params.get("content", "")
            if not isinstance(content, str) or len(content) > 1_000_000:
                return outcome.failed(
                    "file_controller",
                    "file content must be text no larger than 1000000 characters",
                    action=action,
                )
            target_path = _resolve_path(path) / name if name else _resolve_path(path)
            return action_policy.request_confirmation(
                "file_controller",
                action,
                title="Create or replace this file?",
                detail=(
                    f"Target: {target_path}\n\n"
                    f"Complete file contents:\n{content}"
                ),
                run=lambda p=path, n=name, c=content: create_file(p, name=n, content=c),
                arguments={"action": action},
            )

        elif action == "create_folder":
            target_path = (_resolve_path(path) / name) if name else _resolve_path(path)
            if not _is_safe_path(target_path):
                return outcome.failed(
                    "file_controller",
                    "folder target is outside the permitted user directory",
                    action=action,
                )
            if target_path.exists():
                return f"Folder already exists: {target_path.name}"
            return action_policy.request_confirmation(
                "file_controller",
                action,
                title="Create this folder?",
                detail=f"Exact folder path:\n{target_path}",
                run=lambda p=path, n=name: create_folder(p, name=n),
                arguments={"action": action},
            )

        elif action == "delete":
            target_label = str(params.get("name") or path).strip()
            if confirm.pending_title():
                return outcome.ask(
                    "file_controller",
                    "another confirmation is already waiting on the HUD; "
                    "nothing was deleted",
                    action=action,
                    target=target_label[:160],
                )
            target = str(Path(path) / name) if name else str(path)
            return action_policy.request_confirmation(
                "file_controller",
                action,
                title="Move this item to the Recycle Bin?",
                detail=target,
                run=lambda p=path, n=name: delete_file(p, name=n),
                arguments={"action": action},
            )

        elif action == "move":
            destination = params.get("destination", "")
            if not isinstance(destination, str) or len(destination) > 4096:
                return outcome.failed(
                    "file_controller", "destination must be text no longer than 4096 characters"
                )
            if not destination.strip():
                return move_file(path, name=name, destination=destination)
            source_path = _resolve_path(path) / name if name else _resolve_path(path)
            destination_path = _resolve_path(destination)
            if destination_path.is_dir():
                destination_path = destination_path / source_path.name
            return action_policy.request_confirmation(
                "file_controller",
                action,
                title="Move this file or folder?",
                detail=f"From: {source_path}\nTo: {destination_path}",
                run=lambda p=path, n=name, d=destination: move_file(
                    p, name=n, destination=d
                ),
                arguments={"action": action},
            )

        elif action == "copy":
            destination = params.get("destination", "")
            if not isinstance(destination, str) or len(destination) > 4096:
                return outcome.failed(
                    "file_controller",
                    "destination must be text no longer than 4096 characters",
                )
            if not destination.strip():
                return copy_file(path, name=name, destination=destination)
            source_path = _resolve_path(path) / name if name else _resolve_path(path)
            destination_path = _resolve_path(destination)
            if destination_path.is_dir():
                destination_path = destination_path / source_path.name
            return action_policy.request_confirmation(
                "file_controller",
                action,
                title="Copy this file or folder?",
                detail=f"From: {source_path}\nTo: {destination_path}",
                run=lambda p=path, n=name, d=destination: copy_file(
                    p, name=n, destination=d
                ),
                arguments={"action": action},
            )

        elif action == "rename":
            new_name = params.get("new_name", "")
            if not isinstance(new_name, str):
                return outcome.failed(
                    "file_controller", "new_name must be text", action=action
                )
            if (
                not new_name
                or new_name in {".", ".."}
                or len(new_name) > 255
                or any(separator in new_name for separator in ("/", "\\", ":"))
                or new_name.endswith((" ", "."))
            ):
                return outcome.failed(
                    "file_controller",
                    "new_name must be a single safe filename of at most 255 characters",
                    action=action,
                )
            source_path = _resolve_path(path) / name if name else _resolve_path(path)
            destination_path = source_path.parent / new_name
            if not _is_safe_path(source_path) or not _is_safe_path(destination_path):
                return outcome.failed(
                    "file_controller",
                    "rename source and destination must stay inside the permitted user directory",
                    action=action,
                )
            if not source_path.exists():
                return outcome.failed(
                    "file_controller", "rename source does not exist", action=action
                )
            if destination_path.exists():
                return outcome.failed(
                    "file_controller", "rename destination already exists", action=action
                )
            return action_policy.request_confirmation(
                "file_controller",
                action,
                title="Rename this file or folder?",
                detail=f"From:\n{source_path}\nTo:\n{destination_path}",
                run=lambda p=path, n=name, nn=new_name: rename_file(
                    p, name=n, new_name=nn
                ),
                arguments={"action": action},
            )

        elif action == "read":
            return read_file(path, name=name)

        elif action == "write":
            content = params.get("content", "")
            if not isinstance(content, str) or len(content) > 1_000_000:
                return outcome.failed(
                    "file_controller",
                    "file content must be text no larger than 1000000 characters",
                    action=action,
                )
            target_path = _resolve_path(path) / name if name else _resolve_path(path)
            append = params.get("append", False)
            if not isinstance(append, bool):
                return outcome.failed("file_controller", "append must be a boolean")
            return action_policy.request_confirmation(
                "file_controller",
                action,
                title="Write to this file?",
                detail=(
                    f"Target: {target_path}\n"
                    f"Mode: {'append' if append else 'replace'}"
                    f"\n\nComplete content:\n{content}"
                ),
                run=lambda p=path, n=name, c=content, a=append: write_file(
                    p, name=n, content=c, append=a
                ),
                arguments={"action": action},
            )

        elif action == "find":
            return find_files(
                name=name or params.get("name", ""),
                extension=params.get("extension", ""),
                path=path,
                max_results=min(int(params.get("max_results", 20)), 50),
            )

        elif action == "largest":
            return get_largest_files(
                path=path,
                count=int(params.get("count", 10)),
            )

        elif action == "disk_usage":
            return get_disk_usage(path)

        elif action == "organize_desktop":
            return action_policy.request_confirmation(
                "file_controller",
                action,
                title="Organize files on the Desktop?",
                detail=(
                    "This may move multiple Desktop files into folders based "
                    "on their file types."
                ),
                run=organize_desktop,
                arguments={"action": action},
            )

        elif action == "info":
            return get_file_info(path, name=name)

        else:
            return f"Unknown action: '{action}'"

    except Exception as e:
        return f"File controller error ({action}): {e}"


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "file_controller",
    "description": "Manages files and folders: list, create, delete, move, copy, rename, read, write, find, disk usage.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "list | create_file | create_folder | delete | move | copy | rename | read | write | find | largest | disk_usage | organize_desktop | info"
            },
            "path": {
                "type": "STRING",
                "description": "File/folder path or shortcut: desktop, downloads, documents, home"
            },
            "destination": {
                "type": "STRING",
                "description": "Destination path for move/copy"
            },
            "new_name": {
                "type": "STRING",
                "description": "New name for rename"
            },
            "content": {
                "type": "STRING",
                "description": "Content for create_file/write"
            },
            "name": {
                "type": "STRING",
                "description": "File name to search for"
            },
            "extension": {
                "type": "STRING",
                "description": "File extension to search (e.g. .pdf)"
            },
            "count": {
                "type": "INTEGER",
                "description": "Number of results for largest"
            }
        },
        "required": [
            "action"
        ]
    },
    "handler": file_controller,
}
