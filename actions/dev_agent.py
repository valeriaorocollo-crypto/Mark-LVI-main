import sys
import json
import re
import time
from pathlib import Path
from pathlib import PureWindowsPath


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR         = get_base_dir()
PROJECTS_DIR     = Path.home() / "Desktop" / "JarvisProjects"
# Model choice, timeout and fallback ladder all live in core/gemini.py.
from core import action_policy, gemini, outcome

MODEL_PLANNER    = gemini.SMART
MODEL_WRITER     = gemini.SMART

def _get_model(model_name: str = gemini.SMART):
    """Planning and writing whole files — the reasoning tier, and a long
    deadline because the answer is a source file rather than a sentence."""
    class _W:
        def generate_content(self, contents):
            resp = gemini.call(contents, tier=model_name, timeout_ms=60000)
            if resp is None:
                raise RuntimeError("every Gemini model on the ladder failed")
            return resp

    return _W()


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z]*\r?\n?", "", text)
    text = re.sub(r"\r?\n?```\s*$", "", text)
    return text.strip()


def _safe_project_name(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("project name must be text")
    slug = re.sub(r"[^\w-]", "_", value.strip(), flags=re.UNICODE)
    if not slug or slug in {".", ".."} or len(slug) > 100:
        raise ValueError("project name is empty or too long")
    if slug.upper() in {
        "CON", "PRN", "AUX", "NUL",
        *(f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)),
    }:
        raise ValueError("project name is a reserved Windows name")
    return slug


def _safe_project_file(project_dir: Path, relative_path: object) -> Path:
    if not isinstance(relative_path, str) or not relative_path or len(relative_path) > 240:
        raise ValueError("project file path must be text of at most 240 characters")
    normalized = relative_path.replace("\\", "/")
    windows_path = PureWindowsPath(relative_path)
    parts = normalized.split("/")
    if (
        normalized.startswith("/")
        or windows_path.is_absolute()
        or windows_path.drive
        or any(part in {"", ".", ".."} for part in parts)
        or any(":" in part or part.endswith((" ", ".")) for part in parts)
    ):
        raise ValueError("project file path must stay inside the project directory")
    reserved = {"CON", "PRN", "AUX", "NUL"} | {
        f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
    }
    if any(part.split(".", 1)[0].upper() in reserved for part in parts):
        raise ValueError("project file path contains a reserved Windows name")

    root = project_dir.resolve()
    target = root.joinpath(*parts)
    resolved = target.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("project file path escapes the project directory")
    cursor = root
    for part in parts[:-1]:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError("project file path traverses a symbolic link")
    if target.is_symlink():
        raise ValueError("project file path cannot replace a symbolic link")
    return target


def _validate_project_plan(plan: object) -> dict:
    if not isinstance(plan, dict):
        raise ValueError("planner response must be a JSON object")
    files = plan.get("files")
    if not isinstance(files, list) or not 1 <= len(files) <= 50:
        raise ValueError("project plan must contain 1 to 50 files")

    validated_files = []
    seen_paths = set()
    for entry in files:
        if not isinstance(entry, dict):
            raise ValueError("each planned file must be an object")
        path = entry.get("path")
        _safe_project_file(Path(PROJECTS_DIR) / "_validation", path)
        normalized_path = path.replace("\\", "/")
        path_key = normalized_path.casefold()
        if path_key in seen_paths:
            raise ValueError("project plan contains duplicate file paths")
        seen_paths.add(path_key)
        description = entry.get("description", "")
        imports = entry.get("imports", [])
        if not isinstance(description, str) or len(description) > 1000:
            raise ValueError("file descriptions must be text of at most 1000 characters")
        if not isinstance(imports, list) or any(
            not isinstance(item, str) or len(item) > 200 for item in imports
        ):
            raise ValueError("file imports must be a list of short text module names")
        validated_files.append({
            "path": normalized_path,
            "description": description,
            "imports": imports,
        })

    entry_point = plan.get("entry_point")
    _safe_project_file(Path(PROJECTS_DIR) / "_validation", entry_point)
    if entry_point.replace("\\", "/").casefold() not in seen_paths:
        raise ValueError("project entry point must be included in the planned files")

    dependencies = plan.get("dependencies", [])
    if not isinstance(dependencies, list) or len(dependencies) > 20 or any(
        not isinstance(dep, str) or not dep.strip() or len(dep) > 200
        for dep in dependencies
    ):
        raise ValueError("dependencies must be a list of at most 20 short package specifications")

    project_name = plan.get("project_name", "jarvis_project")
    return {
        "project_name": _safe_project_name(project_name),
        "entry_point": entry_point.replace("\\", "/"),
        "files": validated_files,
        "dependencies": dependencies,
    }


