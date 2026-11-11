"""
file_processor.py — JARVIS Universal File Processor

Supported types:
  image   → describe, ocr, resize, convert, compress, crop
  pdf     → summarize, extract_text, extract_pages, to_word
  docx    → summarize, extract_text, reformat, translate_hint
  txt/md  → summarize, reformat, translate_hint, word_count
  csv     → analyze, filter, sort, convert, stats
  xlsx    → analyze, filter, convert, stats
  json    → validate, format, extract, convert
  code    → explain, review, fix, run, document
  audio   → transcribe, trim, convert, info
  video   → trim, extract_audio, extract_frame, info, compress
  zip     → list, extract
  pptx    → summarize, extract_text, to_pdf
"""

import os
import re
import json
import csv
import subprocess
import tempfile
import zipfile
from pathlib import Path
from datetime import datetime

# Model choice, timeout and fallback ladder all live in core/gemini.py.
from core import action_policy, gemini, outcome

def _get_api_key() -> str:
    from memory.config_manager import get_gemini_key

    key = get_gemini_key()
    if not key:
        raise RuntimeError("No Gemini API key is configured.")
    return key


def _gemini_client(tier: str = gemini.SMART):
    """Summarising documents and reading images — the reasoning tier, with a
    long deadline because the input can be a whole file."""
    class _W:
        def generate_content(self, contents):
            resp = gemini.call(contents, tier=tier, timeout_ms=90000)
            if resp is None:
                raise RuntimeError("every Gemini model on the ladder failed")
            return resp

    return _W()


def _detect_type(path: Path) -> str:
    ext = path.suffix.lower().lstrip(".")
    image_exts = {"jpg", "jpeg", "png", "gif", "webp", "bmp", "tiff", "svg", "ico"}
    video_exts = {"mp4", "avi", "mov", "mkv", "wmv", "flv", "webm", "m4v", "3gp"}
    audio_exts = {"mp3", "wav", "ogg", "m4a", "aac", "flac", "wma", "opus"}
    code_exts  = {"py", "js", "ts", "jsx", "tsx", "html", "css", "java", "c",
                  "cpp", "cs", "go", "rs", "rb", "php", "swift", "kt", "sh",
                  "bash", "ps1", "lua", "r", "m", "sql", "yaml", "toml"}
    archive_exts = {"zip", "rar", "tar", "gz", "7z", "bz2", "xz"}

    if ext in image_exts:  return "image"
    if ext in video_exts:  return "video"
    if ext in audio_exts:  return "audio"
    if ext in code_exts:   return "code"
    if ext in archive_exts: return "archive"
    if ext == "pdf":       return "pdf"
    if ext in ("docx", "doc"): return "docx"
    if ext in ("txt", "md", "rst", "log"): return "text"
    if ext in ("csv", "tsv"): return "csv"
    if ext in ("xlsx", "xls", "ods"): return "excel"
    if ext == "json":      return "json"
    if ext == "xml":       return "xml"
    if ext in ("pptx", "ppt"): return "pptx"
    return "unknown"


def _file_size_str(path: Path) -> str:
    size = path.stat().st_size
    if size < 1024:        return f"{size} B"
    if size < 1024**2:     return f"{size/1024:.1f} KB"
    if size < 1024**3:     return f"{size/1024**2:.1f} MB"
    return f"{size/1024**3:.1f} GB"

def _output_path(src: Path, suffix: str, new_ext: str = None) -> Path:
    ext  = new_ext or src.suffix
    name = f"{src.stem}_{suffix}{ext}"
    return src.parent / name


_DEFAULT_FILE_ACTIONS = {
    "image": "describe", "pdf": "summarize", "docx": "summarize",
    "text": "summarize", "csv": "analyze", "excel": "analyze",
    "json": "analyze", "xml": "analyze", "code": "explain",
    "audio": "transcribe", "video": "info", "archive": "list",
    "pptx": "summarize",
}

_LOCAL_DOCUMENT_ACTIONS = {"extract_preview", "search"}
_LOCAL_DOCUMENT_TYPES = {"docx", "text", "csv", "excel"}
_LOCAL_DOCUMENT_EXTENSIONS = {
    ".docx", ".txt", ".md", ".rst", ".log", ".csv", ".tsv", ".xlsx"
}
_LOCAL_DOCUMENT_MAX_BYTES = 20 * 1024 * 1024
_LOCAL_DOCUMENT_MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
_LOCAL_DOCUMENT_MAX_ARCHIVE_ENTRIES = 10_000
_LOCAL_DOCUMENT_MAX_CHARS = 12_000
_LOCAL_DOCUMENT_MAX_ROWS = 100
_LOCAL_DOCUMENT_MAX_COLUMNS = 40
_LOCAL_DOCUMENT_MAX_SHEETS = 10
_LOCAL_DOCUMENT_MAX_MATCHES = 20
_LOCAL_DOCUMENT_MAX_QUERY_LENGTH = 256


def _default_file_action(file_type: str) -> str:
    return _DEFAULT_FILE_ACTIONS.get(file_type, "")


def _safe_format_extension(value: object, default: str) -> str:
    extension = str(value or default).strip().lower().lstrip(".")
    if not re.fullmatch(r"[a-z0-9]{1,10}", extension):
        raise ValueError("invalid output format")
    return extension


def _file_processor_failed(result: object) -> bool:
    text = str(result or "").strip().lower()
    return (
        text.startswith(("could not ", "invalid ", "unsupported ", "processing failed"))
        or " failed:" in text
        or "not installed" in text
        or "not found" in text
    )


