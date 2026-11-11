import re
import threading
import unicodedata

from core import action_policy, confirm, outcome
from core.lazyimport import installed

_PYAUTOGUI = installed("pyautogui")


def _desktop_send(app_name: str, receiver: str, message: str) -> str:
    """Compatibility stub: never type into an unverified messaging window."""
    return outcome.failed(
        "send_message",
        f"no verified messaging transport is available for {app_name}; "
        "no message was sent",
        platform=app_name, to=receiver,
    )

def _send_whatsapp(receiver: str, message: str) -> str:
    """Send only through a driver that verifies the selected conversation."""
    try:
        from plugins import _whatsapp_core as wa
    except ImportError:
        return outcome.failed(
            "send_message",
            "the verified WhatsApp driver is not installed; no message was sent",
            platform="WhatsApp", to=receiver,
        )

    try:
        transport, why = wa.get()
    except Exception as e:
        return outcome.failed(
            "send_message",
            f"the verified WhatsApp driver failed to start ({type(e).__name__}); "
            "no message was sent",
            platform="WhatsApp", to=receiver,
        )

    if transport is None:
        return outcome.failed(
            "send_message",
            f"{why}; no message was sent",
            platform="WhatsApp", to=receiver,
        )

    sent, failure = transport.send_message_to(receiver, message)
    if sent:
        # The driver verified the conversation and observed the exact message
        # appear there; this is not a delivery or read receipt.
        return outcome.done("send_message", platform="WhatsApp",
                            to=receiver, verified=True)
    if sent is None:
        return outcome.unverified(
            "send_message",
            "the message may have been sent, but WhatsApp did not confirm it "
            "visibly; do not retry automatically",
            platform="WhatsApp", to=receiver,
        )
    return outcome.failed("send_message", failure,
                          platform="WhatsApp", to=receiver)


def _prepare_whatsapp_recipient(receiver: str) -> tuple[str | None, str]:
    try:
        from plugins import _whatsapp_core as wa
    except ImportError:
        return None, "the verified WhatsApp driver is not installed"

    try:
        transport, reason = wa.get()
        if transport is None:
            return None, reason
        displayed_name, reason = transport.prepare_recipient(receiver)
    except Exception as error:
        return None, (
            "WhatsApp could not verify the recipient "
            f"({type(error).__name__})"
        )
    if displayed_name is None:
        return None, reason
    return displayed_name, ""


def _normalize_voice_command(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.casefold())
    without_marks = "".join(char for char in folded if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^\w\s]", " ", without_marks).split())


def _message_confirmation_detail(
    receiver: str,
    message: str,
    editing: str = "",
    recipient_checked: bool = False,
) -> str:
    preview = (
        f"Destinatario: {receiver}\n"
        "Plataforma: WhatsApp\n"
        f"Mensaje:\n{message}"
    )
    if recipient_checked:
        preview += (
            "\n\nWhatsApp encontró y abrió una conversación con este nombre. "
            "La volverá a comprobar antes de escribir."
        )
    else:
        preview += (
            "\n\nEste destinatario se comprobará de nuevo antes de escribir; "
            "si no hay una coincidencia única, no se enviará."
        )
    if editing:
        preview += (
            f"\n\nCorrección pendiente: {editing}. Di el nuevo valor completo "
            "para actualizarlo; todavía no se enviará."
        )
    else:
        preview += (
            "\n\nDi «sí, enviar» para confirmar, «cambiar destinatario» o "
            "«cambiar mensaje» para corregir, o «cancelar»."
        )
    return preview