def _is_rate_limit(error: Exception) -> bool:
    msg = str(error).lower()
    return "429" in msg or "quota" in msg or "resource_exhausted" in msg


class RateLimitError(Exception):
    pass


def _plan_project(description: str, language: str) -> dict:
    model = _get_model(MODEL_PLANNER)

    prompt = f"""You are a senior software architect. Create a minimal, complete file plan for this project.

Language: {language}
Description: {description}

Return ONLY valid JSON — no markdown, no explanation:
{{
  "project_name": "snake_case_name",
  "entry_point": "main.py",
  "files": [
    {{
      "path": "main.py",
      "description": "Entry point — what it does and which modules it imports",
      "imports": ["utils.helpers", "core.engine"]
    }},
    {{
      "path": "utils/helpers.py",
      "description": "Helper utilities — what functions it exposes",
      "imports": []
    }}
  ],
  "run_command": "python main.py",
  "dependencies": ["requests"]
}}

Critical rules:
1. List files in DEPENDENCY ORDER — files with no imports come first, entry point comes last.
2. The "imports" field must list every other project module this file imports (dot-notation, e.g. "utils.helpers").
3. Keep it minimal — only files truly needed.
4. Entry point must be in the files list.
5. Use relative paths only (e.g. "utils/helpers.py", not absolute paths).
6. Standard library modules (os, sys, json, etc.) do NOT go in "dependencies".

JSON:"""

    try:
        response = model.generate_content(prompt)
        raw = _strip_fences(response.text)
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Planner returned invalid JSON: {e}\nRaw: {response.text[:300]}")
    except Exception as e:
        if _is_rate_limit(e):
            raise RateLimitError(str(e))
        raise

def _write_file(
    file_info: dict,
    project_description: str,
    all_files: list[dict],
    language: str,
    project_dir: Path,
    already_written: dict[str, str],
) -> str:
    model = _get_model(MODEL_WRITER)

    file_path = file_info["path"]
    file_desc = file_info.get("description", "")
    file_imports = file_info.get("imports", [])

    file_list = "\n".join(
        f"  [{i+1}] {f['path']}: {f.get('description', '')}"
        for i, f in enumerate(all_files)
    )

    dependency_context = ""
    for dep_dotted in file_imports:
        dep_path = dep_dotted.replace(".", "/") + ".py"
        if dep_path in already_written:
            code_snippet = already_written[dep_path][:2000]
            dependency_context += f"\n\n--- {dep_path} (you must import from this) ---\n{code_snippet}"

    lang_rules = ""
    if language.lower() == "python":
        lang_rules = """
Python-specific rules:
- Use type hints for all function signatures.
- Add docstrings for all public functions and classes.
- Use if __name__ == "__main__": guard in the entry point.
- For relative imports within the project, use: from utils.helpers import foo  (match the project structure exactly).
- Do NOT use implicit relative imports (from . import ...) unless it's a proper package with __init__.py.
- If this is a package subdirectory, create __init__.py files where needed."""
    elif language.lower() in ("javascript", "typescript", "js", "ts"):
        lang_rules = """
JS/TS-specific rules:
- Use ES modules (import/export), not CommonJS (require).
- Add JSDoc comments for all exported functions.
- Handle promise rejections with try/catch in async functions."""

    prompt = f"""You are a senior {language} developer writing production-quality code for a real project.

Project goal: {project_description}

Complete project file structure (in dependency order):
{file_list}

{f"Dependencies this file must import from other project files:{dependency_context}" if dependency_context else ""}

Your task: Write the complete, working code for: {file_path}
Purpose of this file: {file_desc}
{f"This file imports from: {', '.join(file_imports)}" if file_imports else "This file has no project-internal imports."}

{lang_rules}

General rules:
- Output ONLY raw code. Absolutely no explanation, no markdown, no triple backticks.
- Write COMPLETE, RUNNABLE code — no placeholders, no "# TODO", no "pass" stubs.
- Every import must either be from the standard library, listed dependencies, or the project files shown above.
- Match import paths EXACTLY to the file paths in the project structure (e.g. if file is "utils/helpers.py", import as "from utils.helpers import ...").
- Use proper error handling (try/except) where I/O or network calls are made.
- The code must work correctly when the project entry point is run from the project root directory.

Code for {file_path}:"""

    try:
        response = model.generate_content(prompt)
        code = _strip_fences(response.text)

        full_path = _safe_project_file(project_dir, file_path)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(code, encoding="utf-8")

        print(f"[DevAgent] ✅ Written: {file_path} ({len(code)} chars)")
        return code

    except Exception as e:
        if _is_rate_limit(e):
            raise RateLimitError(str(e))
        raise