def _file_processor_output_target(
    path: Path, file_type: str, action: str, params: dict
) -> tuple[Path | None, str]:
    """Return the exact output path for actions that may create a file."""
    action = action or _default_file_action(file_type)
    save = params.get("save", True)

    if file_type == "image":
        if action in ("describe", "ocr", "analyze", "read", "extract_text"):
            if save:
                return _output_path(path, "result", ".txt"), "if the generated result is longer than 500 characters"
            return None, ""
        if action == "resize":
            from PIL import Image
            with Image.open(path) as image:
                width, height = image.size
            scale = float(params.get("scale", 0))
            requested_width = int(params.get("width", 0))
            requested_height = int(params.get("height", 0))
            if scale:
                size = (int(width * scale), int(height * scale))
            elif requested_width and requested_height:
                size = (requested_width, requested_height)
            elif requested_width:
                size = (requested_width, int(height * requested_width / width))
            elif requested_height:
                size = (int(width * requested_height / height), requested_height)
            else:
                return None, ""
            return _output_path(path, f"resized_{size[0]}x{size[1]}"), ""
        if action == "convert":
            fmt = _safe_format_extension(params.get("format"), "png")
            return _output_path(path, "converted", f".{fmt}"), ""
        if action == "compress":
            quality = int(params.get("quality", 70))
            return _output_path(path, f"compressed_q{quality}", ".jpg"), ""
        if action not in ("info",):
            return _output_path(path, "result", ".txt"), "if the generated result is longer than 500 characters"

    if file_type == "pdf":
        if action == "extract_text":
            return _output_path(path, "text", ".txt"), ""
        if action == "to_word":
            return _output_path(path, "converted", ".docx"), ""
        if action in ("summarize", "translate_hint", "analyze", "reformat") and save:
            return _output_path(path, action, ".txt"), "if the generated result is longer than 600 characters"

    if file_type in ("text", "docx"):
        if action == "extract_text" and file_type != "text":
            return _output_path(path, "extracted", ".txt"), ""
        if action not in (
            "word_count", "extract_text", *_LOCAL_DOCUMENT_ACTIONS
        ) and save:
            suffix = action if action in (
                "summarize", "analyze", "reformat", "fix",
                "translate_hint", "to_bullet", "custom",
            ) else "custom"
            return _output_path(path, suffix, ".txt"), "if the generated result is longer than 600 characters"

    if file_type in ("csv", "excel"):
        if action in ("convert", "to_csv", "to_excel", "to_json"):
            fmt = {
                "to_csv": "csv", "to_excel": "xlsx", "to_json": "json",
                "convert": _safe_format_extension(params.get("format"), "csv"),
            }[action]
            if fmt in ("csv", "xlsx", "json"):
                return _output_path(path, "converted", f".{fmt}"), ""
        if action == "filter":
            return _output_path(path, "filtered", ".csv"), ""
        if action == "sort":
            return _output_path(path, "sorted", path.suffix), ""

    if file_type in ("json", "xml"):
        if action == "format":
            return _output_path(path, "formatted", ".json"), ""
        if action == "to_csv":
            return _output_path(path, "converted", ".csv"), ""

    if file_type == "code" and action in ("fix", "optimize", "document") and save:
        return _output_path(path, action), ""

    if file_type == "audio":
        if action == "transcribe" and save:
            return _output_path(path, "transcript", ".txt"), ""
        if action == "convert":
            fmt = _safe_format_extension(params.get("format"), "mp3")
            return _output_path(path, "converted", f".{fmt}"), ""
        if action == "trim":
            start = float(params.get("start", 0))
            end = float(params.get("end", 0))
            return _output_path(path, f"trim_{int(start)}s_{int(end)}s"), ""

    if file_type == "video":
        if action == "extract_audio":
            return _output_path(path, "audio", ".mp3"), ""
        if action == "trim":
            return _output_path(path, "trim", path.suffix), ""
        if action == "extract_frame":
            timestamp = str(params.get("timestamp", "00:00:01"))
            return _output_path(path, f"frame_{timestamp.replace(':', '')}", ".jpg"), ""
        if action == "compress":
            quality = int(params.get("quality", 28))
            return _output_path(path, f"compressed_crf{quality}", ".mp4"), ""
        if action == "convert":
            fmt = _safe_format_extension(params.get("format"), "mp4")
            return _output_path(path, "converted", f".{fmt}"), ""

    if file_type == "pptx" and action == "extract_text":
        return _output_path(path, "text", ".txt"), ""

    return None, ""


def _process_image(path: Path, action: str, params: dict, speak=None) -> str:
    try:
        from PIL import Image
    except ImportError:
        return "Pillow is not installed. Run: pip install Pillow"

    action = action or "describe"

    if action in ("describe", "ocr", "analyze", "read", "extract_text"):
        try:
            model  = _gemini_client()
            img    = Image.open(path)
            prompt = {
                "describe": "Describe this image in detail.",
                "ocr":      "Extract all text visible in this image. Return only the text, formatted clearly.",
                "analyze":  "Analyze this image thoroughly: objects, colors, composition, any text, context.",
                "read":     "Read all text in this image, preserving structure and formatting.",
                "extract_text": "Extract all text from this image.",
            }.get(action, "Describe this image.")

            if params.get("instruction"):
                prompt = params["instruction"]

            response = model.generate_content([prompt, img])
            result   = response.text.strip()

            if len(result) > 500 and params.get("save", True):
                out = _output_path(path, "result", ".txt")
                out.write_text(result, encoding="utf-8")
                return f"{result[:300]}...\n\nFull result saved to: {out}"
            return result
        except Exception as e:
            return f"AI image analysis failed: {e}"

    if action == "resize":
        width  = int(params.get("width",  0))
        height = int(params.get("height", 0))
        scale  = float(params.get("scale", 0))
        try:
            img = Image.open(path)
            w, h = img.size
            if scale:
                new_size = (int(w * scale), int(h * scale))
            elif width and height:
                new_size = (width, height)
            elif width:
                new_size = (width, int(h * width / w))
            elif height:
                new_size = (int(w * height / h), height)
            else:
                return "Please specify width, height, or scale."
            out = _output_path(path, f"resized_{new_size[0]}x{new_size[1]}")
            img.resize(new_size, Image.LANCZOS).save(out)
            return f"Resized from {w}x{h} to {new_size[0]}x{new_size[1]}. Saved: {out.name}"
        except Exception as e:
            return f"Resize failed: {e}"

    if action == "convert":
        fmt = params.get("format", "png").lower().strip(".")
        fmt_map = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG",
                   "webp": "WEBP", "bmp": "BMP", "tiff": "TIFF"}
        pil_fmt = fmt_map.get(fmt, fmt.upper())
        try:
            img = Image.open(path).convert("RGB") if fmt == "jpg" else Image.open(path)
            out = _output_path(path, "converted", f".{fmt}")
            img.save(out, pil_fmt)
            return f"Converted to {fmt.upper()}. Saved: {out.name}"
        except Exception as e:
            return f"Convert failed: {e}"

    if action == "compress":
        quality = int(params.get("quality", 70))
        try:
            img = Image.open(path).convert("RGB")
            out = _output_path(path, f"compressed_q{quality}", ".jpg")
            img.save(out, "JPEG", quality=quality, optimize=True)
            before = _file_size_str(path)
            after  = _file_size_str(out)
            return f"Compressed: {before} → {after}. Saved: {out.name}"
        except Exception as e:
            return f"Compress failed: {e}"

    if action == "info":
        try:
            img = Image.open(path)
            return (f"Image info: {img.format}, {img.size[0]}x{img.size[1]}px, "
                    f"mode: {img.mode}, size: {_file_size_str(path)}")
        except Exception as e:
            return f"Info failed: {e}"

    return _process_image(path, "describe", {"instruction": f"{action}: {params}"})

