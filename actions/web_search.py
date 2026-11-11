#web_search.py
import threading
import time
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

# ── Gemini grounding quota circuit breaker ────────────────────────────────────
# The google_search grounding tool has its own small quota, separate from plain
# generation.  Once it is spent every call returns 429 — so retrying it at the
# top of every search only adds a dead round-trip before the DDG fallback runs.
# After a quota error, skip Gemini entirely for a cooldown period.
_QUOTA_COOLDOWN_SEC  = 900          # 15 minutes
_quota_blocked_until = 0.0
_quota_lock          = threading.Lock()


def _gemini_available() -> bool:
    with _quota_lock:
        return time.monotonic() >= _quota_blocked_until


def _note_gemini_error(exc: Exception) -> None:
    """Trip the breaker when the error is a quota / rate-limit rejection."""
    global _quota_blocked_until
    msg = str(exc)
    if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
        with _quota_lock:
            already = time.monotonic() < _quota_blocked_until
            _quota_blocked_until = time.monotonic() + _QUOTA_COOLDOWN_SEC
        if not already:
            print(
                "[WebSearch] Gemini grounding quota exhausted — skipping it for "
                f"{_QUOTA_COOLDOWN_SEC // 60} min and serving results from DDG."
            )


class _QuotaCooldown(RuntimeError):
    """Raised instead of calling Gemini while the quota breaker is open."""


def _log_gemini_failure(context: str, exc: Exception) -> None:
    """Log a Gemini failure — silently when it is just the expected cooldown."""
    if isinstance(exc, _QuotaCooldown):
        return          # announced once when the breaker tripped; not a warning
    print(f"[WebSearch] \u26a0\ufe0f {context} failed ({exc}) — using DDG instead")


def _get_api_key() -> str:
    from memory.config_manager import get_gemini_key

    key = get_gemini_key()
    if not key:
        raise RuntimeError("No Gemini API key is configured.")
    return key


def _gemini_search(query: str) -> str:
    if not _gemini_available():
        raise _QuotaCooldown("Gemini grounding is in quota cooldown")

    from core import gemini

    # Grounded search reads a live page, so it gets a longer deadline than the
    # default — but it still HAS one, and it still walks the fallback ladder.
    try:
        response = gemini.call(query, tier=gemini.SEARCH,
                               config={"tools": [{"google_search": {}}]},
                               timeout_ms=30_000)
        if response is None:
            raise RuntimeError("every Gemini model on the ladder failed")
    except Exception as e:
        _note_gemini_error(e)
        raise

    text = ""
    for part in response.candidates[0].content.parts:
        if hasattr(part, "text") and part.text:
            text += part.text

    text = text.strip()
    if not text:
        raise ValueError("Gemini returned an empty response.")
    return text


def _get_ddgs():
    """Return DDGS from the supported package, with an actionable error."""
    try:
        from ddgs import DDGS
    except ImportError as exc:
        raise RuntimeError(
            "Web search requires the 'ddgs' package. Install it with: "
            "python -m pip install ddgs"
        ) from exc
    return DDGS


def _ddg_search(
    query: str,
    max_results: int = 6,
    timelimit: str | None = None,
    region: str = "us-en",
) -> list[dict]:
    DDGS = _get_ddgs()
    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(
                query,
                max_results=max_results,
                timelimit=timelimit,
                region=region,
            ):
                results.append({
                    "title":   r.get("title",  ""),
                    "snippet": r.get("body",   ""),
                    "url":     r.get("href",   ""),
                    "date":    r.get("date",   ""),
                })
    except Exception as e:
        print(f"[WebSearch] ⚠️ DDG text() failed: {e}")
    return results


def _ddg_news(
    query: str,
    max_results: int = 8,
    timelimit: str = "d",
    region: str = "us-en",
) -> list[dict]:
    """DDG news search — returns actual articles, not website homepages."""
    DDGS = _get_ddgs()
    results = []
    try:
        with DDGS(timeout=3) as ddgs:
            for r in ddgs.news(
                query,
                max_results=max_results,
                timelimit=timelimit,
                region=region,
            ):
                results.append({
                    "title":   r.get("title",  ""),
                    "snippet": r.get("body",   ""),
                    "url":     r.get("url",    ""),
                    "source":  r.get("source", ""),
                    "date":    r.get("date",   ""),
                })
    except Exception as e:
        print(f"[WebSearch] ⚠️ DDG news() failed ({type(e).__name__}: {e})")
    return results


