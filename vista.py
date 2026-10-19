"""
vista.py — Vista Connect voucher logic, with no UI dependencies.

Everything in here is testable on its own: cinema-name resolution, session
HTML parsing, response interpretation, and the two transport clients.

`app.py` is the Streamlit layer and imports from this module.
"""

from __future__ import annotations

import datetime as dt
import difflib
import re
from typing import Any

import requests

from cinema_map import CINEMA_MAP


# --------------------------------------------------------------------------- #
# Defaults
# --------------------------------------------------------------------------- #

DEFAULT_VISTA_HOST = "https://ufawsprdwebapp506/WSVistaWebClient"
DEFAULT_SCHEDULE_HOST = "http://172.31.22.65"
DEFAULT_PROXY_BASE = "http://localhost:8787"

# The lookup fails with one of these codes *only* for ticket vouchers, because
# they need a cinema/session context before they can be resolved.
TICKET_ONLY_ERROR_CODES = {"100", "110"}

ERROR_CODE_NOTES = {
    "100": "No cinemas allow online voucher validation — this is the signature "
           "of a ticket voucher that needs a session.",
    "110": "Failed to get voucher details from the sales server — usually a "
           "ticket voucher that needs a session.",
}


class ApiError(RuntimeError):
    """The transport itself failed (as opposed to an API-level error body)."""


# --------------------------------------------------------------------------- #
# Cinema-name resolution
# --------------------------------------------------------------------------- #

# Schedule display name -> Connect cinema ID, for names that plain string
# matching gets wrong or cannot find. Keys are normalised (lowercase, a-z0-9).
_SPECIAL_CINEMAS = {
    "pavilionkl": "PKL",
    "pavilionkualalumpur": "PKL",
    "pavilionbukitjalil": "PBJ",
    "paviliondamansaraheight": "PDH",
    "paviliondamansaraheights": "PDH",
    "suriaklcc": "KLC",
    "klcc": "KLC",
    "1utama": "BU0",
    "oneutama": "BU0",
    "vivacity": "VIV",
    "vivacitymegamall": "VIV",
    "icity": "ICT",
    "centralicity": "ICT",
    "tasekcentral": "TSC",
    "station18": "S18",
    "thestrand": "STR",
    "strand": "STR",
    "encorpstrand": "STR",
    "sunwaypyramid": "SW0",
    "bukittinggi": "BBT",
    "bukitindah": "BI0",
    "bukitmertajam": "BKM",
    "bukitraja": "BR0",
    "cherasselatan": "CHR",
    "cherassentral": "CTR",
    "seremban2": "S20",
    "serimanjung": "MAN",
    "wangsawalk": "WWM",
    "dpulze": "CYB",
    "gurneyparagon": "GUR",
    "kintacity": "IP0",
    "setiawalk": "STW",
    "sunwayvelocity": "SWV",
    "sunwayputra": "SWP",
    "sunwaysquare": "SWS",
    "tebraucity": "TBR",
    "toppen": "TOP",
    "ksl": "KSL",
    "mines": "MN0",
    "kepong": "KP0",
    "rawang": "RWK",
    "taiping": "TAI",
    "alamanda": "ALM",
    "ampangpoint": "AMP",
    "shamelin": "1SM",
    "1stavenue": "1AV",
}


def _norm(text: str) -> str:
    """Lowercase and drop everything that is not a letter or digit."""
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _core_name(full_name: str) -> str:
    """'TGV Pavilion Kuala Lumpur' -> 'pavilionkualalumpur'."""
    return _norm(re.sub(r"^TGV\s+", "", full_name or "", flags=re.I))


def resolve_cinema_id(schedule_name: str) -> str | None:
    """
    Map a schedule-page cinema name to a Connect cinema ID.

    Order of attempts:
      1. exact match on the normalised name
      2. hand-written special cases
      3. substring containment, most specific (longest) match wins
      4. fuzzy ratio via difflib, if confident enough
    """
    if not schedule_name:
        return None

    target = _norm(schedule_name)
    if not target:
        return None

    for cinema_id, full_name in CINEMA_MAP.items():
        if _core_name(full_name) == target:
            return cinema_id

    if target in _SPECIAL_CINEMAS:
        return _SPECIAL_CINEMAS[target]

    best_id, best_len = None, 0
    for cinema_id, full_name in CINEMA_MAP.items():
        core = _core_name(full_name)
        if not core:
            continue
        if (target in core or core in target) and len(core) > best_len:
            best_id, best_len = cinema_id, len(core)
    if best_id:
        return best_id

    scores = {
        cinema_id: difflib.SequenceMatcher(None, target, _core_name(full_name)).ratio()
        for cinema_id, full_name in CINEMA_MAP.items()
    }
    if scores:
        top_id = max(scores, key=scores.get)
        if scores[top_id] >= 0.62:
            return top_id

    return None