def _process_pdf(path: Path, action: str, params: dict, speak=None) -> str:
    action = action or "summarize"

    def _extract_pdf_text(max_chars=50000) -> str:
        text = ""
        try:
            import pdfplumber
            with pdfplumber.open(path) as pdf:
                for page in pdf.pages:
                    text += (page.extract_text() or "") + "\n"
        except ImportError:
            try:
                import PyPDF2
                with open(path, "rb") as f:
                    reader = PyPDF2.PdfReader(f)
                    for page in reader.pages:
                        text += page.extract_text() + "\n"
            except ImportError:
                return ""
        return text[:max_chars]

    if action in ("summarize", "extract_text", "translate_hint", "analyze", "reformat"):
        text = _extract_pdf_text()
        if not text.strip():
            return "Could not extract text from PDF (may be scanned/image-based)."

        if action == "extract_text":
            out = _output_path(path, "text", ".txt")
            out.write_text(text, encoding="utf-8")
            return f"Text extracted ({len(text)} chars). Saved: {out.name}"

        prompt_map = {
            "summarize":      f"Summarize this PDF document concisely:\n\n{text}",
            "analyze":        f"Analyze this document thoroughly:\n\n{text}",
            "translate_hint": f"What language is this document in and what does it say? Summarize:\n\n{text}",
            "reformat":       f"Reformat this text cleanly with proper structure:\n\n{text}",
        }
        try:
            model    = _gemini_client()
            response = model.generate_content(prompt_map.get(action, f"Analyze:\n\n{text}"))
            result   = response.text.strip()
            if len(result) > 600 and params.get("save", True):
                out = _output_path(path, action, ".txt")
                out.write_text(result, encoding="utf-8")
                return f"{result[:400]}...\n\nFull result saved: {out.name}"
            return result
        except Exception as e:
            return f"AI analysis failed: {e}"

    if action == "info":
        try:
            import pdfplumber
            with pdfplumber.open(path) as pdf:
                pages = len(pdf.pages)
            return f"PDF: {pages} pages, size: {_file_size_str(path)}"
        except Exception:
            return f"PDF size: {_file_size_str(path)}"

    if action == "to_word":
        text = _extract_pdf_text()
        if not text:
            return "Could not extract text to convert."
        try:
            from docx import Document
            doc  = Document()
            doc.add_heading(path.stem, 0)
            for para in text.split("\n\n"):
                if para.strip():
                    doc.add_paragraph(para.strip())
            out = _output_path(path, "converted", ".docx")
            doc.save(out)
            return f"Converted to Word document. Saved: {out.name}"
        except ImportError:
            return "python-docx not installed. Run: pip install python-docx"

    return f"Unknown PDF action: '{action}'. Try: summarize, extract_text, info, to_word"

def _process_text_doc(path: Path, file_type: str, action: str,
                       params: dict, speak=None) -> str:
    action = action or "summarize"

    if action in _LOCAL_DOCUMENT_ACTIONS:
        content = _read_local_document(path, file_type)
        return _local_text_result(
            content,
            action,
            params.get("query"),
        )

    def _read_content() -> str:
        if file_type == "docx":
            try:
                from docx import Document
                doc  = Document(path)
                return "\n".join(p.text for p in doc.paragraphs)
            except ImportError:
                return "python-docx not installed."
            except Exception as e:
                return f"Read failed: {e}"
        else:
            return path.read_text(encoding="utf-8", errors="ignore")

    content = _read_content()
    if not content.strip():
        return "File appears to be empty."

    if action == "word_count":
        words = len(content.split())
        chars = len(content)
        lines = content.count("\n")
        return f"Word count: {words} words, {chars} characters, {lines} lines."

    if action == "extract_text":
        if file_type != "txt":
            out = _output_path(path, "extracted", ".txt")
            out.write_text(content, encoding="utf-8")
            return f"Text extracted. Saved: {out.name}"
        return content[:2000]

    instruction = params.get("instruction", "")
    prompt_map  = {
        "summarize":  f"Summarize this document concisely:\n\n{content[:40000]}",
        "analyze":    f"Analyze this document:\n\n{content[:40000]}",
        "reformat":   f"Reformat this text with clean structure, proper headings and paragraphs:\n\n{content[:40000]}",
        "fix":        f"Fix grammar, spelling and style issues in this text:\n\n{content[:40000]}",
        "translate_hint": f"What language is this and what does it say? Summarize:\n\n{content[:10000]}",
        "to_bullet":  f"Convert this text into a clear bullet-point summary:\n\n{content[:40000]}",
        "custom":     f"{instruction}\n\n{content[:40000]}",
    }

    if action not in prompt_map:
        action  = "custom"
        instruction = params.get("instruction", "")

    try:
        model    = _gemini_client()
        response = model.generate_content(prompt_map[action])
        result   = response.text.strip()
        if len(result) > 600 and params.get("save", True):
            out = _output_path(path, action, ".txt")
            out.write_text(result, encoding="utf-8")
            return f"{result[:400]}...\n\nFull result saved: {out.name}"
        return result
    except Exception as e:
        return f"AI processing failed: {e}"


def _read_local_document(path: Path, file_type: str) -> str:
    if file_type != "docx":
        return path.read_text(encoding="utf-8", errors="replace")

    from docx import Document

    document = Document(path)
    lines = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            lines.append(" | ".join(cell.text for cell in row.cells))
    return "\n".join(line for line in lines if line)