def _format_ddg(query: str, results: list[dict]) -> str:
    if not results:
        return f"No results found for: {query}"

    lines = [f"Search results for: {query}\n"]
    for i, r in enumerate(results, 1):
        if r.get("title"):   lines.append(f"{i}. {r['title']}")
        if r.get("snippet"): lines.append(f"   {r['snippet']}")
        if r.get("url"):     lines.append(f"   Source: {r['url']}")
        lines.append("")
    return "\n".join(lines).strip()


def _format_news(
    results: list[dict],
    language: str = "en",
    freshness: str = "d",
) -> str:
    if not results:
        return ""

    if language == "es":
        heading = "Últimas 24 horas" if freshness == "d" else "Últimos 7 días"
        source_label = "Fuente"
    else:
        heading = "Last 24 hours" if freshness == "d" else "Last 7 days"
        source_label = "Source"
    headlines = []
    for i, r in enumerate(results, 1):
        title = str(r.get("title") or "").strip()
        if not title:
            continue
        source = str(r.get("source") or "").strip()
        if not source:
            try:
                source = urlparse(str(r.get("url") or "")).hostname or ""
            except ValueError:
                source = ""
            source = source.removeprefix("www.")
        published = r.get("_published_at")
        date_text = (
            published.strftime("%d/%m/%Y %H:%M UTC")
            if isinstance(published, datetime)
            else ""
        )
        details = " · ".join(part for part in (source, date_text) if part)
        headline = f"{i}. {title}"
        if details:
            headline += f" — {source_label}: {details}"
        snippet = " ".join(str(r.get("snippet") or "").split())
        if snippet:
            headline += f" — {snippet[:180]}"
        headlines.append(headline)
    return f"{heading}: " + " || ".join(headlines) if headlines else ""


def _parse_news_date(value: object, now: datetime) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None

        folded = _fold_news_text(text)
        if folded in {"today", "hoy"}:
            parsed = now
        elif folded in {"yesterday", "ayer"}:
            parsed = now - timedelta(days=1)
        else:
            relative = re.fullmatch(
                r"(?:(\d+)\s+(seconds?|minutes?|hours?|days?)\s+ago|"
                r"hace\s+(\d+)\s+(segundos?|minutos?|horas?|dias?))",
                folded,
            )
            if relative:
                amount = int(relative.group(1) or relative.group(3))
                unit = relative.group(2) or relative.group(4)
                if unit.startswith(("second", "segundo")):
                    delta = timedelta(seconds=amount)
                elif unit.startswith(("minute", "minuto")):
                    delta = timedelta(minutes=amount)
                elif unit.startswith(("hour", "hora")):
                    delta = timedelta(hours=amount)
                else:
                    delta = timedelta(days=amount)
                parsed = now - delta
            else:
                try:
                    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
                except ValueError:
                    try:
                        parsed = parsedate_to_datetime(text)
                    except (TypeError, ValueError, OverflowError):
                        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _fold_news_text(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value.casefold())
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def _filter_recent_news(
    results: list[dict],
    max_age: timedelta,
    now: datetime | None = None,
) -> list[dict]:
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    reference = reference.astimezone(timezone.utc)

    recent: list[dict] = []
    seen: set[str] = set()
    for result in results:
        published = _parse_news_date(result.get("date"), reference)
        if published is None:
            continue
        age = reference - published
        if age < timedelta(0) or age > max_age:
            continue
        key = str(result.get("url") or result.get("title") or "").strip().casefold()
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        recent.append({**result, "_published_at": published})
    recent.sort(key=lambda result: result["_published_at"], reverse=True)
    return recent


def _mentions_location(topic: str, location: str) -> bool:
    folded_topic = _fold_news_text(topic)
    for component in re.split(r"[,/]", location):
        folded_component = _fold_news_text(component).strip()
        candidates = [folded_component]
        candidates.extend(
            word for word in folded_component.split() if len(word) > 2
        )
        for candidate in candidates:
            if candidate and re.search(
                rf"(?<!\w){re.escape(candidate)}(?!\w)", folded_topic
            ):
                return True
    return False


# ── Briefing helper ────────────────────────────────────────────────────────────

