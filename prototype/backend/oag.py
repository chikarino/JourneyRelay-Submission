"""JourneyRelay — live flight status from the OAG Flight Info API.

Used for one thing: how late a flight is running, so a shortened connection can
prompt the passenger and the transfer desk (REDESIGN.md §5.5). Schedules in the
seed were read from the same API; nothing else depends on it.

The demo must never wait on, or fail because of, an outside service: lookups
return what is cached and refresh in a background thread; no key, an error or
a slow reply all mean "unknown" (None).
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

API_URL = "https://api.oag.com/flight-instances/"
TTL_SECONDS = 300        # the free tier allows 1,000 requests per 30 days
TIMEOUT_SECONDS = 8

_cache: dict[tuple[str, str], tuple[float, int | None]] = {}
_refreshing: set[tuple[str, str]] = set()
_lock = threading.Lock()


def _minutes(variation: str | None) -> int | None:
    """'00:50:00' or '-00:05:00' -> minutes."""
    m = re.fullmatch(r"(-?)(\d+):(\d\d):(\d\d)", variation or "")
    if not m:
        return None
    total = int(m.group(2)) * 60 + int(m.group(3))
    return -total if m.group(1) else total


def parse_delay(payload: dict) -> int | None:
    """Minutes late from a Flight Info STATUS reply: the arrival estimate when
    there is one, else the departure estimate. Early or on time is 0."""
    try:
        status = payload["data"][0]["statusDetails"][0]
    except (KeyError, IndexError, TypeError):
        return None
    for side, key in (("arrival", "inGateVariation"), ("departure", "outGateVariation")):
        for clock in ("actualTime", "estimatedTime"):
            minutes = _minutes(((status.get(side) or {}).get(clock) or {}).get(key))
            if minutes is not None:
                return max(minutes, 0)
    return None


def _fetch(flight: str, date: str) -> int | None:
    key = os.getenv("OAG_FLIGHT_INFO_KEY", "").strip()
    m = re.fullmatch(r"([A-Z0-9]{2})(\d+)", flight)
    if not key or not m:
        return None
    query = urllib.parse.urlencode({
        "DepartureDateTime": date, "CarrierCode": m.group(1), "FlightNumber": m.group(2),
        "CodeType": "IATA", "Codeshare": "OPERATING", "Content": "STATUS", "version": "v2",
    })
    request = urllib.request.Request(f"{API_URL}?{query}", headers={"Subscription-Key": key})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as resp:
            return parse_delay(json.load(resp))
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None


def _refresh(key: tuple[str, str]) -> None:
    value = _fetch(*key)
    with _lock:
        _cache[key] = (time.monotonic() + TTL_SECONDS, value)
        _refreshing.discard(key)


def live_delay(flight: str, date: str) -> int | None:
    """Cached minutes late for a flight on a departure date; None when unknown.
    Never blocks: a stale or missing entry starts a background refresh."""
    key = (flight, date)
    with _lock:
        expires, value = _cache.get(key, (0.0, None))
        if time.monotonic() >= expires and key not in _refreshing:
            _refreshing.add(key)
            threading.Thread(target=_refresh, args=(key,), daemon=True).start()
    return value