def _validate_local_document_archive(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError("invalid document container") from exc

    if len(entries) > _LOCAL_DOCUMENT_MAX_ARCHIVE_ENTRIES:
        raise ValueError("document container has too many entries")
    expanded_size = sum(entry.file_size for entry in entries)
    if expanded_size > _LOCAL_DOCUMENT_MAX_ARCHIVE_BYTES:
        raise ValueError("document container exceeds the expanded-size limit")


def _validate_local_csv_width(path: Path, delimiter: str) -> None:
    max_fields = _LOCAL_DOCUMENT_MAX_COLUMNS + 1
    fields = 1
    field_start = True
    in_quotes = False
    quote_pending = False

    with path.open("r", encoding="utf-8", errors="replace", newline="") as source:
        while chunk := source.read(64 * 1024):
            index = 0
            while index < len(chunk):
                char = chunk[index]
                index += 1

                if quote_pending:
                    quote_pending = False
                    if char == '"':
                        continue
                    in_quotes = False

                if in_quotes:
                    if char == '"':
                        quote_pending = True
                    continue

                if char == '"' and field_start:
                    in_quotes = True
                    field_start = False
                elif char == delimiter:
                    fields += 1
                    if fields > max_fields:
                        raise ValueError(
                            "CSV row exceeds the supported column limit"
                        )
                    field_start = True
                elif char in "\r\n":
                    fields = 1
                    field_start = True
                else:
                    field_start = False


def _truncate_local_output(result: str) -> str:
    if len(result) <= _LOCAL_DOCUMENT_MAX_CHARS:
        return result
    marker = "[Output truncated.]"
    if _LOCAL_DOCUMENT_MAX_CHARS <= len(marker):
        return marker[:_LOCAL_DOCUMENT_MAX_CHARS]
    return (
        result[:_LOCAL_DOCUMENT_MAX_CHARS - len(marker) - 1]
        + "\n"
        + marker
    )


def _local_text_result(content: str, action: str, query: object) -> str:
    lines = content.splitlines()
    if action == "search":
        if (
            not isinstance(query, str)
            or not query.strip()
            or len(query) > _LOCAL_DOCUMENT_MAX_QUERY_LENGTH
        ):
            raise ValueError(
                f"query must contain 1-{_LOCAL_DOCUMENT_MAX_QUERY_LENGTH} characters"
            )
        needle = query.casefold()
        matches = []
        additional_matches = False
        for index, line in enumerate(lines, start=1):
            if needle not in line.casefold():
                continue
            if len(matches) >= _LOCAL_DOCUMENT_MAX_MATCHES:
                additional_matches = True
                break
            preview = line[:500]
            if needle not in preview.casefold():
                preview += " [match is outside preview]"
            matches.append(f"line {index}: {preview}")
        result = "\n".join(matches) if matches else "No matches found."
        if additional_matches:
            result += "\nAdditional matches may exist."
    else:
        result = "\n".join(lines)
        if len(lines) > _LOCAL_DOCUMENT_MAX_ROWS:
            result = "\n".join(lines[:_LOCAL_DOCUMENT_MAX_ROWS])
            result += "\n[Preview truncated by row limit.]"
    return _truncate_local_output(result) or "The document contains no text."


def _process_data(path: Path, file_type: str, action: str,
                  params: dict, speak=None) -> str:
    action = action or "analyze"

    if action in _LOCAL_DOCUMENT_ACTIONS:
        return _process_local_table(path, file_type, action, params)

    try:
        import pandas as pd
    except ImportError:
        return "pandas not installed. Run: pip install pandas openpyxl"

    try:
        if file_type == "csv":
            df = pd.read_csv(path, encoding="utf-8", errors="replace")
        else:
            df = pd.read_excel(path)
    except Exception as e:
        return f"Could not read file: {e}"

    if action == "info":
        return (f"Rows: {len(df)}, Columns: {len(df.columns)}\n"
                f"Columns: {', '.join(df.columns.tolist())}\n"
                f"Size: {_file_size_str(path)}")

    if action == "stats":
        try:
            desc = df.describe(include="all").to_string()
            return f"Statistics:\n{desc[:2000]}"
        except Exception as e:
            return f"Stats failed: {e}"

    if action == "analyze":
        preview = df.head(50).to_string()
        prompt  = (f"Analyze this dataset. Columns: {list(df.columns)}\n"
                   f"Rows: {len(df)}\nPreview:\n{preview}\n\n"
                   f"Give insights, patterns, and notable findings.")
        try:
            model    = _gemini_client()
            response = model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            return f"AI analysis failed: {e}"

    if action in ("convert", "to_csv", "to_excel", "to_json"):
        fmt = {"to_csv": "csv", "to_excel": "xlsx", "to_json": "json",
               "convert": params.get("format", "csv")}.get(action, "csv")
        try:
            if fmt == "csv":
                out = _output_path(path, "converted", ".csv")
                df.to_csv(out, index=False, encoding="utf-8")
            elif fmt == "xlsx":
                out = _output_path(path, "converted", ".xlsx")
                df.to_excel(out, index=False)
            elif fmt == "json":
                out = _output_path(path, "converted", ".json")
                df.to_json(out, orient="records", force_ascii=False, indent=2)
            return f"Converted to {fmt.upper()}. Saved: {out.name}"
        except Exception as e:
            return f"Convert failed: {e}"

    if action == "filter":
        col       = params.get("column", "")
        value     = params.get("value", "")
        condition = params.get("condition", "equals")
        if not col or col not in df.columns:
            return f"Column '{col}' not found. Available: {', '.join(df.columns)}"
        try:
            if condition == "equals":     filtered = df[df[col] == value]
            elif condition == "contains": filtered = df[df[col].astype(str).str.contains(str(value), case=False)]
            elif condition == "gt":       filtered = df[df[col] > float(value)]
            elif condition == "lt":       filtered = df[df[col] < float(value)]
            else:                         filtered = df[df[col] == value]
            out = _output_path(path, "filtered", ".csv")
            filtered.to_csv(out, index=False)
            return f"Filtered: {len(filtered)} rows match. Saved: {out.name}"
        except Exception as e:
            return f"Filter failed: {e}"

    if action == "sort":
        col = params.get("column", df.columns[0])
        asc = params.get("ascending", True)
        try:
            sorted_df = df.sort_values(col, ascending=asc)
            out = _output_path(path, "sorted", path.suffix)
            sorted_df.to_csv(out, index=False)
            return f"Sorted by '{col}'. Saved: {out.name}"
        except Exception as e:
            return f"Sort failed: {e}"

    preview = df.head(30).to_string()
    try:
        model    = _gemini_client()
        response = model.generate_content(
            f"Task: {action}\nDataset ({len(df)} rows, cols: {list(df.columns)}):\n{preview}"
        )
        return response.text.strip()
    except Exception as e:
        return f"Processing failed: {e}"


def _process_local_table(
    path: Path, file_type: str, action: str, params: dict
) -> str:
    query = params.get("query")
    if action == "search" and (
        not isinstance(query, str)
        or not query.strip()
        or len(query) > _LOCAL_DOCUMENT_MAX_QUERY_LENGTH
    ):
        raise ValueError(
            f"query must contain 1-{_LOCAL_DOCUMENT_MAX_QUERY_LENGTH} characters"
        )

    sheets: list[tuple[str, list[object], list[tuple], bool, bool]] = []
    omitted_sheets = False
    if file_type == "csv":
        separator = "\t" if path.suffix.lower() == ".tsv" else ","
        with path.open("r", encoding="utf-8", errors="replace", newline="") as source:
            reader = csv.reader(source, delimiter=separator)
            columns = next(reader, [])
            rows = []
            has_more_rows = False
            has_more_columns = len(columns) > _LOCAL_DOCUMENT_MAX_COLUMNS
            for row_index, row in enumerate(reader):
                if row_index >= _LOCAL_DOCUMENT_MAX_ROWS:
                    has_more_rows = True
                    break
                has_more_columns = (
                    has_more_columns or len(row) > _LOCAL_DOCUMENT_MAX_COLUMNS
                )
                rows.append(tuple(row[:_LOCAL_DOCUMENT_MAX_COLUMNS + 1]))
        sheets.append(
            (
                "CSV",
                columns[:_LOCAL_DOCUMENT_MAX_COLUMNS + 1],
                rows,
                has_more_rows,
                has_more_columns,
            )
        )
    else:
        try:
            from openpyxl import load_workbook
        except ImportError as exc:
            raise RuntimeError("openpyxl is required to read XLSX files") from exc

        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            all_sheet_names = workbook.sheetnames
            names = all_sheet_names[:_LOCAL_DOCUMENT_MAX_SHEETS]
            for name in names:
                sheet = workbook[name]
                rows_iterator = sheet.iter_rows(
                    min_row=1,
                    max_row=_LOCAL_DOCUMENT_MAX_ROWS + 2,
                    max_col=_LOCAL_DOCUMENT_MAX_COLUMNS + 1,
                    values_only=True,
                )
                columns = list(next(rows_iterator, ()))
                rows = []
                has_more_rows = False
                for row_index, row in enumerate(rows_iterator):
                    if row_index >= _LOCAL_DOCUMENT_MAX_ROWS:
                        has_more_rows = True
                        break
                    rows.append(row)
                sheets.append(
                    (
                        name,
                        columns,
                        rows,
                        has_more_rows,
                        sheet.max_column > _LOCAL_DOCUMENT_MAX_COLUMNS,
                    )
                )
            omitted_sheets = len(all_sheet_names) > _LOCAL_DOCUMENT_MAX_SHEETS
        finally:
            workbook.close()

    needle = query.casefold() if isinstance(query, str) else ""
    output: list[str] = []
    match_count = 0
    omitted_content = omitted_sheets
    for sheet_name, columns, rows, has_more_rows, has_more_columns in sheets:
        omitted_content = omitted_content or has_more_rows or has_more_columns
        display_columns = [
            "" if value is None else str(value)[:500]
            for value in columns[:_LOCAL_DOCUMENT_MAX_COLUMNS]
        ]
        output.append(
            f"Sheet {sheet_name!r}; columns={json.dumps(display_columns, ensure_ascii=False)}"
        )

        for row_index, row in enumerate(rows, start=2):
            raw_values = [
                "" if value is None else str(value)
                for value in row[:_LOCAL_DOCUMENT_MAX_COLUMNS]
            ]
            values = [
                value[:500] + ("..." if len(value) > 500 else "")
                for value in raw_values
            ]
            if action == "search" and not any(
                needle in value.casefold() for value in raw_values
            ):
                continue
            if action == "search":
                match_count += 1
                values = [
                    value + " [match is outside preview]"
                    if needle in raw.casefold()
                    and needle not in raw[:500].casefold()
                    else value
                    for raw, value in zip(raw_values, values)
                ]
                output.append(
                    f"row {row_index}: {json.dumps(values, ensure_ascii=False)}"
                )
                if match_count >= _LOCAL_DOCUMENT_MAX_MATCHES:
                    break
            else:
                output.append(
                    f"row {row_index}: {json.dumps(values, ensure_ascii=False)}"
                )
        if action == "search" and match_count >= _LOCAL_DOCUMENT_MAX_MATCHES:
            output.append("[Search stopped at the match limit; more matches may exist.]")
            break
        if has_more_rows:
            output.append("[Additional rows omitted by limit.]")
        if has_more_columns:
            output.append("[Additional columns omitted by limit.]")

    if action == "search" and match_count == 0:
        if omitted_content:
            output.append(
                "No matches found in inspected content; some content was omitted by limits."
            )
        else:
            output.append("No matches found.")
    if omitted_sheets:
        output.append("[Additional sheets omitted by limit.]")
    result = "\n".join(output)
    return _truncate_local_output(result) or "The table contains no rows."


def _process_json(path: Path, action: str, params: dict, speak=None) -> str:
    action = action or "analyze"
    try:
        content = path.read_text(encoding="utf-8")
        data    = json.loads(content)
    except Exception as e:
        return f"Invalid JSON: {e}"

    if action == "validate":
        return f"Valid JSON. Type: {type(data).__name__}, size: {_file_size_str(path)}"

    if action == "format":
        out = _output_path(path, "formatted", ".json")
        out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return f"Formatted JSON saved: {out.name}"

    if action in ("analyze", "summarize", "extract"):
        preview = json.dumps(data, indent=2, ensure_ascii=False)[:8000]
        prompt  = f"Task: {action} this JSON data:\n{preview}"
        if params.get("instruction"):
            prompt = f"{params['instruction']}\n\nJSON data:\n{preview}"
        try:
            model    = _gemini_client()
            response = model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            return f"AI processing failed: {e}"

    if action == "to_csv":
        try:
            import pandas as pd
            if isinstance(data, list):
                df  = pd.DataFrame(data)
                out = _output_path(path, "converted", ".csv")
                df.to_csv(out, index=False)
                return f"Converted to CSV. Saved: {out.name}"
            return "JSON must be an array of objects to convert to CSV."
        except ImportError:
            return "pandas not installed."

    return _process_json(path, "analyze", {"instruction": action})

def _process_code(path: Path, action: str, params: dict, speak=None) -> str:
    action  = action or "explain"
    content = path.read_text(encoding="utf-8", errors="ignore")
    ext     = path.suffix.lstrip(".")

    if action == "run":
        return outcome.failed(
            "file_processor",
            "running uploaded code is disabled until a tested sandbox is available",
            action="run",
        )

    if action == "info":
        lines = content.count("\n")
        words = len(content.split())
        return f"Code file: {lines} lines, {words} words, {_file_size_str(path)}"

    prompt_map = {
        "explain":   f"Explain this {ext} code clearly:\n\n```{ext}\n{content[:30000]}\n```",
        "review":    f"Review this {ext} code for bugs, issues, and improvements:\n\n```{ext}\n{content[:30000]}\n```",
        "fix":       f"Fix any bugs in this {ext} code and return the corrected version:\n\n```{ext}\n{content[:30000]}\n```",
        "optimize":  f"Optimize this {ext} code for performance and readability:\n\n```{ext}\n{content[:30000]}\n```",
        "document":  f"Add proper documentation/comments to this {ext} code:\n\n```{ext}\n{content[:30000]}\n```",
        "summarize": f"Summarize what this {ext} code does:\n\n```{ext}\n{content[:30000]}\n```",
        "test":      f"Write unit tests for this {ext} code:\n\n```{ext}\n{content[:30000]}\n```",
    }

    instruction = params.get("instruction", "")
    if action not in prompt_map:
        prompt = f"{action}\n\n```{ext}\n{content[:30000]}\n```"
        if instruction:
            prompt = f"{instruction}\n\n```{ext}\n{content[:30000]}\n```"
    else:
        prompt = prompt_map[action]

    try:
        model    = _gemini_client()
        response = model.generate_content(prompt)
        result   = response.text.strip()

        if action in ("fix", "optimize", "document") and params.get("save", True):
            out = _output_path(path, action)
            code_match = re.search(r"```(?:\w+)?\n(.*?)```", result, re.DOTALL)
            code_to_save = code_match.group(1) if code_match else result
            out.write_text(code_to_save, encoding="utf-8")
            return f"{result[:400]}...\n\nSaved: {out.name}"
        return result
    except Exception as e:
        return f"AI processing failed: {e}"

def _process_audio(path: Path, action: str, params: dict, speak=None) -> str:
    action = action or "transcribe"

    if action == "info":
        try:
            from pydub import AudioSegment
            audio    = AudioSegment.from_file(path)
            duration = len(audio) / 1000
            mins, secs = divmod(int(duration), 60)
            return (f"Audio: {mins}m {secs}s, "
                    f"{audio.channels} ch, "
                    f"{audio.frame_rate}Hz, "
                    f"{_file_size_str(path)}")
        except ImportError:
            return f"Audio file: {_file_size_str(path)} (install pydub for more info)"
        except Exception as e:
            return f"Info failed: {e}"

    if action == "transcribe":
        try:
            model   = _gemini_client()
            content = path.read_bytes()
            mime    = {
                "mp3": "audio/mp3", "wav": "audio/wav",
                "ogg": "audio/ogg", "m4a": "audio/mp4",
                "aac": "audio/aac", "flac": "audio/flac",
            }.get(path.suffix.lstrip(".").lower(), "audio/mpeg")
            response = model.generate_content([
                "Transcribe all speech in this audio file accurately.",
                {"mime_type": mime, "data": content}
            ])
            result = response.text.strip()
            if params.get("save", True):
                out = _output_path(path, "transcript", ".txt")
                out.write_text(result, encoding="utf-8")
                return f"Transcription saved: {out.name}\n\nPreview: {result[:300]}"
            return result
        except Exception as e:
            return f"Transcription failed: {e}"

    if action == "convert":
        fmt = params.get("format", "mp3").lstrip(".")
        try:
            from pydub import AudioSegment
            audio = AudioSegment.from_file(path)
            out   = _output_path(path, "converted", f".{fmt}")
            audio.export(out, format=fmt)
            return f"Converted to {fmt.upper()}. Saved: {out.name}"
        except ImportError:
            return "pydub not installed. Run: pip install pydub"
        except Exception as e:
            return f"Convert failed: {e}"

    if action == "trim":
        start = float(params.get("start", 0))
        end   = float(params.get("end",   0))
        try:
            from pydub import AudioSegment
            audio   = AudioSegment.from_file(path)
            end_ms  = int(end * 1000)   if end   else len(audio)
            trimmed = audio[int(start * 1000):end_ms]
            out     = _output_path(path, f"trim_{int(start)}s_{int(end)}s")
            trimmed.export(out, format=path.suffix.lstrip("."))
            return f"Trimmed audio ({int(start)}s–{int(end)}s). Saved: {out.name}"
        except ImportError:
            return "pydub not installed."
        except Exception as e:
            return f"Trim failed: {e}"

    return f"Unknown audio action: '{action}'. Try: transcribe, info, convert, trim"

def _process_video(path: Path, action: str, params: dict, speak=None) -> str:
    action = action or "info"


    def _ffmpeg_available() -> bool:
        try:
            subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=3)
            return True
        except Exception:
            return False

    if action == "info":
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json",
                 "-show_format", "-show_streams", str(path)],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10
            )
            data     = json.loads(result.stdout)
            fmt      = data.get("format", {})
            duration = float(fmt.get("duration", 0))
            mins, secs = divmod(int(duration), 60)
            size     = _file_size_str(path)
            streams  = data.get("streams", [])
            video_s  = next((s for s in streams if s["codec_type"] == "video"), {})
            w        = video_s.get("width", "?")
            h        = video_s.get("height", "?")
            fps      = video_s.get("r_frame_rate", "?")
            return f"Video: {mins}m {secs}s, {w}x{h}, {fps} fps, {size}"
        except Exception:
            return f"Video file: {_file_size_str(path)}"

    if action == "extract_audio":
        if not _ffmpeg_available():
            return "ffmpeg not found. Install ffmpeg to extract audio."
        out = _output_path(path, "audio", ".mp3")
        try:
            subprocess.run(
                ["ffmpeg", "-i", str(path), "-q:a", "0", "-map", "a", str(out), "-y"],
                capture_output=True, timeout=300
            )
            return f"Audio extracted. Saved: {out.name}"
        except Exception as e:
            return f"Extract audio failed: {e}"

    if action == "trim":
        start = params.get("start", "00:00:00")
        end   = params.get("end",   "")
        if not _ffmpeg_available():
            return "ffmpeg not found."
        out = _output_path(path, f"trim", path.suffix)
        try:
            cmd = ["ffmpeg", "-i", str(path), "-ss", str(start)]
            if end:
                cmd += ["-to", str(end)]
            cmd += ["-c", "copy", str(out), "-y"]
            subprocess.run(cmd, capture_output=True, timeout=600)
            return f"Trimmed video saved: {out.name}"
        except Exception as e:
            return f"Trim failed: {e}"

    if action == "extract_frame":
        timestamp = params.get("timestamp", "00:00:01")
        if not _ffmpeg_available():
            return "ffmpeg not found."
        out = _output_path(path, f"frame_{timestamp.replace(':', '')}", ".jpg")
        try:
            subprocess.run(
                ["ffmpeg", "-i", str(path), "-ss", timestamp,
                 "-vframes", "1", str(out), "-y"],
                capture_output=True, timeout=30
            )
            return f"Frame extracted at {timestamp}. Saved: {out.name}"
        except Exception as e:
            return f"Extract frame failed: {e}"

    if action == "compress":
        crf = int(params.get("quality", 28))  
        if not _ffmpeg_available():
            return "ffmpeg not found."
        out = _output_path(path, f"compressed_crf{crf}", ".mp4")
        try:
            subprocess.run(
                ["ffmpeg", "-i", str(path),
                 "-c:v", "libx264", "-crf", str(crf),
                 "-preset", "medium", "-c:a", "copy",
                 str(out), "-y"],
                capture_output=True, timeout=1800
            )
            before = _file_size_str(path)
            after  = _file_size_str(out)
            return f"Compressed: {before} → {after}. Saved: {out.name}"
        except Exception as e:
            return f"Compress failed: {e}"

    if action == "transcribe":
        if not _ffmpeg_available():
            return "ffmpeg not found. Needed for video transcription."
        with tempfile.NamedTemporaryFile(
            prefix="mark-transcription-", suffix=".mp3", delete=False
        ) as audio_file:
            tmp_audio = Path(audio_file.name)
        try:
            subprocess.run(
                ["ffmpeg", "-i", str(path), "-q:a", "0", "-map", "a",
                 str(tmp_audio), "-y"],
                capture_output=True, timeout=300
            )
            result = _process_audio(
                tmp_audio, "transcribe", {**params, "save": False}, speak
            )
            return result
        except Exception as e:
            return f"Video transcription failed: {e}"
        finally:
            if tmp_audio.exists():
                tmp_audio.unlink()

    if action == "convert":
        fmt = params.get("format", "mp4").lstrip(".")
        if not _ffmpeg_available():
            return "ffmpeg not found."
        out = _output_path(path, "converted", f".{fmt}")
        try:
            subprocess.run(
                ["ffmpeg", "-i", str(path), str(out), "-y"],
                capture_output=True, timeout=1800
            )
            return f"Converted to {fmt.upper()}. Saved: {out.name}"
        except Exception as e:
            return f"Convert failed: {e}"

    return f"Unknown video action: '{action}'. Try: info, trim, extract_audio, extract_frame, compress, transcribe, convert"