def _gemini_headlines(n: int = 5) -> tuple[list[str], str]:
    """
    Fetches current headlines via Gemini grounded search.
    Optimised for speed: minimal prompt + strict token cap.
    Returns (headline_list, raw_text_for_display).
    """
    from core import gemini

    response = gemini.call(
        f"Current world news: {n} headlines. Numbered list, titles only.",
        tier=gemini.SEARCH,
        config={"tools": [{"google_search": {}}]},
        timeout_ms=30_000,
    )
    if response is None:
        return [], ""

    raw = ""
    for part in response.candidates[0].content.parts:
        if hasattr(part, "text") and part.text:
            raw += part.text

    headlines = []
    for line in raw.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        # Only accept lines that begin with a number — skips preamble/closing sentences
        if not re.match(r'^[\d]+[.\)\-]', line):
            continue
        clean = re.sub(r'^[\d]+[.\)\-]\s*', '', line)
        clean = re.sub(r'^\*+\s*',          '', clean).strip()
        if clean and len(clean) > 10:
            headlines.append(clean)

    return headlines[:n], raw.strip()


# ── Modes ──────────────────────────────────────────────────────────────────────

def _search(query: str) -> str:
    """Default search — Gemini grounded, DDG fallback."""
    try:
        return _gemini_search(query)
    except Exception as e:
        _log_gemini_failure("Gemini search", e)
        results = _ddg_search(query)
        return _format_ddg(query, results)