def _build_project(
    description: str,
    language: str,
    project_name: str,
    plan: dict,
    speak=None,
    player=None,
) -> str:

    def log(msg: str):
        print(f"[DevAgent] {msg}")
        if player:
            player.write_log(f"[DevAgent] {msg}")

    proj_name = _safe_project_name(project_name or plan["project_name"])
    projects_root = Path(PROJECTS_DIR)
    if projects_root.is_symlink():
        return outcome.failed(
            "dev_agent", "the projects directory cannot be a symbolic link",
            wanted="build_project",
        )
    try:
        projects_root.mkdir(parents=True, exist_ok=True)
        projects_root = projects_root.resolve()
        project_dir = projects_root / proj_name
        project_dir.mkdir(exist_ok=False)
    except FileExistsError:
        return outcome.failed(
            "dev_agent", "a project with that name already exists; choose another name",
            wanted="build_project",
        )
    except OSError as exc:
        return outcome.failed(
            "dev_agent",
            f"could not create the project folder ({type(exc).__name__})",
            wanted="build_project",
        )

    files = plan["files"]
    dependencies = plan["dependencies"]

    log(f"Project: {proj_name} | Files: {len(files)}")

    def _dep_sort_key(fi: dict) -> int:
        return len(fi.get("imports", []))

    sorted_files = sorted(files, key=_dep_sort_key)

    file_codes: dict[str, str] = {}

    for file_info in sorted_files:
        file_path = file_info.get("path", "")
        if not file_path:
            continue

        log(f"Writing {file_path}...")
        for attempt in range(2):
            try:
                code = _write_file(
                    file_info=file_info,
                    project_description=description,
                    all_files=files,
                    language=language,
                    project_dir=project_dir,
                    already_written=file_codes,
                )
                file_codes[file_path] = code
                time.sleep(0.4)
                break
            except RateLimitError:
                if attempt == 0:
                    log("Rate limit — waiting 20s...")
                    time.sleep(20)
                else:
                    log(f"Rate limit retry failed for {file_path}, skipping.")
            except Exception as e:
                log(f"Failed to write {file_path} ({type(e).__name__})")
                break

    if not file_codes:
        try:
            project_dir.rmdir()
        except OSError:
            pass
        msg = outcome.failed(
            "dev_agent",
            "no project files could be generated",
            project=proj_name,
            wanted="generate_project",
        )
        if speak: speak(msg)
        return msg

    if len(file_codes) != len(files):
        return outcome.unverified(
            "dev_agent",
            "only some planned files were generated; review the project folder "
            "before continuing",
            project=proj_name,
            files_written=len(file_codes),
            files_planned=len(files),
        )

    dependency_note = (
        f"Dependencies were not installed: {', '.join(dependencies)}."
        if dependencies else "No dependencies were installed."
    )
    msg = outcome.done(
        "dev_agent",
        project=proj_name,
        files=len(file_codes),
        executed=False,
        dependencies_installed=False,
        verified=True,
    ) + (
        f" Source files are in {project_dir}. The generated code was not "
        f"executed. Review it before running it. {dependency_note}"
    )
    if speak: speak(msg)
    return msg


