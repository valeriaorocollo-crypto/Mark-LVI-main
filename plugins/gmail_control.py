"""Read-only Gmail search integration using the official Gmail API."""
from __future__ import annotations

import json
from typing import Any

from core import outcome
from memory import config_manager

PLUGIN = {
    "name": "gmail_control",
    "description": (
        "Search a connected Gmail account using the official Gmail API with "
        "read-only permission. Use for requests to find or inspect recent "
        "email, such as 'find the latest message from Steam'. This integration "
        "never sends, deletes, archives, or modifies email. Configure a Google "
        "OAuth Desktop client in plugin settings and authorize it with the "
        "read-only button before searching."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "enum": ["search"],
                "description": "Search Gmail messages; no write actions exist.",
            },
            "query": {
                "type": "STRING",
                "description": (
                    "A Gmail search query, for example "
                    "'from:steampowered.com' or 'subject:receipt'."
                ),
            },
            "max_results": {
                "type": "INTEGER",
                "description": "Maximum matching messages to return (1-10).",
            },
        },
        "required": ["action", "query"],
    },
}

_GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
_TOKEN_KEY = "oauth_credentials"
_MAX_QUERY_LENGTH = 500
_MAX_RESULTS = 10
_MAX_SNIPPET_LENGTH = 500
_MAX_HEADER_LENGTH = 300


def _plugin_config() -> dict:
    return config_manager.get_plugin_config(
        "gmail_control",
        secret_keys=["client_secret", _TOKEN_KEY],
    )


def _save_credentials(credentials_json: str) -> None:
    config_manager.save_plugin_config(
        "gmail_control",
        {_TOKEN_KEY: credentials_json},
        secret_keys=["client_secret", _TOKEN_KEY],
    )


def _new_authorization_flow(client_id: str, client_secret: str):
    from google_auth_oauthlib.flow import InstalledAppFlow

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": (
                "https://www.googleapis.com/oauth2/v1/certs"
            ),
            "redirect_uris": ["http://localhost"],
        }
    }
    return InstalledAppFlow.from_client_config(
        client_config,
        scopes=[_GMAIL_SCOPE],
    )


def _authorize_from_settings(values: dict) -> tuple[bool, str]:
    client_id = values.get("client_id", "")
    client_secret = values.get("client_secret", "")
    if not isinstance(client_id, str) or not client_id.strip():
        return False, "Enter a Google OAuth Desktop Client ID first."
    if not isinstance(client_secret, str) or not client_secret.strip():
        return False, "Enter a Google OAuth Desktop Client Secret first."

    try:
        flow = _new_authorization_flow(
            client_id.strip(),
            client_secret.strip(),
        )
        credentials = flow.run_local_server(
            port=0,
            open_browser=True,
            access_type="offline",
            prompt="consent",
        )
        granted_scopes = set(getattr(credentials, "scopes", None) or [])
        if _GMAIL_SCOPE not in granted_scopes:
            return False, "Google did not grant the required Gmail read-only scope."
        _save_credentials(credentials.to_json())
    except Exception as exc:
        return False, f"Gmail authorization failed ({type(exc).__name__})."
    return True, "Gmail was authorized with read-only access."


PLUGIN_SETTINGS = {
    "namespace": "gmail_control",
    "title": "GMAIL — READ ONLY",
    "fields": [
        {
            "key": "client_id",
            "type": "text",
            "label": "Google OAuth Desktop Client ID",
            "placeholder": "Client ID from your Google Cloud OAuth app",
        },
        {
            "key": "client_secret",
            "type": "password",
            "label": "Google OAuth Desktop Client Secret",
            "placeholder": "Stored in the Windows credential vault",
        },
    ],
    "action": {
        "label": "AUTHORIZE GMAIL READ ONLY",
        "run": _authorize_from_settings,
    },
}