def _news(
    query: str, location: str | None = None, language: str | None = None
) -> str:
    """
    Return only dated headlines within one day, or seven days as a fallback.

    An unstructured Gemini answer cannot be independently date-filtered here;
    when DDG does not return verifiable dated results, report that limitation
    instead of turning stale or unverified headlines into current news.
    """
    if location is None:
        from memory.config_manager import get_news_location
        location = get_news_location()
    if language is None:
        from memory.config_manager import get_language
        language = get_language()
    language = "es" if language == "es" else "en"
    location = " ".join(str(location or "").split())[:100] or "Peru"
    topic = " ".join(str(query or "").split())[:200]
    search_region = "pe-es" if language == "es" else "us-en"

    topic_folded = _fold_news_text(topic)
    location_mentioned = _mentions_location(topic, location)
    topic_words = set(topic_folded.split())
    international_requested = bool(
        topic_words.intersection({
            "internacional", "internacionales", "international",
            "mundo", "world", "global",
        })
    )
    local_requested = location_mentioned or any(
        word in topic_words
        for word in ("local", "locales", "nacional", "nacionales", "peru",
                     "tacna", "national")
    )

    if language == "es":
        local_query = topic or f"noticias nacionales y locales de {location}"
        if topic and not location_mentioned:
            local_query = f"{local_query} {location}"
        if not any(word in _fold_news_text(local_query).split()
                   for word in ("noticia", "noticias", "news")):
            local_query = f"noticias {local_query}"
        international_query = (
            f"noticias internacionales {topic}".strip()
            if topic else "principales noticias internacionales"
        )
        local_label = f"NOTICIAS LOCALES Y NACIONALES — {location.upper()}"
        international_label = "NOTICIAS INTERNACIONALES"
    else:
        local_query = topic or f"national and local news in {location}"
        if topic and not location_mentioned:
            local_query = f"{local_query} {location}"
        if not any(word in local_query.casefold().split()
                   for word in ("news", "headline", "headlines")):
            local_query = f"news {local_query}"
        international_query = (
            f"international news {topic}".strip()
            if topic else "top international news"
        )
        local_label = f"LOCAL AND NATIONAL NEWS — {location.upper()}"
        international_label = "INTERNATIONAL NEWS"

    queries: list[tuple[str, str]] = []
    if not international_requested or local_requested or not topic:
        queries.append((local_label, local_query))
    if international_requested or not topic:
        queries.append((international_label, international_query))

    def fetch_section(section_query: str) -> tuple[str, str] | None:
        for timelimit, max_age in (
            ("d", timedelta(days=1)),
            ("w", timedelta(days=7)),
        ):
            raw_results = _ddg_news(
                section_query,
                max_results=6,
                timelimit=timelimit,
                region=search_region,
            )
            recent = _filter_recent_news(raw_results or [], max_age)
            if recent:
                return (
                    _format_news(
                        recent,
                        language=language,
                        freshness=timelimit,
                    ),
                    timelimit,
                )
        return None

    sections: list[tuple[str, str]] = []
    results: dict[str, tuple[str, str] | None] = {}
    workers = [
        threading.Thread(
            target=lambda key=label, value=section_query: results.__setitem__(
                key, fetch_section(value)
            ),
            daemon=True,
            name=f"news-{label.lower().replace('/', '-')}",
        )
        for label, section_query in queries
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(11.0)
    for label, _ in queries:
        section = results.get(label)
        if section:
            sections.append((label, section[0]))

    if not sections:
        return (
            f"No pude verificar noticias recientes para {topic or location}. "
            "Los resultados disponibles no tienen una fecha de publicación "
            "comprobable o la fuente no respondió; no presentaré titulares "
            "antiguos como actuales."
            if language == "es"
            else f"I couldn't verify recent news for {topic or location}. "
                 "Available results had no verifiable publication date or "
                 "the source did not respond, so I won't present old "
                 "headlines as current."
        )
    return " || ".join(f"{label}: {text}" for label, text in sections)


def _research(query: str) -> str:
    """
    Deep dive — asks Gemini for a comprehensive answer with context.
    Falls back to a wider DDG fetch.
    """
    research_query = (
        f"Comprehensive, detailed explanation of: {query}. "
        "Include background context, key facts, current state, and important nuances."
    )
    try:
        return _gemini_search(research_query)
    except Exception as e:
        _log_gemini_failure("Gemini research", e)
        results = _ddg_search(query, max_results=10)
        return _format_ddg(query, results)


def _price(query: str) -> str:
    """Product price lookup — searches for current market prices."""
    price_query = f"current price of {query} — how much does it cost today"
    try:
        return _gemini_search(price_query)
    except Exception as e:
        _log_gemini_failure("Gemini price", e)
        results = _ddg_search(f"{query} price buy", max_results=6)
        return _format_ddg(query, results)


def _compare(items: list[str], aspect: str) -> str:
    query = (
        f"Compare {', '.join(items)} in terms of {aspect}. "
        "Give specific facts and data."
    )
    try:
        return _gemini_search(query)
    except Exception as e:
        _log_gemini_failure("Gemini compare", e)

    all_results: dict[str, list] = {}
    for item in items:
        try:
            all_results[item] = _ddg_search(f"{item} {aspect}", max_results=3)
        except Exception:
            all_results[item] = []

    lines = [f"Comparison — {aspect.upper()}", "─" * 40]
    for item in items:
        lines.append(f"\n▸ {item}")
        for r in all_results.get(item, [])[:2]:
            if r.get("snippet"):
                lines.append(f"  • {r['snippet']}")
            if r.get("url"):
                lines.append(f"    {r['url']}")
    return "\n".join(lines)


# ── Public entry point ─────────────────────────────────────────────────────────

from core import outcome


def web_search(
    parameters:     dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters or {}
    query  = str(params.get("query") or "").strip()
    mode   = params.get("mode",  "search").lower().strip()
    items  = params.get("items", [])
    aspect = params.get("aspect", "general").strip() or "general"

    if not query and not items and mode != "news":
        return "Please provide a search query."

    if items and mode not in ("compare",):
        mode = "compare"

    if player:
        print(f"[WebSearch] {mode}: {query or ', '.join(items)}")  # terminal

    print(f"[WebSearch] 🔍 mode={mode!r}  query={query!r}")

    try:
        if mode == "compare" and items:
            found = _compare(items, aspect)
        elif mode == "news":
            found = _news(query)
        elif mode == "research":
            found = _research(query)
        elif mode == "price":
            found = _price(query)
        else:
            found = _search(query)

    except Exception as e:
        print(f"[WebSearch] ❌ All backends failed: {e}")
        return outcome.failed("web_search", f"the search failed: {e}",
                              query=query or ", ".join(items))

    # ActionRegistry normalizes this free-form result and marks external search
    # content as untrusted once. Wrapping it here as well leaks nested markers
    # into the model result and the content panel.
    return found


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "web_search",
    "description": "Searches the web. Use for ANY question about current facts, events, prices, or topics — always prefer this over guessing. Modes: 'search' (default), 'news' (latest headlines on a topic), 'research' (deep comprehensive answer), 'price' (product cost lookup), 'compare' (side-by-side comparison of items).",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "query": {
                "type": "STRING",
                "description": "Search query or topic"
            },
            "mode": {
                "type": "STRING",
                "description": "search | news | research | price | compare"
            },
            "items": {
                "type": "ARRAY",
                "items": {
                    "type": "STRING"
                },
                "description": "Items to compare (compare mode)"
            },
            "aspect": {
                "type": "STRING",
                "description": "Comparison aspect: price | specs | reviews | features"
            }
        },
        "required": [
            "query"
        ]
    },
    "handler": web_search,
}