def _process_archive(path: Path, action: str, params: dict, speak=None) -> str:
    action = action or "list"

    if action == "list":
        try:
            import zipfile, tarfile
            ext = path.suffix.lower()
            if ext == ".zip":
                with zipfile.ZipFile(path) as z:
                    names = z.namelist()
            elif ext in (".tar", ".gz", ".bz2", ".xz"):
                with tarfile.open(path) as t:
                    names = t.getnames()
            else:
                return f"Unsupported archive format: {ext}"
            preview = "\n".join(names[:30])
            suffix  = f"\n... and {len(names)-30} more" if len(names) > 30 else ""
            return f"Archive contains {len(names)} files:\n{preview}{suffix}"
        except Exception as e:
            return f"List failed: {e}"

    if action == "extract":
        return outcome.failed(
            "file_processor",
            "archive extraction is disabled until safe path and resource limits are implemented",
            action="extract",
        )

    return f"Unknown archive action: '{action}'. Try: list, extract"

def _process_pptx(path: Path, action: str, params: dict, speak=None) -> str:
    action = action or "summarize"

    def _read_pptx_text() -> str:
        try:
            from pptx import Presentation
            prs  = Presentation(path)
            text = []
            for i, slide in enumerate(prs.slides, 1):
                slide_text = f"\n--- Slide {i} ---\n"
                for shape in slide.shapes:
                    if hasattr(shape, "text") and shape.text.strip():
                        slide_text += shape.text.strip() + "\n"
                text.append(slide_text)
            return "\n".join(text)
        except ImportError:
            return "python-pptx not installed."

    if action in ("summarize", "extract_text", "analyze"):
        text = _read_pptx_text()
        if action == "extract_text":
            out = _output_path(path, "text", ".txt")
            out.write_text(text, encoding="utf-8")
            return f"Text extracted. Saved: {out.name}"
        try:
            model    = _gemini_client()
            prompt   = f"{'Summarize' if action == 'summarize' else 'Analyze'} this presentation:\n{text[:30000]}"
            response = model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            return f"AI processing failed: {e}"

    return f"Unknown PPTX action: '{action}'. Try: summarize, extract_text, analyze"

