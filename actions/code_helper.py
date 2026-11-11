import re
import stat
import tempfile
import time
from pathlib import Path

DESKTOP            = Path.home() / "Desktop"
_DEBUG_SCREENSHOT_MAX_AGE_SECONDS = 24 * 60 * 60
# Model choice lives in core/gemini.py, and so does the timeout and the
# fallback ladder. Writing a model name here is what left this file hanging
# forever whenever that one alias was unwell.
from core import action_policy, gemini, outcome


def _get_api_key() -> str:
    from memory.config_manager import get_gemini_key

    key = get_gemini_key()
    if not key:
        raise RuntimeError("No Gemini API key is configured.")
    return key


def _get_gemini(tier: str = gemini.SMART):
    """Writing and fixing code is the reasoning tier; a 60s deadline because a
    whole file can come back."""
    class _W:
        def generate_content(self, contents):
            resp = gemini.call(contents, tier=tier, timeout_ms=60000)
            if resp is None:
                raise RuntimeError("every Gemini model on the ladder failed")
            return resp

    return _W()


def _clean_code(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return text.strip()


def _resolve_save_path(output_path: str, language: str) -> Path:
    ext_map = {
        "python": ".py", "py": ".py",
        "javascript": ".js", "js": ".js",
        "typescript": ".ts", "ts": ".ts",
        "html": ".html", "css": ".css",
        "java": ".java", "cpp": ".cpp", "c": ".c",
        "bash": ".sh", "shell": ".sh", "powershell": ".ps1",
        "sql": ".sql", "json": ".json", "rust": ".rs", "go": ".go",
    }
    if output_path:
        p = Path(output_path)
        return p if p.is_absolute() else DESKTOP / p
    ext = ext_map.get((language or "python").lower(), ".py")
    return DESKTOP / f"jarvis_code{ext}"


def _read_file(file_path: str) -> tuple[str, str]:
    if not file_path:
        return "", "No file path provided."
    p = Path(file_path)
    if not p.exists():
        return "", f"File not found: {file_path}"
    try:
        return p.read_text(encoding="utf-8"), ""
    except Exception as e:
        return "", f"Could not read file: {e}"


def _save_file(path: Path, content: str) -> str:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"Saved to: {path}"
    except Exception as e:
        return f"Could not save: {e}"


def _request_code_write(
    action: str,
    path: Path,
    content: str,
    expected_content: str | None,
) -> str:
    target = path.resolve()
    expected_exists = expected_content is not None
    detail = (
        f"Action: {action}\n"
        f"Exact destination: {target}\n"
        f"Existing file: {'will be updated' if expected_exists else 'must not exist'}\n"
        "Complete replacement code:\n"
        f"{content}"
    )

    def save_if_unchanged() -> str:
        try:
            if expected_exists:
                if not target.is_file() or target.read_text(encoding="utf-8") != expected_content:
                    return outcome.failed(
                        "code_helper",
                        "the destination changed after the preview; no code was written",
                        action=action,
                    )
            elif target.exists():
                return outcome.failed(
                    "code_helper",
                    "the destination now exists; no code was written",
                    action=action,
                )
        except (OSError, UnicodeError) as exc:
            return outcome.failed(
                "code_helper",
                "the destination could not be checked before writing",
                action=action,
                error=type(exc).__name__,
            )

        saved = _save_file(target, content)
        if saved.startswith("Could not save:"):
            return outcome.failed(
                "code_helper",
                "the code could not be written",
                action=action,
                error=saved.partition(":")[2].strip(),
            )
        try:
            verified = target.is_file() and target.read_text(encoding="utf-8") == content
        except (OSError, UnicodeError):
            verified = False
        if not verified:
            return outcome.unverified(
                "code_helper",
                "the write was attempted but the saved content could not be verified",
                action=action,
                path=target,
            )
        return outcome.done(
            "code_helper",
            action=action,
            path=target,
            verified=True,
        )

    return action_policy.request_confirmation(
        "code_helper",
        action,
        f"Confirm code {action}",
        detail,
        run=save_if_unchanged,
        arguments={"action": action},
    )


def _take_screenshot() -> Path | None:
    _cleanup_stale_debug_screenshots()
    screenshot_path: Path | None = None
    try:
        import pyautogui
        screenshot = pyautogui.screenshot()
        with tempfile.NamedTemporaryFile(
            prefix="mark_screen_debug_",
            suffix=".png",
            delete=False,
        ) as temp_file:
            screenshot_path = Path(temp_file.name)
        screenshot.save(str(screenshot_path))
        print("[Code] Screenshot captured.")
        return screenshot_path
    except Exception as e:
        if screenshot_path is not None:
            try:
                screenshot_path.unlink()
            except FileNotFoundError:
                pass
            except OSError as cleanup_error:
                print(
                    "[Code] Incomplete debug screenshot could not be deleted "
                    f"({type(cleanup_error).__name__}): {screenshot_path}"
                )
        print(f"[Code] Screenshot failed ({type(e).__name__}).")
        return None


def _cleanup_stale_debug_screenshots() -> None:
    temp_dir = Path(tempfile.gettempdir())
    cutoff = time.time() - _DEBUG_SCREENSHOT_MAX_AGE_SECONDS
    try:
        candidates = temp_dir.glob("mark_screen_debug_*.png")
        for candidate in candidates:
            try:
                if candidate.is_symlink():
                    continue
                metadata = candidate.stat()
                if stat.S_ISREG(metadata.st_mode) and metadata.st_mtime < cutoff:
                    candidate.unlink()
            except FileNotFoundError:
                continue
            except OSError as exc:
                print(
                    "[Code] Stale debug screenshot could not be cleaned "
                    f"({type(exc).__name__}): {candidate}"
                )
    except OSError as exc:
        print(
            "[Code] Stale debug screenshot cleanup could not scan the "
            f"temporary directory ({type(exc).__name__})."
        )


def _image_to_base64(path: Path) -> str:
    import base64
    return base64.b64encode(path.read_bytes()).decode("utf-8")


_VALID_INTENTS = {"write", "edit", "explain", "run", "build", "screen_debug", "optimize"}


def _detect_intent(description: str, file_path: str, code: str) -> str:
    """
    Language-independent intent detection — NO fixed keyword list.
    Whatever language the user speaks, the description is classified by
    Gemini. If the API is unreachable, it falls back to language-agnostic
    structural hints (does the file exist on disk, was code provided).
    """
    desc        = (description or "").strip()
    file_exists = bool(file_path) and Path(file_path).exists()

    if desc:
        try:
            ctx = []
            if file_path:
                ctx.append(f"a file path is provided (exists on disk: {file_exists})")
            if code:
                ctx.append("an inline code snippet is provided")
            prompt = (
                "Classify a coding assistant request into exactly ONE intent word.\n"
                "The request may be written in ANY language.\n\n"
                f"Request: {desc}\n"
                + (f"Context: {'; '.join(ctx)}\n" if ctx else "")
                + "\nIntents:\n"
                "  write        = create new code from scratch\n"
                "  edit         = modify an existing file\n"
                "  explain      = describe what given code/file does\n"
                "  run          = execute an existing file\n"
                "  build        = write code, run it, and iterate until it works\n"
                "  screen_debug = analyze an error currently visible on the user's screen\n"
                "  optimize     = refactor / clean up / speed up existing code\n\n"
                "Reply with ONLY the intent word, nothing else."
            )
            ans = _get_gemini().generate_content(prompt).text.strip().lower()
            ans = ans.strip("`'\". \n")
            if ans in _VALID_INTENTS:
                return ans
        except Exception as e:
            print(f"[Code] Intent classification failed ({e}) — structural fallback")

    # Structural fallback — not tied to any language
    if file_exists:
        return "edit" if desc else "explain"
    if code:
        return "explain"
    return "write"

def _write(description: str, language: str, output_path: str, player=None) -> tuple[str, Path]:
    lang  = language or "python"
    model = _get_gemini()

    prompt = f"""You are an expert {lang} developer.
Write clean, working, well-commented {lang} code for the description below.

Rules:
- Output ONLY the code. No explanation, no markdown, no backticks.
- Add helpful inline comments.
- Handle errors and edge cases properly.
- Use modern best practices.

Description: {description}

Code:"""

    response = model.generate_content(prompt)
    code     = _clean_code(response.text)
    path     = _resolve_save_path(output_path, lang)
    return code, path


def _write_action(description, language, output_path, player) -> str:
    if not description:
        return "Please describe what you want me to write, sir."
    if player:
        player.write_log("[Code] Writing code...")
    try:
        code, path = _write(description, language, output_path, player)
        if path.exists():
            return outcome.failed(
                "code_helper",
                "the destination already exists; choose a new path or use edit",
                action="write",
                path=path.resolve(),
            )
        return _request_code_write("write", path, code, None)
    except Exception as e:
        return f"Could not generate code: {e}"


def _edit_action(file_path, instruction, player) -> str:
    if not file_path:
        return "Please provide a file path to edit, sir."
    if not instruction:
        return "Please describe what change to make, sir."

    content, err = _read_file(file_path)
    if err:
        return err

    if player:
        player.write_log("[Code] Editing file...")

    model  = _get_gemini()
    prompt = f"""You are an expert code editor.
Apply the following change to the code below.
Return ONLY the complete updated code — no explanation, no markdown, no backticks.

Change: {instruction}

Original code:
{content}

Updated code:"""

    try:
        response = model.generate_content(prompt)
        edited   = _clean_code(response.text)
    except Exception as e:
        return f"Could not edit code: {e}"

    return _request_code_write("edit", Path(file_path), edited, content)


def _explain_action(file_path, code, player) -> str:
    if file_path and not code:
        code, err = _read_file(file_path)
        if err:
            return err
    if not code:
        return "Please provide code or a file path to explain, sir."

    if player:
        player.write_log("[Code] Analyzing code...")

    model  = _get_gemini()
    prompt = f"""Explain what this code does in simple, clear language.
Focus on: what it does, how it works, and any important details.
Be concise — 3 to 6 sentences maximum.

Code:
{code[:4000]}

Explanation:"""

    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"Could not explain code: {e}"


def _optimize_action(file_path, code, language, output_path, player) -> str:
    original_content = None
    if file_path:
        if Path(file_path).exists():
            original_content, err = _read_file(file_path)
            if err:
                return err
            if not code:
                code = original_content
        elif not code:
            return f"File not found: {file_path}"
    if not code:
        return "Please provide code or a file path to optimize, sir."

    if player:
        player.write_log("[Code] Optimizing code...")

    lang  = language or "python"
    model = _get_gemini()

    prompt = f"""You are an expert {lang} developer and code reviewer.
Optimize the following code for:
1. Performance — eliminate unnecessary operations, use efficient data structures
2. Readability — clear variable names, proper formatting, logical structure
3. Best practices — modern {lang} patterns, error handling, type hints if applicable
4. Remove dead code, redundant comments, and unnecessary complexity

Return ONLY the optimized code — no explanation, no markdown, no backticks.

Original code:
{code[:6000]}

Optimized code:"""

    try:
        response  = model.generate_content(prompt)
        optimized = _clean_code(response.text)
    except Exception as e:
        return f"Could not optimize code: {e}"

    # Kaydet
    if file_path:
        save_path = Path(file_path)
    else:
        save_path = _resolve_save_path(output_path, lang)

    if original_content is None and save_path.exists():
        return outcome.failed(
            "code_helper",
            "the destination already exists; choose a new path or provide the file to optimize",
            action="optimize",
            path=save_path.resolve(),
        )
    return _request_code_write("optimize", save_path, optimized, original_content)


def _screen_debug_action(description, file_path, player, speak=None) -> str:
    detail = (
        "Source: full active screen (not a selected window or region)\n"
        "Destination: Gemini for visual debugging\n"
        "A temporary screenshot is created only after approval and deleted "
        "after analysis. It is not retained by this operation.\n"
        "If a related file is provided, up to 4,000 characters may also be "
        "sent to Gemini.\n"
        f"Question: {description or 'Describe the visible error'}\n"
        f"Related file: {file_path or 'none'}"
    )

    def run() -> str:
        begin_activity = getattr(player, "begin_capture_activity", None)
        mark_transmitting = getattr(
            player, "mark_capture_transmitting", None
        )
        end_activity = getattr(player, "end_capture_activity", None)
        if not all(callable(fn) for fn in (
            begin_activity, mark_transmitting, end_activity
        )):
            return outcome.failed(
                "code_helper",
                "the screen-capture indicator is unavailable; no image was captured",
                action="screen_debug",
            )

        stopped = begin_activity(
            "Full-screen capture to Gemini for visual debugging."
        )
        if stopped is None:
            return outcome.failed(
                "code_helper",
                "screen capture was cancelled or its indicator could not be shown",
                action="screen_debug",
            )

        screenshot_path: Path | None = None
        cleanup_error: OSError | None = None
        indicator_cleanup_error: Exception | None = None
        result: str | None = None
        try:
            if stopped.is_set():
                result = outcome.failed(
                    "code_helper",
                    "screen capture was stopped before the image was read",
                    action="screen_debug",
                )
            else:
                print("[Code] Capturing screen for debug...")
                screenshot_path = _take_screenshot()
                if screenshot_path is None:
                    result = outcome.failed(
                        "code_helper",
                        "the screen screenshot could not be captured",
                        action="screen_debug",
                    )
                elif stopped.is_set():
                    result = outcome.failed(
                        "code_helper",
                        "screen capture was stopped before upload; no image was sent",
                        action="screen_debug",
                    )
                else:
                    from google.genai import types

                    file_content = ""
                    if file_path:
                        file_content, err = _read_file(file_path)
                        if err:
                            print("[Code] Related file could not be read.")

                    image_bytes = screenshot_path.read_bytes()
                    if (
                        not mark_transmitting(stopped)
                        or stopped.is_set()
                    ):
                        result = outcome.failed(
                            "code_helper",
                            "screen capture was stopped before upload; no image was sent",
                            action="screen_debug",
                        )
                    else:
                        user_question = (
                            description
                            or "What error or problem do you see on the screen? "
                            "How can it be fixed?"
                        )
                        context = ""
                        if file_content:
                            context = (
                                "\n\nAdditionally, here is the related file "
                                "content:\n```\n"
                                f"{file_content[:4000]}\n```"
                            )

                        analysis_prompt = f"""You are an expert programmer and debugger analyzing a screenshot.

User's question: {user_question}{context}

Please:
1. Identify any errors, exceptions, or problems visible on the screen
2. Explain what is causing the problem in simple terms
3. Provide a concrete fix or solution
4. If there's code visible, show the corrected version

Be specific and actionable. If you see an error message, quote it exactly."""

                        contents = [
                            types.Part.from_bytes(
                                data=image_bytes, mime_type="image/png"
                            ),
                            analysis_prompt,
                        ]
                        response = gemini.call(
                            contents, tier=gemini.SMART, timeout_ms=45_000
                        )
                        if response is None:
                            result = outcome.failed(
                                "code_helper",
                                "Gemini could not analyze the screenshot",
                                action="screen_debug",
                            )
                        else:
                            analysis = (response.text or "").strip()
                            print("[Code] Screen analysis complete.")
                            if file_path and file_content:
                                code_match = re.search(
                                    r"```[a-zA-Z]*\n(.*?)```",
                                    analysis,
                                    re.DOTALL,
                                )
                                if code_match:
                                    result = _request_code_write(
                                        "screen_debug",
                                        Path(file_path),
                                        code_match.group(1).strip(),
                                        file_content,
                                    )
                            if result is None:
                                result = analysis or outcome.unverified(
                                    "code_helper",
                                    "Gemini returned an empty screen analysis",
                                    action="screen_debug",
                                )
        except Exception as error:
            result = outcome.failed(
                "code_helper",
                f"screen analysis failed with {type(error).__name__}",
                action="screen_debug",
            )
        finally:
            if screenshot_path is not None:
                try:
                    screenshot_path.unlink()
                except FileNotFoundError:
                    pass
                except OSError as error:
                    cleanup_error = error
            try:
                end_activity(stopped)
            except Exception as error:
                indicator_cleanup_error = error
                print(
                    "[Code] Capture indicator cleanup failed "
                    f"({type(error).__name__})."
                )

        if cleanup_error is not None:
            result = outcome.unverified(
                "code_helper",
                "the temporary debug screenshot could not be deleted and "
                "remains on disk; remove it manually",
                action="screen_debug",
                screenshot_path=screenshot_path,
                cleanup_error=type(cleanup_error).__name__,
            )
        elif indicator_cleanup_error is not None:
            result = outcome.unverified(
                "code_helper",
                "the capture indicator could not be removed",
                action="screen_debug",
                error=type(indicator_cleanup_error).__name__,
            )
        if result is None:
            result = outcome.failed(
                "code_helper",
                "screen analysis did not complete",
                action="screen_debug",
            )
        if player is not None:
            show_content = getattr(player, "show_content", None)
            if callable(show_content) and result:
                show_content("SCREEN DEBUG", outcome.unwrap(result))
        return result

    return action_policy.run_or_confirm(
        "code_helper",
        "screen_debug",
        "Share a screen capture with Gemini for debugging?",
        detail,
        run,
        arguments={
            "action": "screen_debug",
            "description": description,
            "file_path": file_path,
        },
    )


def code_helper(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
    speak=None
) -> str:
    """
    Called from main.py.

    parameters:
        action      : write | edit | explain | run | build | screen_debug | optimize | auto
        description : What the code should do / what change to make / what problem to analyze
        language    : Programming language (default: python)
        output_path : Where to save — user specifies full path or filename
        file_path   : Path to existing file (edit / explain / run / build / optimize)
        code        : Raw code string (explain/optimize without a file)
        args        : not used; execution remains disabled until a sandbox exists
        timeout     : not used; execution remains disabled until a sandbox exists
    """
    p           = parameters or {}
    action      = p.get("action", "auto").lower().strip()
    description = p.get("description", "").strip()
    language    = p.get("language", "python").strip()
    output_path = p.get("output_path", "").strip()
    file_path   = p.get("file_path", "").strip()
    code        = p.get("code", "").strip()
    if action == "auto":
        action = _detect_intent(description, file_path, code)
        print(f"[Code] 🤖 Auto-detected: {action}")

    if action == "write":
        return _write_action(description, language, output_path, player)

    elif action == "edit":
        return _edit_action(
            file_path,
            description or p.get("instruction", ""),
            player
        )

    elif action == "explain":
        return _explain_action(file_path, code, player)

    elif action == "run":
        return outcome.failed(
            "code_helper",
            "running code is disabled until a tested sandbox is available",
            action="run",
        )

    elif action == "build":
        return outcome.failed(
            "code_helper",
            "build is disabled until generated code can be run in a tested sandbox",
            action="build",
        )

    elif action == "optimize":
        return _optimize_action(file_path, code, language, output_path, player)

    elif action == "screen_debug":
        return _screen_debug_action(description, file_path, player, speak)

    else:
        return (
            f"Unknown action: '{action}'. Use write, edit, explain, optimize, "
            "or screen_debug. Run/build remain disabled until sandboxing exists."
        )


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "code_helper",
    "description": "Generates and explains code. File changes require HUD approval; running/building code is disabled until a tested sandbox is available.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "write | edit | explain | optimize | screen_debug | run/build (disabled) | auto (default: auto)"
            },
            "description": {
                "type": "STRING",
                "description": "What the code should do or what change to make"
            },
            "language": {
                "type": "STRING",
                "description": "Programming language (default: python)"
            },
            "output_path": {
                "type": "STRING",
                "description": "Where to save the file"
            },
            "file_path": {
                "type": "STRING",
                "description": "Path to existing file for edit/explain/run/build"
            },
            "code": {
                "type": "STRING",
                "description": "Raw code string for explain"
            },
            "args": {
                "type": "STRING",
                "description": "CLI arguments for run/build"
            },
            "timeout": {
                "type": "INTEGER",
                "description": "Execution timeout in seconds (default: 30)"
            }
        },
        "required": [
            "action"
        ]
    },
    "handler": code_helper,
}