def _load_authorized_credentials():
    values = _plugin_config()
    token_json = values.get(_TOKEN_KEY)
    if not isinstance(token_json, str) or not token_json.strip():
        return None, "Authorize Gmail from plugin settings before searching."
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        credentials = Credentials.from_authorized_user_info(
            json.loads(token_json),
            scopes=[_GMAIL_SCOPE],
        )
        granted_scopes = set(getattr(credentials, "scopes", None) or [])
        if _GMAIL_SCOPE not in granted_scopes:
            return None, "The saved Google authorization lacks Gmail read-only access."
        if not credentials.valid:
            if not credentials.expired or not credentials.refresh_token:
                return None, "Gmail authorization expired; reconnect it in plugin settings."
            credentials.refresh(Request())
            _save_credentials(credentials.to_json())
        return credentials, None
    except Exception as exc:
        return None, f"Could not load Gmail authorization ({type(exc).__name__})."


def _build_gmail_service(credentials):
    from googleapiclient.discovery import build

    return build(
        "gmail",
        "v1",
        credentials=credentials,
        cache_discovery=False,
    )


def _header(headers: Any, name: str) -> str:
    if not isinstance(headers, list):
        return ""
    for header in headers:
        if (
            isinstance(header, dict)
            and str(header.get("name", "")).casefold() == name.casefold()
        ):
            value = header.get("value", "")
            return value[:_MAX_HEADER_LENGTH] if isinstance(value, str) else ""
    return ""


def _search(parameters: dict) -> str:
    query = parameters.get("query")
    if (
        not isinstance(query, str)
        or not query.strip()
        or len(query) > _MAX_QUERY_LENGTH
    ):
        return outcome.failed(
            "gmail_control",
            "query must contain 1-500 characters",
            action="search",
        )
    max_results = parameters.get("max_results", 5)
    if (
        isinstance(max_results, bool)
        or not isinstance(max_results, int)
        or not 1 <= max_results <= _MAX_RESULTS
    ):
        return outcome.failed(
            "gmail_control",
            "max_results must be an integer from 1 to 10",
            action="search",
        )

    credentials, error = _load_authorized_credentials()
    if error:
        return outcome.failed(
            "gmail_control",
            error,
            action="search",
        )
    try:
        service = _build_gmail_service(credentials)
        response = (
            service.users()
            .messages()
            .list(
                userId="me",
                q=query.strip(),
                maxResults=max_results,
            )
            .execute()
        )
        message_refs = response.get("messages", [])
        if not isinstance(message_refs, list):
            raise ValueError("Gmail returned an invalid message list.")
        results = []
        for item in message_refs[:max_results]:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                continue
            message = (
                service.users()
                .messages()
                .get(
                    userId="me",
                    id=item["id"],
                    format="metadata",
                    metadataHeaders=["From", "Subject", "Date"],
                )
                .execute()
            )
            try:
                internal_date = int(message.get("internalDate", 0))
            except (TypeError, ValueError):
                internal_date = 0
            results.append({
                "id": item["id"],
                "internal_date": internal_date,
                "from": _header(message.get("payload", {}).get("headers"), "From"),
                "subject": _header(
                    message.get("payload", {}).get("headers"), "Subject"
                ),
                "date": _header(message.get("payload", {}).get("headers"), "Date"),
                "snippet": (
                    message.get("snippet", "")[:_MAX_SNIPPET_LENGTH]
                    if isinstance(message.get("snippet", ""), str)
                    else ""
                ),
            })
        results.sort(key=lambda result: result["internal_date"], reverse=True)
    except Exception as exc:
        return outcome.failed(
            "gmail_control",
            f"Gmail search failed ({type(exc).__name__}).",
            action="search",
        )

    return outcome.done(
        "gmail_control",
        action="search",
        query=query.strip(),
        count=len(results),
        messages=(
            outcome.untrusted(
                "gmail",
                json.dumps(results, ensure_ascii=False, separators=(",", ":")),
            )
            if results else "none"
        ),
        verified=True,
    )


def run(parameters: dict, player=None, session_memory=None) -> str:
    del player, session_memory
    if not isinstance(parameters, dict):
        return outcome.failed(
            "gmail_control",
            "parameters must be an object",
        )
    if parameters.get("action") != "search":
        return outcome.failed(
            "gmail_control",
            "only read-only search is supported",
            action=str(parameters.get("action", "unknown")),
        )
    return _search(parameters)