def file_processor(parameters: dict, player=None, speak=None) -> str:
    file_path_str = parameters.get("file_path", "").strip()
    if not file_path_str:
        return "No file path provided."

    path = Path(file_path_str)
    if not path.exists():
        return f"File not found: {file_path_str}"
    if not path.is_file():
        return f"Path is not a file: {file_path_str}"

    file_type   = _detect_type(path)
    action      = (parameters.get("action") or "").lower().strip()
    instruction = parameters.get("instruction", "")
    params      = {**parameters, "instruction": instruction}

    if action in _LOCAL_DOCUMENT_ACTIONS:
        if (
            file_type not in _LOCAL_DOCUMENT_TYPES
            or path.suffix.lower() not in _LOCAL_DOCUMENT_EXTENSIONS
        ):
            return outcome.failed(
                "file_processor",
                "local preview and search support only DOCX, text, CSV, TSV, and XLSX files",
                action=action,
            )
        try:
            source_size = path.stat().st_size
        except OSError as exc:
            return outcome.failed(
                "file_processor",
                "the local document could not be inspected",
                action=action,
                error=type(exc).__name__,
            )
        if source_size > _LOCAL_DOCUMENT_MAX_BYTES:
            return outcome.failed(
                "file_processor",
                "the local document exceeds the configured processing limit",
                action=action,
                maximum_bytes=_LOCAL_DOCUMENT_MAX_BYTES,
            )
        if path.suffix.lower() in {".docx", ".xlsx"}:
            try:
                _validate_local_document_archive(path)
            except ValueError as exc:
                return outcome.failed(
                    "file_processor",
                    str(exc),
                    action=action,
                )
        elif path.suffix.lower() in {".csv", ".tsv"}:
            delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
            try:
                _validate_local_csv_width(path, delimiter)
            except (OSError, ValueError) as exc:
                return outcome.failed(
                    "file_processor",
                    str(exc) or "the delimited document could not be inspected",
                    action=action,
                    error=type(exc).__name__,
                )
        if action == "search":
            query = parameters.get("query")
            if (
                not isinstance(query, str)
                or not query.strip()
                or len(query) > _LOCAL_DOCUMENT_MAX_QUERY_LENGTH
            ):
                return outcome.failed(
                    "file_processor",
                    f"query must contain 1-{_LOCAL_DOCUMENT_MAX_QUERY_LENGTH} characters",
                    action=action,
                )

    if file_type == "code" and action == "run":
        return outcome.failed(
            "file_processor",
            "running uploaded code is disabled until a tested sandbox is available",
            action="run",
            file=path.name,
        )
    if file_type == "archive" and action == "extract":
        return outcome.failed(
            "file_processor",
            "archive extraction is disabled until safe path and resource limits are implemented",
            action="extract",
            file=path.name,
        )

    log_msg = f"[FileProcessor] {file_type.upper()} | {path.name} | action={action or 'auto'}"
    print(log_msg)
    if player:
        player.write_log(log_msg)

    if file_type == "unknown":
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")[:10000]
            model   = _gemini_client()
            prompt  = f"File: {path.name}\nContent preview:\n{content}\n\nTask: {action or instruction or 'Describe what this file contains and what can be done with it.'}"
            response = model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            return f"Unknown file type ({path.suffix}). Could not process: {e}"

    dispatch = {
        "image":   _process_image,
        "pdf":     _process_pdf,
        "docx":    lambda p, a, pm, s: _process_text_doc(p, "docx", a, pm, s),
        "text":    lambda p, a, pm, s: _process_text_doc(p, "text", a, pm, s),
        "csv":     lambda p, a, pm, s: _process_data(p, "csv",   a, pm, s),
        "excel":   lambda p, a, pm, s: _process_data(p, "excel", a, pm, s),
        "json":    _process_json,
        "xml":     lambda p, a, pm, s: _process_json(p, a, pm, s),  
        "code":    _process_code,
        "audio":   _process_audio,
        "video":   _process_video,
        "archive": _process_archive,
        "pptx":    _process_pptx,
    }

    handler = dispatch.get(file_type)
    if not handler:
        return f"Unsupported file type: {file_type}"

    try:
        output_path, conditional_note = _file_processor_output_target(
            path, file_type, action, params
        )
    except Exception as exc:
        return outcome.failed(
            "file_processor",
            "the output destination could not be determined safely; nothing was processed",
            action=action or "default",
            error=type(exc).__name__,
        )

    if output_path is not None:
        source_resolved = path.resolve()
        output_resolved = output_path.resolve()
        if output_resolved == source_resolved or output_resolved.parent != source_resolved.parent:
            return outcome.failed(
                "file_processor",
                "the requested output path is not a safe sibling of the source; nothing was processed",
                action=action or "default",
            )
        if output_resolved.exists():
            return outcome.failed(
                "file_processor",
                "the output file already exists; choose a different source or destination to avoid overwriting it",
                action=action or "default",
                output=output_resolved,
            )

        detail = (
            f"Operation: process {path.name} as {action or 'default action'}\n"
            f"Source file: {source_resolved}\n"
            f"Exact output path: {output_resolved}\n"
            "Existing files will not be overwritten."
        )
        if conditional_note:
            detail += f"\nThe output will be created only {conditional_note}."

        confirmation_action = action or _default_file_action(file_type)
        if file_type in ("text", "docx") and confirmation_action not in {
            "word_count", "extract_text", "summarize", "analyze", "reformat",
            "fix", "translate_hint", "to_bullet", "custom",
        }:
            confirmation_action = "custom"
        elif file_type == "image" and confirmation_action not in {
            "info", "describe", "ocr", "analyze", "read", "extract_text",
            "resize", "convert", "compress",
        }:
            confirmation_action = "describe"

        def process_after_approval() -> str:
            if output_resolved.exists():
                return outcome.failed(
                    "file_processor",
                    "the output appeared after the preview; nothing was processed",
                    action=confirmation_action,
                )
            try:
                processing_result = handler(path, action, params, speak)
            except Exception as exc:
                return outcome.failed(
                    "file_processor",
                    "processing failed after approval",
                    action=confirmation_action,
                    error=type(exc).__name__,
                )
            if _file_processor_failed(processing_result):
                return outcome.unverified(
                    "file_processor",
                    "the handler reported a processing failure; any partial output needs inspection",
                    action=confirmation_action,
                    output_created=output_resolved.is_file(),
                )
            if output_resolved.is_file():
                return outcome.done(
                    "file_processor",
                    action=confirmation_action,
                    output=output_resolved,
                    verified=True,
                )
            if conditional_note:
                return outcome.done(
                    "file_processor",
                    action=confirmation_action,
                    output_created=False,
                    verified=True,
                )
            return outcome.unverified(
                "file_processor",
                "processing returned without creating the expected output file",
                action=confirmation_action,
            )

        return action_policy.request_confirmation(
            "file_processor",
            confirmation_action,
            "Confirm file processing output",
            detail,
            run=process_after_approval,
            arguments={"action": confirmation_action},
        )

    try:
        result = handler(path, action, params, speak)
        if action in _LOCAL_DOCUMENT_ACTIONS:
            return json.dumps(
                {
                    "status": "done",
                    "action": action,
                    "content": outcome.untrusted(
                        f"file:{path.suffix.lstrip('.') or 'text'}",
                        result or "The document contains no text.",
                    ),
                    "verified": True,
                },
                ensure_ascii=False,
            )
        # A document's contents are not the user speaking. A PDF, a spreadsheet
        # or a text file can carry anything its author put there, including a
        # sentence addressed to whatever reads it — so what comes out of one
        # goes to the model marked as data. See core/outcome.untrusted().
        return outcome.untrusted(f"file:{path.suffix.lstrip('.') or 'text'}",
                                 result) if result else outcome.done(
            "file_processor", file=path.name, note="nothing to report",
            reason="the handler returned no result or completion evidence")
    except Exception as e:
        return outcome.failed(
            "file_processor",
            "processing raised an exception",
            error=type(e).__name__,
        )


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "file_processor",
    "description": "Processes files the user uploads. Code execution and archive extraction are disabled until safe isolation and extraction limits are implemented. Supports: images (describe/ocr/resize/compress/convert), PDFs (summarize/extract_text/to_word), Word docs and text files (summarize/fix/reformat/translate), CSV/Excel (analyze/stats/filter/sort/convert), JSON/XML (validate/format/analyze), code files (explain/review/fix/optimize/document/test), audio (transcribe/trim/convert/info), video (trim/extract_audio/extract_frame/compress/transcribe/info), archives (list), presentations (summarize/extract_text). Prefer asking the user when the requested action is ambiguous.",
    # Used in place of `description` only when a small model is on a tool
    # budget - Gemini still gets the full text. See providers/schema.py.
    "brief": (
        "Reads a local file and answers questions about it or summarises it. Put the path in 'path' and what is wanted in 'query'."
    ),
    "tier": "core",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "file_path": {
                "type": "STRING",
                "description": "Full path to the uploaded file. Leave empty to use the currently uploaded file."
            },
            "action": {
                "type": "STRING",
                "description": "What to do with the file. Examples by type:\nimage: describe | ocr | resize | compress | convert | info\npdf: summarize | extract_text | to_word | info\ndocx/txt: extract_preview | search | summarize | fix | reformat | translate_hint | word_count\ncsv/tsv/xlsx: extract_preview | search | analyze | stats | filter | sort | convert | info\njson: validate | format | analyze | to_csv\ncode: explain | review | fix | optimize | document | test (run disabled)\naudio: transcribe | trim | convert | info\nvideo: trim | extract_audio | extract_frame | compress | transcribe | info | convert\narchive: list (extract disabled)\npptx: summarize | extract_text | analyze"
            },
            "query": {
                "type": "STRING",
                "description": "Required search text for action=search on supported local document and spreadsheet formats (maximum 256 characters)."
            },
            "instruction": {
                "type": "STRING",
                "description": "Free-form instruction if action doesn't cover it. E.g. 'translate this to Turkish', 'find all email addresses'"
            },
            "format": {
                "type": "STRING",
                "description": "Target format for conversion. E.g. 'mp3', 'pdf', 'csv', 'png'"
            },
            "width": {
                "type": "INTEGER",
                "description": "Target width for image resize"
            },
            "height": {
                "type": "INTEGER",
                "description": "Target height for image resize"
            },
            "scale": {
                "type": "NUMBER",
                "description": "Scale factor for image resize (e.g. 0.5)"
            },
            "quality": {
                "type": "INTEGER",
                "description": "Quality 1-100 for image/video compress"
            },
            "start": {
                "type": "STRING",
                "description": "Start time for trim: seconds or HH:MM:SS"
            },
            "end": {
                "type": "STRING",
                "description": "End time for trim: seconds or HH:MM:SS"
            },
            "timestamp": {
                "type": "STRING",
                "description": "Timestamp for video frame extraction HH:MM:SS"
            },
            "column": {
                "type": "STRING",
                "description": "Column name for CSV filter/sort"
            },
            "value": {
                "type": "STRING",
                "description": "Filter value for CSV filter"
            },
            "condition": {
                "type": "STRING",
                "description": "Filter condition: equals|contains|gt|lt"
            },
            "ascending": {
                "type": "BOOLEAN",
                "description": "Sort order for CSV sort (default: true)"
            },
            "save": {
                "type": "BOOLEAN",
                "description": "Save result to file (default: true)"
            },
            "destination": {
                "type": "STRING",
                "description": "Output folder for archive extract"
            }
        },
        "required": []
    },
    "handler": file_processor,
}
