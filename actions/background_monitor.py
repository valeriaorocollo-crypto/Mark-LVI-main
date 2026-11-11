"""
BackgroundMonitor — user-configured topic watching.
Checks DDG news once per day per topic; alerts JARVIS when a new headline appears.
No crypto, no finance, no uninvited tracking.
"""
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from core import action_policy, outcome

# ── Blocked categories (never monitor regardless of what user says) ────────────

_BLOCKED = {
    # Brand / asset names — spelled the same in every language
    "bitcoin", "ethereum", "dogecoin", "solana", "binance",
    "nft", "blockchain", "defi", "altcoin", "memecoin", "coin", "token",
    # spellings of the "crypto" root across different languages
    "crypto", "kripto", "cripto", "krypto", "крипто", "仮想通貨", "暗号資産",
    "cryptocurrency",
}

def _is_blocked(topic: str) -> bool:
    t = topic.lower()
    return any(word in t for word in _BLOCKED)


# ── Slug / hash helpers ────────────────────────────────────────────────────────

def _slug(topic: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", topic.lower().strip())[:40].strip("_")

def _title_hash(title: str) -> str:
    return hashlib.md5(title.encode("utf-8", errors="ignore")).hexdigest()[:12]


# ── Memory I/O ─────────────────────────────────────────────────────────────────

def _load() -> dict:
    from memory.memory_manager import load_memory
    data = load_memory().get("monitors", {})
    return data if isinstance(data, dict) else {}

def _save(monitors: dict) -> None:
    from memory.memory_manager import load_memory, MEMORY_PATH, _lock
    memory = load_memory()
    memory["monitors"] = monitors
    with _lock:
        MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        MEMORY_PATH.write_text(
            json.dumps(memory, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


# ── Public API ─────────────────────────────────────────────────────────────────

def add_monitor(topic: str) -> str:
    if not isinstance(topic, str) or not topic.strip() or len(topic.strip()) > 120:
        return outcome.failed(
            "manage_monitor",
            "topic must contain 1 to 120 characters",
            wanted="add",
        )
    topic = topic.strip()
    if _is_blocked(topic):
        return outcome.failed(
            "manage_monitor",
            "crypto and financial topics are not monitored",
            wanted="add",
        )
    monitors = _load()
    slug = _slug(topic)
    if not slug:
        return outcome.failed(
            "manage_monitor", "topic does not contain usable characters",
            wanted="add",
        )
    if slug in monitors:
        return f"Already monitoring: {monitors[slug]['topic']}"

    def _add() -> str:
        current = _load()
        if slug in current:
            return outcome.failed(
                "manage_monitor",
                "topic was added while confirmation was pending",
                wanted="add",
            )
        current[slug] = {
            "topic": topic,
            "added": datetime.now().strftime("%Y-%m-%d"),
            "last_check": "",
            "last_hash": "",
        }
        _save(current)
        if _load().get(slug, {}).get("topic") != topic:
            return outcome.unverified(
                "manage_monitor",
                "topic was saved but could not be verified after writing",
                wanted="add",
            )
        print("[Monitor] Added topic")
        return outcome.done(
            "manage_monitor", wanted="add", verified=True
        )

    return action_policy.request_confirmation(
        "manage_monitor",
        "add",
        "Confirm background monitoring",
        f"Add this topic to daily background news monitoring?\n\nTopic: {topic}",
        run=_add,
        arguments={"action": "add"},
    )


def remove_monitor(topic: str) -> str:
    if not isinstance(topic, str) or not topic.strip() or len(topic.strip()) > 120:
        return outcome.failed(
            "manage_monitor",
            "topic must contain 1 to 120 characters",
            wanted="remove",
        )
    topic = topic.strip().lower()
    monitors = _load()
    slug = _slug(topic)
    if slug in monitors:
        matches = [slug]
    else:
        matches = [
            key for key, value in monitors.items()
            if topic in value.get("topic", "").lower()
        ]
    if not matches:
        return f"Not found in monitored topics: {topic}"
    if len(matches) > 1:
        return outcome.ask(
            "manage_monitor",
            "topic matches more than one monitor; specify the exact topic",
            wanted="remove",
            matches=len(matches),
        )
    match = matches[0]
    label = monitors[match].get("topic", match)

    def _remove() -> str:
        current = _load()
        if match not in current:
            return outcome.failed(
                "manage_monitor",
                "topic was already removed while confirmation was pending",
                wanted="remove",
            )
        current.pop(match)
        _save(current)
        if match in _load():
            return outcome.unverified(
                "manage_monitor",
                "topic removal could not be verified after writing",
                wanted="remove",
            )
        return outcome.done(
            "manage_monitor", wanted="remove", verified=True
        )

    return action_policy.request_confirmation(
        "manage_monitor",
        "remove",
        "Confirm stop monitoring",
        f"Stop daily monitoring for this exact topic?\n\nTopic: {label}",
        run=_remove,
        arguments={"action": "remove"},
    )


def list_monitors() -> list[str]:
    return [v.get("topic", k) for k, v in _load().items()]


def check_all() -> list[str]:
    """
    Run all pending topic checks (once per day per topic).
    Returns a list of [MONITOR_ALERT] strings — empty if nothing new.
    """
    from actions.web_search import _ddg_news

    monitors = _load()
    if not monitors:
        return []

    today   = datetime.now().strftime("%Y-%m-%d")
    alerts  = []
    changed = False

    for slug, data in monitors.items():
        if data.get("last_check") == today:
            continue                     # already checked today

        topic = data.get("topic", slug)
        try:
            results = _ddg_news(topic, max_results=5)
            if not results:
                monitors[slug]["last_check"] = today
                changed = True
                continue

            top   = results[0]
            title = top.get("title", "").strip()
            if not title:
                continue

            h = _title_hash(title)
            monitors[slug]["last_check"] = today
            changed = True

            if h == data.get("last_hash"):
                continue                 # same headline as last check — no alert

            monitors[slug]["last_hash"] = h

            snippet = top.get("snippet", "")[:150]
            source  = top.get("source", "")
            parts   = [f"[MONITOR_ALERT] {topic}", f"Headline: {title}"]
            if snippet:
                parts.append(snippet)
            if source:
                parts.append(f"Source: {source}")
            alerts.append("\n".join(parts))
            print(f"[Monitor] 🔔 New headline for '{topic}': {title[:60]}")

        except Exception as e:
            print(f"[Monitor] ⚠️ Check failed for '{topic}': {e}")

    if changed:
        _save(monitors)

    return alerts