# --------------------------------------------------------------------------- #
# Session-HTML parsing
# --------------------------------------------------------------------------- #

_TR_RE = re.compile(r"<tr\b([^>]*)>(.*?)</tr>", re.S | re.I)
_TD_RE = re.compile(r"<td\b[^>]*>(.*?)</td>", re.S | re.I)
_ATTR_RE = re.compile(r'data-([a-z0-9_-]+)\s*=\s*"([^"]*)"', re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", html or "")).strip()


def parse_sessions(html: str) -> list[dict[str, Any]]:
    """
    Pull session rows out of the screenschedule results table.

    Every real row carries `data-session-id`. Column order is:
        0 film | 1 screen | 2 showing | 3 finishing | 4 status | ... | 7 price card
    """
    sessions: list[dict[str, Any]] = []

    for match in _TR_RE.finditer(html or ""):
        row_attrs, row_body = match.group(1), match.group(2)
        attrs = {k.lower(): v for k, v in _ATTR_RE.findall(row_attrs + " " + row_body)}

        session_id = attrs.get("session-id")
        if not session_id:
            continue

        cells = [_text(c) for c in _TD_RE.findall(row_body)]

        def cell(index: int) -> str:
            return cells[index] if index < len(cells) else ""

        sessions.append(
            {
                "sessionId": session_id,
                "filmCode": attrs.get("film-code", ""),
                "film": cell(0) or attrs.get("orig-film", ""),
                "screen": cell(1) or attrs.get("orig-screen", ""),
                "showing": cell(2),
                "finishing": cell(3),
                "status": cell(4),
                "priceCard": cell(7),
            }
        )

    seen, unique = set(), []
    for s in sessions:
        if s["sessionId"] in seen:
            continue
        seen.add(s["sessionId"])
        unique.append(s)
    return unique


# --------------------------------------------------------------------------- #
# Response interpretation
# --------------------------------------------------------------------------- #

def looks_like_ticket_voucher(body: dict[str, Any]) -> bool:
    """
    A failed lookup is the *positive* signal for a ticket voucher.

    F&B and cash vouchers resolve from the barcode alone. Ticket vouchers
    cannot, because the API needs to know which cinema/session you intend to
    redeem against — so it returns errorCode 100/110 instead.
    """
    return str((body or {}).get("errorCode", "")).strip() in TICKET_ONLY_ERROR_CODES


def detect_type(body: dict[str, Any]) -> tuple[str, str]:
    """Return (kind, human summary) from the redemption blocks."""
    body = body or {}
    ticket = body.get("ticketRedemptions") or {}
    payment = body.get("paymentRedemptions") or {}
    misc = body.get("miscellaneousRedemptions") or {}

    t_avail = ticket.get("available") or 0
    p_avail = payment.get("available") or 0
    m_avail = misc.get("available") or 0
    p_value = payment.get("paymentValueInCents") or 0

    if t_avail and not p_avail and not m_avail:
        return "ticket", f"{t_avail} ticket redemption(s) available"
    if p_avail and not t_avail and not m_avail:
        return "cash", f"{p_avail} cash redemption(s) available · value {p_value / 100:.2f}"
    if m_avail and not t_avail and not p_avail:
        summary = f"{m_avail} F&B redemption(s) available"
        deals = misc.get("deals") or []
        if deals:
            summary += f" · {len(deals)} deal(s) attached"
        return "fb", summary
    if t_avail or p_avail or m_avail:
        return "mixed", f"ticket:{t_avail} · cash:{p_avail} · fb:{m_avail}"
    return "unknown", "No redemptions available — the voucher may be fully used."


def error_text(body: dict[str, Any]) -> str:
    body = body or {}
    parts = [
        e.get("description", "")
        for e in (body.get("errors") or [])
        if isinstance(e, dict)
    ]
    parts = [p for p in parts if p]
    return "; ".join(parts) or body.get("error") or body.get("raw", "") or "Unknown error"


def fmt_dt(value: str | None) -> str:
    if not value:
        return "—"
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.strftime("%d %b %Y, %H:%M")
    except ValueError:
        return str(value)


# --------------------------------------------------------------------------- #
# Transport
# --------------------------------------------------------------------------- #

def _as_json(resp) -> dict[str, Any]:
    try:
        body = resp.json()
    except ValueError:
        body = {"raw": resp.text[:2000]}
    if not isinstance(body, dict):
        body = {"value": body}
    body["statusCode"] = resp.status_code
    return body


def explain_transport_error(exc: Exception) -> str:
    name = type(exc).__name__
    if "SSL" in name or "SSL" in str(exc) or "ssl" in str(exc):
        return (
            f"{name}: {exc}\n\n"
            "This is a TLS failure, not an API error. If Python cannot "
            "negotiate TLS on this machine, switch the sidebar to "
            "'Node proxy' mode."
        )
    return f"{name}: {exc}"


class DirectClient:
    """Calls the Vista Connect API and the schedule page directly."""

    def __init__(self, vista_host: str, schedule_host: str, token: str, timeout: int = 25):
        self.vista_host = vista_host.rstrip("/")
        self.schedule_host = schedule_host.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.http = requests.Session()
        # Internal hosts use a self-signed certificate.
        self.http.verify = False

    def _vista_headers(self) -> dict[str, str]:
        return {"Accept": "application/json", "connectApiToken": self.token}

    def get_voucher(self, barcode: str) -> dict[str, Any]:
        url = f"{self.vista_host}/vouchers/{barcode}"
        try:
            resp = self.http.get(url, headers=self._vista_headers(), timeout=self.timeout)
        except requests.RequestException as exc:
            raise ApiError(explain_transport_error(exc)) from exc
        return _as_json(resp)

    def validate_ticket(self, barcode: str, session_id: str, cinema_id: str) -> dict[str, Any]:
        url = f"{self.vista_host}/vouchers/validate-ticket-voucher-for-session"
        payload = {"Barcode": barcode, "SessionId": session_id, "CinemaId": cinema_id}
        try:
            resp = self.http.post(
                url, headers=self._vista_headers(), json=payload, timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise ApiError(explain_transport_error(exc)) from exc
        body = _as_json(resp)
        body["_resolvedCinemaId"] = cinema_id
        return body

    def version(self) -> dict[str, Any]:
        try:
            resp = self.http.get(
                f"{self.vista_host}/version",
                headers=self._vista_headers(),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise ApiError(explain_transport_error(exc)) from exc
        return _as_json(resp)

    def _schedule_session(self):
        """Open the schedule page and steal its antiforgery token + cookies."""
        sess = requests.Session()
        sess.verify = False
        resp = sess.get(f"{self.schedule_host}/screenschedule/?tab=main", timeout=self.timeout)
        match = re.search(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', resp.text)
        return sess, (match.group(1) if match else None)

    def list_cinemas(self) -> list[str]:
        sess, token = self._schedule_session()
        headers = {"X-Requested-With": "XMLHttpRequest"}
        if token:
            headers["RequestVerificationToken"] = token
        resp = sess.get(
            f"{self.schedule_host}/screenschedule/Schedule/Tab",
            headers=headers,
            timeout=self.timeout,
        )
        names = re.findall(r'<option value="([^"]*)">', resp.text)
        return [n for n in names if n.strip()]

    def get_sessions(self, cinema: str, date_str: str) -> list[dict[str, Any]]:
        """date_str must be YYYY/MM/DD."""
        sess, token = self._schedule_session()
        headers = {"X-Requested-With": "XMLHttpRequest"}
        if token:
            headers["RequestVerificationToken"] = token
        resp = sess.post(
            f"{self.schedule_host}/screenschedule/Schedule/Results",
            data={
                "SelectedDate": date_str,
                "SelectedCinema": cinema,
                "GroupBy": "By film",
                "StatusFilter": "O",
            },
            headers=headers,
            timeout=self.timeout,
        )
        return parse_sessions(resp.text)


class ProxyClient:
    """
    Talks to the bundled Node gateway (`voucher-validator-server.js`), which in
    turn calls Vista. Useful when Python's TLS stack is broken on the host.
    """

    def __init__(self, base: str = DEFAULT_PROXY_BASE, timeout: int = 30):
        self.base = base.rstrip("/")
        self.timeout = timeout
        self.http = requests.Session()

    def _get(self, path: str, **params) -> dict[str, Any]:
        try:
            resp = self.http.get(f"{self.base}{path}", params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise ApiError(explain_transport_error(exc)) from exc
        try:
            return resp.json()
        except ValueError as exc:
            raise ApiError(f"Gateway returned non-JSON (HTTP {resp.status_code})") from exc

    def get_voucher(self, barcode: str) -> dict[str, Any]:
        return self._get("/api/voucher-details", barcode=barcode)

    def validate_ticket(self, barcode: str, session_id: str, cinema_id: str) -> dict[str, Any]:
        return self._get(
            "/api/validate-ticket-voucher",
            barcode=barcode,
            sessionId=session_id,
            cinemaId=cinema_id,
        )

    def version(self) -> dict[str, Any]:
        return self._get("/api/version")

    def list_cinemas(self) -> list[str]:
        return self._get("/api/cinemas").get("cinemas", [])

    def get_sessions(self, cinema: str, date_str: str) -> list[dict[str, Any]]:
        return self._get("/api/sessions", cinema=cinema, date=date_str).get("sessions", [])