def dev_agent(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
    speak=None,
) -> str:
    p = parameters if isinstance(parameters, dict) else {}
    if parameters is not None and not isinstance(parameters, dict):
        return outcome.failed(
            "dev_agent", "parameters must be an object", wanted="build_project"
        )
    description = p.get("description", "")
    language = p.get("language", "python")
    project_name = p.get("project_name", "")

    if not isinstance(description, str) or not description.strip():
        return outcome.failed(
            "dev_agent", "a project description is required",
            wanted="build_project",
        )
    if len(description) > 10_000:
        return outcome.failed(
            "dev_agent", "project description exceeds 10000 characters",
            wanted="build_project",
        )
    if not isinstance(language, str) or not 1 <= len(language) <= 32:
        return outcome.failed(
            "dev_agent", "language must be text of at most 32 characters",
            wanted="build_project",
        )
    if not isinstance(project_name, str) or len(project_name) > 100:
        return outcome.failed(
            "dev_agent", "project name must be text of at most 100 characters",
            wanted="build_project",
        )
    description = description.strip()
    language = language.strip()
    project_name = project_name.strip()
    try:
        plan = _validate_project_plan(_plan_project(description, language))
        project_name = _safe_project_name(project_name or plan["project_name"])
        projects_root = Path(PROJECTS_DIR)
        if projects_root.is_symlink():
            raise ValueError("the projects directory cannot be a symbolic link")
        candidate = projects_root.resolve() / project_name
        if candidate.exists():
            return outcome.failed(
                "dev_agent",
                "a project with that name already exists; choose another name",
                wanted="build_project",
            )
    except RateLimitError:
        return outcome.failed(
            "dev_agent", "project planning reached the API rate limit",
            wanted="build_project",
        )
    except (ValueError, OSError) as exc:
        return outcome.failed(
            "dev_agent",
            f"project plan was rejected ({type(exc).__name__})",
            wanted="build_project",
        )
    except Exception as exc:
        return outcome.failed(
            "dev_agent",
            f"project planning failed ({type(exc).__name__})",
            wanted="build_project",
        )

    planned_paths = "\n".join(f"- {entry['path']}" for entry in plan["files"])
    planned_dependencies = (
        ", ".join(plan["dependencies"]) if plan["dependencies"] else "none"
    )
    detail = (
        "This will ask the model to generate and write source files under the "
        "JarvisProjects folder. The files will NOT be run, dependencies will "
        "NOT be installed, and VS Code will NOT be opened automatically.\n"
        f"Project name: {project_name}\n"
        f"Language: {language}\n"
        f"Files to create:\n{planned_paths}\n"
        f"Dependency suggestions (not installed): {planned_dependencies}\n"
        f"Requested behavior:\n{description}"
    )
    return action_policy.request_confirmation(
        "dev_agent",
        "build_project",
        "Confirm generated project files",
        detail,
        run=lambda: _build_project(
            description=description,
            language=language,
            project_name=project_name,
            plan=plan,
            speak=speak,
            player=player,
        ),
        arguments=p,
    )


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "dev_agent",
    "description": "Plans and writes generated project source files after HUD approval. Does not install dependencies, open VS Code, or execute generated code.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "description": {
                "type": "STRING",
                "description": "What the project should do"
            },
            "language": {
                "type": "STRING",
                "description": "Programming language (default: python)"
            },
            "project_name": {
                "type": "STRING",
                "description": "Optional project folder name"
            },
        },
        "required": [
            "description"
        ]
    },
    "handler": dev_agent,
}