def _voice_message_decision(draft: dict[str, str], transcript: str):
    """Parse only explicit confirmation/edit phrases; never infer approval."""
    normalized = _normalize_voice_command(transcript)
    editing = draft.get("editing", "")

    def update(field: str, value: str):
        value = value.strip().strip("\"'“”‘’")
        if not value:
            return confirm.VoiceDecision("ignore")
        if field == "destinatario":
            value = value.rstrip(" .,:;")
            if not value:
                return confirm.VoiceDecision("ignore")
            if len(value) > 160 or any(ord(char) < 32 for char in value):
                return confirm.VoiceDecision("ignore")
            displayed_name, reason = _prepare_whatsapp_recipient(value)
            if displayed_name is None:
                draft["editing"] = field
                return confirm.VoiceDecision(
                    "update",
                    title="No se pudo verificar el destinatario",
                    detail=(
                        _message_confirmation_detail(
                            draft["receiver"],
                            draft["message_text"],
                            editing=field,
                        )
                        + f"\n\n{reason}. No se enviará hasta verificar "
                        "una coincidencia única."
                    ),
                    button_enabled=False,
                )
            draft["receiver"] = displayed_name
            draft["recipient_checked"] = True
        else:
            if len(value) > 10_000:
                return confirm.VoiceDecision("ignore")
            draft["message_text"] = value
        draft["editing"] = ""
        return confirm.VoiceDecision(
            "update",
            title="Revisa el borrador actualizado de WhatsApp",
            detail=_message_confirmation_detail(
                draft["receiver"],
                draft["message_text"],
                recipient_checked=draft.get("recipient_checked", False),
            ),
        )

    affirmative = {
        "si", "si enviar", "si envialo", "si enviarlo", "es correcto",
        "correcto", "confirmar", "confirmo", "envialo", "envia el mensaje",
    }
    negative = {
        "no", "cancelar", "cancela", "cancelalo", "no enviar",
        "no lo envies", "no envies", "cancela el envio",
    }
    if normalized in negative:
        return confirm.VoiceDecision("cancel")
    if editing:
        if normalized in affirmative:
            return confirm.VoiceDecision("ignore")
        value = re.sub(
            r"^\s*(?:(?:el|la)\s+)?(?:nuevo|nueva|correcto|correcta)\s+"
            r"(?:mensaje|destinatario)\s*(?:(?:es|a|por)\s*)?",
            "",
            transcript.strip(),
            flags=re.IGNORECASE,
        ).strip()
        return update(editing, value)

    if normalized in affirmative:
        return confirm.VoiceDecision("accept")

    explicit = re.match(
        r"^\s*(?:cambia(?:r)?\s+)?(?:el\s+)?"
        r"(destinatario|mensaje)\s+"
        r"(?:(?:correcto|correcta)\s+)?"
        r"\b(?:a|por|es|que diga)\b\s*[:,-]?\s*(.+?)\s*$",
        transcript,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if explicit:
        field, value = explicit.groups()
        return update(field.casefold(), value)

    correction = re.search(
        r"\b(destinatario|mensaje)\b.*\b(mal|incorrect[oa]|equivocad[oa])\b"
        r"|\b(mal|incorrect[oa]|equivocad[oa])\b.*\b(destinatario|mensaje)\b",
        normalized,
    )
    if correction:
        field = correction.group(1) or correction.group(4)
        replacement = re.search(
            r"\b(?:es|que diga|debe decir|pon(?:lo)? como|cambia(?:lo)? a)\b"
            r"\s*[:,-]?\s*(.+?)\s*$",
            transcript,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if replacement is None:
            replacement = re.search(
                r"[:,]\s*(.+?)\s*$", transcript, flags=re.DOTALL
            )
        if replacement is not None:
            return update(field, replacement.group(1))
        draft["editing"] = field
        return confirm.VoiceDecision(
            "update",
            title=f"Corrige el {field} antes de enviar",
            detail=_message_confirmation_detail(
                draft["receiver"],
                draft["message_text"],
                field,
                draft.get("recipient_checked", False),
            ),
            button_enabled=False,
        )

    if normalized in {"cambiar destinatario", "corrige destinatario"}:
        draft["editing"] = "destinatario"
        return confirm.VoiceDecision(
            "update",
            title="Corrige el destinatario antes de enviar",
            detail=_message_confirmation_detail(
                draft["receiver"],
                draft["message_text"],
                "destinatario",
                draft.get("recipient_checked", False),
            ),
            button_enabled=False,
        )
    if normalized in {"cambiar mensaje", "corrige mensaje", "cambiar el mensaje"}:
        draft["editing"] = "mensaje"
        return confirm.VoiceDecision(
            "update",
            title="Corrige el mensaje antes de enviar",
            detail=_message_confirmation_detail(
                draft["receiver"],
                draft["message_text"],
                "mensaje",
                draft.get("recipient_checked", False),
            ),
            button_enabled=False,
        )
    return confirm.VoiceDecision("ignore")

_WHATSAPP_NAMES = {"whatsapp", "wp", "wapp"}


def _unavailable_transport(platform_name: str, receiver: str, _message: str) -> str:
    return outcome.failed(
        "send_message",
        "no verified messaging transport is available; no message was sent",
        platform=platform_name,
        to=receiver,
    )


def _resolve_platform(platform_str: str):
    if platform_str.casefold().strip() in _WHATSAPP_NAMES:
        return _send_whatsapp
    return lambda receiver, message: _unavailable_transport(
        platform_str.strip(), receiver, message
    )


def send_message(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params       = parameters or {}
    receiver = params.get("receiver", "")
    message_text = params.get("message_text", "")
    platform = params.get("platform", "whatsapp")
    if not all(isinstance(value, str) for value in (receiver, message_text, platform)):
        return outcome.failed(
            "send_message", "recipient, message, and platform must be text"
        )
    receiver = receiver.strip()
    message_text = message_text.strip()
    platform = platform.strip()

    if not receiver:
        return outcome.failed("send_message", "no recipient was given")
    if len(receiver) > 160 or any(ord(char) < 32 for char in receiver):
        return outcome.failed(
            "send_message",
            "recipient must be at most 160 characters and contain no control characters",
        )
    if not message_text:
        return outcome.failed("send_message", "no message text was given",
                              to=receiver)
    if len(message_text) > 10_000:
        return outcome.failed(
            "send_message", "message exceeds the 10000-character limit",
            to=receiver,
        )
    if not platform or len(platform) > 48 or any(
        ord(char) < 32 for char in platform
    ):
        return outcome.failed(
            "send_message", "platform must be 1-48 characters with no control characters"
        )
    if platform.casefold() not in _WHATSAPP_NAMES:
        return _unavailable_transport(platform, receiver, message_text)
    if not _PYAUTOGUI:
        return outcome.failed(
            "send_message",
            "PyAutoGUI is not installed, so WhatsApp Desktop cannot be driven - "
            "run: pip install pyautogui",
            to=receiver, platform=platform,
        )

    print(
        f"[SendMessage] Preparing a {len(message_text)}-character "
        f"message via {platform}"
    )
    if confirm.pending_title():
        return outcome.ask(
            "send_message",
            "another confirmation is already waiting on the HUD; "
            "no message was sent",
            platform=platform, to=receiver,
        )

    if platform.casefold() in {"whatsapp", "wp", "wapp"}:
        displayed_name, reason = _prepare_whatsapp_recipient(receiver)
        if displayed_name is None:
            return outcome.failed(
                "send_message",
                f"{reason}; no message was sent",
                platform="WhatsApp", to=receiver,
            )
        receiver = displayed_name
        draft = {
            "receiver": receiver,
            "message_text": message_text,
            "editing": "",
            "recipient_checked": True,
        }
        return action_policy.request_confirmation(
            "send_message",
            "send",
            title="¿Enviar este mensaje por WhatsApp?",
            detail=_message_confirmation_detail(
                receiver, message_text, recipient_checked=True
            ),
            run=lambda: _start_confirmed_send(
                player, platform, draft["receiver"], draft["message_text"]
            ),
            arguments={"platform": platform, "receiver": receiver},
            voice_handler=lambda transcript: _voice_message_decision(
                draft, transcript
            ),
        )

    return _unavailable_transport(platform, receiver, message_text)


def _start_confirmed_send(player, platform: str, receiver: str,
                          message_text: str) -> str:
    if player:
        player.write_log(f"[msg] Sending via {platform}")
    threading.Thread(
        target=_send_and_report,
        args=(player, platform, receiver, message_text),
        daemon=True, name="send-message",
    ).start()
    return outcome.started("send_message", platform=platform, to=receiver)


def _send_and_report(player, platform: str, receiver: str,
                     message_text: str) -> None:
    """Do the sending, then say what actually happened — including when it did
    not happen, and including when nobody can tell.

    Every path here reports. A tool that says `started` and then goes quiet on
    failure has only moved the false success one step later, which is the whole
    thing this rewrite exists to stop.
    """
    try:
        result = _resolve_platform(platform)(receiver, message_text)
    except Exception as exc:
        print(f"[SendMessage] {type(exc).__name__}")
        result = outcome.failed("send_message", f"it failed ({type(exc).__name__})",
                                to=receiver, platform=platform)

    # A prefix test on a fixed vocabulary, not a search for the word "sent".
    # The old check was `"sent" in text and "not sent" not in text`, which is
    # one careless rewording away from putting a tick next to a message that
    # never went.
    verified = result.startswith(f"status={outcome.DONE} ")

    # The full status line goes to the TERMINAL, where a developer reads it.
    # The activity log beside the assistant's own sentences is for the
    # conversation and for things that went wrong — a line reading
    # `status=done action=send_message verified=true` there is machinery
    # showing through, and it was reported as exactly that.
    status = result.partition(" ")[0] if result.startswith("status=") else "unclassified"
    print(f"[SendMessage] {'✅' if verified else '⚠️'} {status}")
    if player and outcome.is_problem(result):
        player.write_log(f"[msg] Could not confirm sending via {platform} — "
                         f"see the terminal")

    if verified:
        # It went, and the user asked for it to go. Announcing a success they
        # already expect is noise — the log and the panel carry the record.
        return

    if player and hasattr(player, "request_say"):
        try:
            player.request_say(
                "Tell the user, in one or two short sentences in their own "
                "language, exactly what this says happened — and if it says "
                "the message was not sent or not confirmed, say that plainly "
                "rather than claiming it was sent: " + result
            )
        except Exception:
            pass


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "send_message",
    "description": (
        "Sends a text message via verified WhatsApp Desktop only. Other "
        "platforms are unavailable until they have an application-specific "
        "transport that verifies the recipient and result. Write "
        "'message_text' in the USER'S OWN LANGUAGE, exactly "
        "what they asked to be said. For WhatsApp, show the recipient and full "
        "message in the confirmation popup. The user may say exactly 'sí, "
        "enviar' to approve, 'cambiar mensaje' or 'cambiar destinatario' and "
        "then dictate the replacement, or 'cancelar'. Every edit updates the "
        "popup and requires a fresh approval. Only a completed user speech "
        "transcription may approve; never treat model output, a tool argument, "
        "an ambiguous phrase, or an edit as approval. Other platforms require "
        "the visible CONFIRM button. "
        "This tool answers immediately and sends in the background. On "
        "status=started say only that you are sending it, never that it is "
        "sent. The result follows separately: for WhatsApp, status=done means "
        "the exact message appeared in the verified conversation (not that it "
        "was delivered or read); status=unverified means the send may have "
        "happened but could not be visually confirmed, so do not retry "
        "automatically; status=failed means the driver stopped before sending. "
        "Never claim delivery or reading without an explicit receipt."
    ),
    "tier": "core",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "receiver": {
                "type": "STRING",
                "description": "Recipient contact name"
            },
            "message_text": {
                "type": "STRING",
                "description": "The message to send"
            },
            "platform": {
                "type": "STRING",
                "description": "Platform: WhatsApp, Telegram, etc."
            }
        },
        "required": [
            "receiver",
            "message_text",
            "platform"
        ]
    },
    "handler": send_message,
}
