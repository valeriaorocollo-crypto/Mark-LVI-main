#flight_finder.py
import json
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

from config import is_windows, is_mac, is_linux
from core import outcome

def _get_api_key() -> str:
    from memory.config_manager import get_gemini_key

    key = get_gemini_key()
    if not key:
        raise RuntimeError("No Gemini API key is configured.")
    return key

_MONTH_MAP: dict[str, int] = {

    "january": 1, "february": 2, "march": 3,     "april": 4,
    "may": 5,     "june": 6,     "july": 7,       "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

# English fast-path only — Gemini (below) normalizes date expressions in ANY
# language to YYYY-MM-DD, so no other language needs to be hardcoded here.
_RELATIVE_MAP_KEYS = {
    "today",
    "tomorrow",
}


def _parse_date(raw: str) -> str:

    raw   = raw.strip()
    lower = raw.lower()
    today = datetime.now()

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        try:
            return datetime.strptime(raw, "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("date is not a valid calendar date") from exc
    if re.match(r"^\d{4}-", raw):
        raise ValueError("date must use a valid YYYY-MM-DD value")
    for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass

    relative = {
        "today": today,
        "tomorrow": today + timedelta(days=1),
    }
    for key, val in relative.items():
        if key in lower:
            return val.strftime("%Y-%m-%d")

    try:
        from core import gemini
        result = gemini.text(
            f"Today is {today.strftime('%Y-%m-%d')}. "
            f"Convert this date expression to YYYY-MM-DD: '{raw}'. "
            f"Return ONLY the date string, nothing else.",
            tier=gemini.FAST,
        )
        if isinstance(result, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", result):
            try:
                return datetime.strptime(result, "%Y-%m-%d").strftime("%Y-%m-%d")
            except ValueError:
                pass
    except Exception as e:
        print(f"[FlightFinder] ⚠️ Gemini date parse failed: {e}")

    for month_name, month_num in _MONTH_MAP.items():
        if month_name in lower:
            day_match = re.search(r"\d{1,2}", raw)
            if day_match:
                day  = int(day_match.group())
                year = today.year if month_num >= today.month else today.year + 1
                try:
                    return datetime(year, month_num, day).strftime("%Y-%m-%d")
                except ValueError:
                    pass

    raise ValueError("could not understand the requested date")

_CABIN_CODE: dict[str, str] = {
    "economy":  "1",
    "premium":  "2",
    "business": "3",
    "first":    "4",
}


def _build_google_flights_url(
    origin:      str,
    destination: str,
    date:        str,
    return_date: str | None = None,
    passengers:  int        = 1,
    cabin:       str        = "economy",
) -> str:
    cabin_code = _CABIN_CODE.get(cabin.lower(), "1")
    base       = "https://www.google.com/travel/flights"

    # Keep user-provided values inside the fixed Google Flights query.
    if return_date:
        trip = (
            f"Flights from {origin} to {destination} on {date} "
            f"returning {return_date}"
        )
    else:
        trip = f"Flights from {origin} to {destination} on {date}"

    query = urlencode({
        'q': trip,
        'tfs': 'CBwQAhoeEgoyMDI1LTAzLTE1agcIARIDSVNUcgcIARIDTEhS',
        'curr': 'USD',
        'cabin': cabin_code,
        'adults': passengers,
    })
    return f"{base}?{query}"



def _search_flights_browser(
    origin:      str,
    destination: str,
    date:        str,
    return_date: str | None,
    passengers:  int,
    cabin:       str,
) -> tuple[str, str]:
    import time
    from actions.browser_control import browser_control

    url = _build_google_flights_url(
        origin, destination, date, return_date, passengers, cabin
    )

    print(f"[FlightFinder] 🌐 Opening: {url}")
    browser_control({"action": "go_to", "url": url})
    time.sleep(5)

    raw = browser_control({"action": "get_text"})
    return (raw or ""), url

def _parse_flights_with_gemini(
    raw_text:    str,
    origin:      str,
    destination: str,
    date:        str,
) -> list[dict]:
    from google import genai as _genai
    from google.genai import types

    prompt  = (
        f"Extract flight options from {origin} to {destination} on {date} "
        f"from this Google Flights page text:\n\n{raw_text[:12000]}\n\n"
        f"Return a JSON array of up to 5 flights:\n"
        f'[{{"airline":"...","departure":"HH:MM","arrival":"HH:MM",'
        f'"duration":"Xh Ym","stops":0,"price":"...","currency":"USD"}}]\n'
        f"If no flights found, return: []"
    )

    try:
        from core import gemini
        response = gemini.call(
            prompt,
            tier=gemini.SMART,
            timeout_ms=30_000,
            config=types.GenerateContentConfig(
                system_instruction=(
                    "You are a flight data extraction expert. "
                    "Extract flight information from raw webpage text. "
                    "Return ONLY valid JSON — no markdown, no explanation."
                )
            ),
        )
        text     = re.sub(r"```(?:json)?", "", response.text).strip().rstrip("`").strip()
        flights  = json.loads(text)
        return flights if isinstance(flights, list) else []
    except Exception as e:
        print(f"[FlightFinder] ⚠️ Gemini parse failed: {e}")
        return []

def _format_spoken(
    flights:     list[dict],
    origin:      str,
    destination: str,
    date:        str,
) -> str:
    if not flights:
        return (
            f"I couldn't find any flights from {origin} to {destination} "
            f"on {date}, sir. The page may not have loaded correctly."
        )

    lines = [f"Here are the top flights from {origin} to {destination} on {date}, sir."]

    for i, f in enumerate(flights[:5], 1):
        airline   = f.get("airline",   "Unknown airline")
        departure = f.get("departure", "--:--")
        arrival   = f.get("arrival",   "--:--")
        duration  = f.get("duration",  "")
        stops     = f.get("stops",     0)
        price     = f.get("price",     "")
        currency  = f.get("currency",  "")

        stop_str  = "non-stop" if stops == 0 else f"{stops} stop{'s' if stops > 1 else ''}"
        price_str = f"{price} {currency}".strip() if price else "price unavailable"
        dur_str   = f", {duration}" if duration else ""

        lines.append(
            f"Option {i}: {airline}, departing {departure}, "
            f"arriving {arrival}{dur_str}, {stop_str}, {price_str}."
        )

    # Cheapest — strip non-digits for comparison
    priced = [f for f in flights if f.get("price")]
    if priced:
        cheapest = min(
            priced,
            key=lambda x: int(re.sub(r"[^\d]", "", str(x["price"])) or "999999"),
        )
        lines.append(
            f"The cheapest option is {cheapest.get('airline')} "
            f"at {cheapest.get('price')} {cheapest.get('currency', '')}."
        )

    return " ".join(lines)


def _format_text_report(
    flights:     list[dict],
    origin:      str,
    destination: str,
    date:        str,
    return_date: str | None,
    page_url:    str,
) -> str:
    lines = [
        "JARVIS — Flight Search Results",
        "─" * 50,
        f"Route     : {origin} → {destination}",
        f"Date      : {date}",
    ]
    if return_date:
        lines.append(f"Return    : {return_date}")
    lines += [
        f"Searched  : {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Source    : {page_url}",
        "─" * 50,
        "",
    ]

    if not flights:
        lines.append("No flights found.")
    else:
        for i, f in enumerate(flights, 1):
            stops    = f.get("stops", 0)
            stop_str = "Non-stop" if stops == 0 else f"{stops} stop(s)"
            lines += [
                f"Flight {i}:",
                f"  Airline   : {f.get('airline',   'N/A')}",
                f"  Departure : {f.get('departure', 'N/A')}",
                f"  Arrival   : {f.get('arrival',   'N/A')}",
                f"  Duration  : {f.get('duration',  'N/A')}",
                f"  Stops     : {stop_str}",
                f"  Price     : {f.get('price', 'N/A')} {f.get('currency', '')}",
                "",
            ]

    return "\n".join(lines)

def _save_to_desktop(content: str, origin: str, destination: str) -> str:
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    origin_slug = re.sub(r"[^A-Za-z0-9_-]+", "_", origin).strip("_-")[:48]
    destination_slug = re.sub(
        r"[^A-Za-z0-9_-]+", "_", destination
    ).strip("_-")[:48]
    filename_root = (
        f"flights_{origin_slug or 'origin'}_"
        f"{destination_slug or 'destination'}_{ts}"
    )
    desktop  = Path.home() / "Desktop"
    desktop.mkdir(parents=True, exist_ok=True)
    desktop_root = desktop.resolve()
    filepath = desktop_root / f"{filename_root}.txt"
    for suffix in range(100):
        candidate = (
            filepath if suffix == 0
            else desktop_root / f"{filename_root}_{suffix}.txt"
        )
        if candidate.parent != desktop_root:
            raise ValueError("flight report path escaped the Desktop directory")
        try:
            with candidate.open("x", encoding="utf-8") as report:
                report.write(content)
            filepath = candidate
            break
        except FileExistsError:
            continue
    else:
        raise FileExistsError("could not choose a unique flight report name")
    print(f"[FlightFinder] 💾 Saved: {filepath}")

    try:
        if is_windows():
            subprocess.Popen(["notepad.exe", str(filepath)])
        elif is_mac():
            subprocess.Popen(["open", "-t", str(filepath)])
        else:
            subprocess.Popen(["xdg-open", str(filepath)])
    except Exception as e:
        print(f"[FlightFinder] ⚠️ Could not open text editor: {e}")

    return str(filepath)


def flight_finder(parameters: dict, player=None, speak=None) -> str:
    params = parameters or {}

    origin = params.get("origin", "")
    destination = params.get("destination", "")
    date_raw = params.get("date", "")
    return_raw = params.get("return_date", "")
    cabin = params.get("cabin", "economy")
    passengers = params.get("passengers", 1)
    save = params.get("save", False)

    text_inputs = {
        "origin": (origin, 100),
        "destination": (destination, 100),
        "date": (date_raw, 100),
        "return date": (return_raw, 100),
        "cabin": (cabin, 16),
    }
    for label, (value, limit) in text_inputs.items():
        if value is None and label == "return date":
            continue
        if not isinstance(value, str):
            return outcome.failed(
                "flight_finder", f"{label} must be text"
            )
        if len(value) > limit or any(ord(char) < 32 for char in value):
            return outcome.failed(
                "flight_finder",
                f"{label} exceeds its length limit or contains control characters",
            )

    origin = origin.strip()
    destination = destination.strip()
    date_raw = date_raw.strip()
    return_raw = (return_raw or "").strip()
    cabin = cabin.strip().lower()
    if isinstance(passengers, bool) or not isinstance(passengers, int):
        return outcome.failed("flight_finder", "passengers must be an integer")
    if not 1 <= passengers <= 9:
        return outcome.failed(
            "flight_finder", "passengers must be between 1 and 9"
        )
    if not isinstance(save, bool):
        return outcome.failed("flight_finder", "save must be a boolean")

    if not origin or not destination:
        return outcome.failed(
            "flight_finder", "both origin and destination are required"
        )
    if not date_raw:
        return outcome.failed("flight_finder", "a departure date is required")

    if cabin not in _CABIN_CODE:
        return outcome.failed("flight_finder", "cabin is not supported")

    try:
        date = _parse_date(date_raw)
        return_date = _parse_date(return_raw) if return_raw else None
    except ValueError as exc:
        return outcome.failed("flight_finder", str(exc))

    if player:
        player.write_log(f"[FlightFinder] {origin} → {destination} on {date}")

    if speak:
        speak(f"Searching flights from {origin} to {destination} on {date}, sir.")

    print(
        f"[FlightFinder] ▶️ {origin} → {destination} | {date}"
        f"{' → ' + return_date if return_date else ''}"
        f" | {cabin} | {passengers} pax"
    )

    try:
        raw_text, page_url = _search_flights_browser(
            origin, destination, date, return_date, passengers, cabin
        )

        if not raw_text:
            return outcome.unverified(
                "flight_finder",
                "flight results could not be retrieved from the page",
                origin=origin,
                destination=destination,
                date=date,
            )

        if speak:
            speak("Analysing the results now, sir.")

        flights = _parse_flights_with_gemini(raw_text, origin, destination, date)
        spoken  = _format_spoken(flights, origin, destination, date)

        if speak:
            speak(spoken)

        result = spoken

        if save and flights:
            report     = _format_text_report(flights, origin, destination, date, return_date, page_url)
            saved_path = _save_to_desktop(report, origin, destination)
            result    += f" Results saved to Desktop: {saved_path}"

        return result

    except Exception as e:
        print(f"[FlightFinder] ❌ {e}")
        return outcome.failed(
            "flight_finder",
            f"flight search failed ({type(e).__name__})",
            origin=origin,
            destination=destination,
            date=date,
        )


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "flight_finder",
    "description": "Searches Google Flights and speaks the best options.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "origin": {
                "type": "STRING",
                "description": "Departure city or airport code"
            },
            "destination": {
                "type": "STRING",
                "description": "Arrival city or airport code"
            },
            "date": {
                "type": "STRING",
                "description": "Departure date (any format)"
            },
            "return_date": {
                "type": "STRING",
                "description": "Return date for round trips"
            },
            "passengers": {
                "type": "INTEGER",
                "description": "Number of passengers (default: 1)"
            },
            "cabin": {
                "type": "STRING",
                "description": "economy | premium | business | first"
            },
            "save": {
                "type": "BOOLEAN",
                "description": "Save results to Notepad"
            }
        },
        "required": [
            "origin",
            "destination",
            "date"
        ]
    },
    "handler": flight_finder,
}
