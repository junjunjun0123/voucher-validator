"""
Voucher Validator — Vista Connect  (Streamlit UI)

A single scan box for all three voucher types:

    Ticket voucher  -> needs a cinema + session to validate
    F&B voucher     -> the lookup alone is the validation
    Cash voucher    -> the lookup alone is the validation

You do NOT have to know the type up front. `GET /vouchers/{barcode}` succeeds
for F&B / cash vouchers, and fails with `errorCode 100 or 110` *only* for
ticket vouchers (they need a cinema/session context). So a failed lookup is
itself the signal to ask for a session.

Run locally
-----------
    pip install -r requirements.txt
    streamlit run app.py

All the API logic lives in `vista.py`; this file is only the interface.
"""

from __future__ import annotations

import datetime as dt

import streamlit as st
import urllib3

from vista import (
    DEFAULT_PROXY_BASE,
    DEFAULT_SCHEDULE_HOST,
    DEFAULT_VISTA_HOST,
    ERROR_CODE_NOTES,
    ApiError,
    DirectClient,
    ProxyClient,
    detect_type,
    error_text,
    fmt_dt,
    looks_like_ticket_voucher,
    resolve_cinema_id,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

_BADGE_COLORS = {
    "ticket": ("#dbeafe", "#1e40af"),
    "fb": ("#fef3c7", "#92400e"),
    "cash": ("#d1fae5", "#065f46"),
    "mixed": ("#ede9fe", "#5b21b6"),
    "unknown": ("#f1f5f9", "#475569"),
    "ok": ("#d1fae5", "#065f46"),
    "fail": ("#fee2e2", "#991b1b"),
}


def badge_html(text: str, kind: str = "unknown") -> str:
    bg, fg = _BADGE_COLORS.get(kind, _BADGE_COLORS["unknown"])
    return (
        f'<span style="background:{bg};color:{fg};padding:3px 10px;border-radius:11px;'
        f'font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.03em;'
        f'white-space:nowrap">{text}</span>'
    )


def show_badge(text: str, kind: str = "unknown") -> None:
    st.markdown(badge_html(text, kind), unsafe_allow_html=True)


def secret(key: str, default: str = "") -> str:
    """Read from st.secrets if a secrets file exists, otherwise use the default."""
    try:
        return str(st.secrets.get(key, default))
    except Exception:
        return default


def init_state() -> None:
    defaults = {
        "voucher": None,
        "voucher_barcode": "",
        "sessions": [],
        "sessions_for": None,
        "validate_result": None,
        "cinema_names": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


# --------------------------------------------------------------------------- #
# Page setup
# --------------------------------------------------------------------------- #

st.set_page_config(
    page_title="Voucher Validator · Vista Connect",
    page_icon="🎟️",
    layout="wide",
)
init_state()


# --------------------------------------------------------------------------- #
# Sidebar — connection settings
# --------------------------------------------------------------------------- #

with st.sidebar:
    st.header("Connection")

    transport = st.radio(
        "Transport",
        options=["Direct", "Node proxy"],
        index=0,
        help=(
            "Direct: this app calls the Vista API itself (needs working TLS). "
            "Node proxy: this app calls the bundled Node gateway, which calls "
            "Vista for you. Use the proxy if Python cannot do TLS here."
        ),
    )

    if transport == "Direct":
        token = st.text_input(
            "connectApiToken",
            value=secret("CONNECT_API_TOKEN"),
            type="password",
            help="Sent as the `connectApiToken` header on every Vista request.",
        )
        vista_host = st.text_input("Vista host", value=secret("VISTA_HOST", DEFAULT_VISTA_HOST))
        schedule_host = st.text_input(
            "Schedule host", value=secret("SCHEDULE_HOST", DEFAULT_SCHEDULE_HOST)
        )
        proxy_base = DEFAULT_PROXY_BASE
    else:
        proxy_base = st.text_input(
            "Gateway URL", value=secret("PROXY_BASE", DEFAULT_PROXY_BASE)
        )
        token, vista_host, schedule_host = "", "", ""

    def build_client():
        if transport == "Direct":
            if not token:
                raise ApiError("No connectApiToken set — add it in the sidebar.")
            return DirectClient(vista_host, schedule_host, token)
        return ProxyClient(proxy_base)

    if st.button("Test connection", use_container_width=True):
        try:
            with st.spinner("Pinging…"):
                info = build_client().version()
            st.success("Connected")
            st.json(info, expanded=False)
        except Exception as exc:  # noqa: BLE001 - show the user everything
            st.error("Connection failed")
            st.code(str(exc), language="text")

    st.divider()
    with st.expander("How the voucher type is detected"):
        st.markdown(
            """
| Type | `GET /vouchers/{barcode}` | Needs session |
|---|---|---|
| **F&B** | succeeds · `miscellaneousRedemptions.available > 0` | no |
| **Cash** | succeeds · `paymentRedemptions.available > 0` | no |
| **Ticket** | fails with `errorCode 100` or `110` | **yes** |

A *failed* lookup is therefore the signal for a ticket voucher — the codes
mean "no cinema context, tell me which session you want". No PIN is involved.
"""
        )


# --------------------------------------------------------------------------- #
# Header + step 1
# --------------------------------------------------------------------------- #

st.title("🎟️ Voucher Validator")
st.caption(
    "Vista Connect API · Ticket / F&B / Cash vouchers · "
    "scan once, the tool works out the type for you"
)

col_input, col_button = st.columns([4, 1], vertical_alignment="bottom")

with col_input:
    barcode = st.text_input(
        "Voucher barcode",
        value=st.session_state.voucher_barcode,
        placeholder="e.g. JP0010001235",
    )

with col_button:
    do_lookup = st.button("Look up voucher", type="primary", use_container_width=True)

if do_lookup:
    cleaned = (barcode or "").strip()
    if not cleaned:
        st.warning("Enter a barcode first.")
    else:
        st.session_state.voucher_barcode = cleaned
        st.session_state.voucher = None
        st.session_state.validate_result = None
        st.session_state.sessions = []
        st.session_state.sessions_for = None
        try:
            with st.spinner(f"Looking up {cleaned}…"):
                st.session_state.voucher = build_client().get_voucher(cleaned)
        except ApiError as exc:
            st.error("Could not reach the API")
            st.code(str(exc), language="text")


# --------------------------------------------------------------------------- #
# Step 2 — interpret the lookup
# --------------------------------------------------------------------------- #

voucher = st.session_state.voucher
is_ticket = voucher is not None and looks_like_ticket_voucher(voucher)

if voucher is not None:
    st.divider()
    st.subheader("2. Voucher details")

    if is_ticket:
        show_badge("ticket voucher · session required", "ticket")
        code = str(voucher.get("errorCode", ""))

        left, right = st.columns(2)
        with left:
            st.markdown(
                f"**Barcode** · `{st.session_state.voucher_barcode}`  \n"
                f"**HTTP** · `{voucher.get('statusCode', '?')}`  \n"
                f"**errorCode** · `{code}`  \n"
                f"**Description** · {error_text(voucher)}"
            )
        with right:
            st.info(
                ERROR_CODE_NOTES.get(code, "The lookup needs a session context.")
                + "\n\nPick a cinema and a session below to validate it."
            )

        with st.expander("Raw lookup response"):
            st.json(voucher)

    else:
        kind, summary = detect_type(voucher)
        status = voucher.get("status", "")

        row = badge_html(f"{kind} voucher", kind)
        if status:
            row += " " + badge_html(
                status, "ok" if status in ("Issued", "PartiallyRedeemed") else "fail"
            )
        st.markdown(row, unsafe_allow_html=True)

        left, right = st.columns(2)
        with left:
            st.markdown(
                f"**Barcode** · `{voucher.get('id') or st.session_state.voucher_barcode}`  \n"
                f"**Voucher code** · `{voucher.get('code', '')}`  \n"
                f"**Type name** · {voucher.get('typeName') or '—'}  \n"
                f"**Status** · {status or '—'}  \n"
                f"**Valid from** · {fmt_dt(voucher.get('validFromDateTime'))}  \n"
                f"**Expires** · {fmt_dt(voucher.get('expiryDateTime'))}"
            )
        with right:
            if kind in ("ticket", "cash", "fb"):
                st.metric("Redemptions available", summary.split(" ")[0])
            st.caption(summary)

        if kind in ("fb", "cash", "mixed", "unknown"):
            st.success(
                f"No session is needed for a {kind} voucher — "
                "the lookup above *is* the validation."
            )

        with st.expander("Raw lookup response"):
            st.json(voucher)


# --------------------------------------------------------------------------- #
# Step 3 + 4 — session picker and validation (ticket vouchers only)
# --------------------------------------------------------------------------- #

if is_ticket:
    st.divider()
    st.subheader("3. Pick a session")
    st.caption(
        "The session ID is what the API needs. Film name and time are shown so "
        "you can pick the right one."
    )

    col_a, col_b = st.columns([3, 2], vertical_alignment="bottom")

    with col_a:
        if st.session_state.cinema_names is None:
            st.caption("The cinema list comes from the schedule page.")
            if st.button("Load cinema list"):
                try:
                    with st.spinner("Loading cinemas…"):
                        st.session_state.cinema_names = build_client().list_cinemas()
                    st.rerun()
                except ApiError as exc:
                    st.error("Could not load cinemas")
                    st.code(str(exc), language="text")
            cinema = None
        else:
            cinema = st.selectbox(
                "Location (cinema)",
                options=st.session_state.cinema_names,
                index=None,
                placeholder="-- select cinema --",
                format_func=lambda name: f"{name}  ({resolve_cinema_id(name) or 'id ?'})",
            )

    with col_b:
        show_date = st.date_input("Show date", value=dt.date.today())

    if cinema:
        cinema_id = resolve_cinema_id(cinema)
        if cinema_id:
            st.caption(f"Resolved cinema ID · `{cinema_id}`")
        else:
            st.warning(
                f"Could not map **{cinema}** to a Connect cinema ID. Validation "
                "will probably fail with `CinemaNotFound` — add the mapping to "
                "`cinema_map.py`."
            )

        target = (cinema, show_date.isoformat())
        if st.button("Load sessions", type="secondary"):
            try:
                with st.spinner(f"Loading sessions for {cinema}…"):
                    st.session_state.sessions = build_client().get_sessions(
                        cinema, show_date.strftime("%Y/%m/%d")
                    )
                    st.session_state.sessions_for = target
            except ApiError as exc:
                st.error("Could not load sessions")
                st.code(str(exc), language="text")

        sessions = st.session_state.sessions
        if sessions and st.session_state.sessions_for == target:
            films = sorted({s["film"] for s in sessions if s["film"]})

            if not films:
                st.info("Sessions were returned but none had a film name.")
            else:
                col_film, col_time = st.columns(2)
                with col_film:
                    film = st.selectbox(
                        f"Film · {len(films)} showing", options=films, index=0
                    )
                with col_time:
                    choices = sorted(
                        (s for s in sessions if s["film"] == film),
                        key=lambda s: s.get("showing", ""),
                    )
                    session = st.selectbox(
                        f"Session · {len(choices)} time(s)",
                        options=choices,
                        index=0,
                        format_func=lambda s: (
                            f"{s['showing']}–{s['finishing']}  ·  {s['screen']}"
                            f"  [{s['status']}]"
                            + (f"  ·  {s['priceCard']}" if s["priceCard"] else "")
                        ),
                    )

                if session:
                    st.markdown(
                        f"Selected **{film}** · {session['showing']}–"
                        f"{session['finishing']} · {session['screen']} · "
                        f"session ID `{session['sessionId']}`"
                    )

                    st.divider()
                    st.subheader("4. Validate")

                    if st.button("Validate ticket voucher", type="primary"):
                        try:
                            with st.spinner("Validating…"):
                                st.session_state.validate_result = build_client().validate_ticket(
                                    st.session_state.voucher_barcode,
                                    session["sessionId"],
                                    cinema_id or cinema,
                                )
                        except ApiError as exc:
                            st.error("Could not reach the API")
                            st.code(str(exc), language="text")
        elif sessions:
            st.info("Those sessions belong to a different cinema/date — press **Load sessions** again.")


# --------------------------------------------------------------------------- #
# Result
# --------------------------------------------------------------------------- #

result = st.session_state.validate_result
if result is not None:
    st.divider()
    st.subheader("Result")

    failed = bool(result.get("error") or result.get("errorCode"))
    remaining = result.get("numberOfRedemptionsRemaining")
    ticket_types = result.get("ticketTypes") or []

    if failed:
        show_badge("invalid", "fail")
        st.markdown(
            f"**errorCode** · `{result.get('errorCode') or result.get('error')}`  \n\n"
            f"{error_text(result)}"
        )
    elif ticket_types:
        show_badge("valid", "ok")
        if remaining is not None:
            st.markdown(badge_html(f"{remaining} redemption(s) left", "ok"), unsafe_allow_html=True)
        st.markdown("**Ticket types available**")
        for tt in ticket_types:
            code = tt.get("ticketTypeCode", tt) if isinstance(tt, dict) else tt
            st.markdown(f"- `{code}`")
    else:
        show_badge("unknown", "unknown")
        st.markdown("The API returned a response we do not recognise.")

    if result.get("_resolvedCinemaId"):
        st.caption(f"Cinema sent as `{result['_resolvedCinemaId']}`")

    with st.expander("Raw validation response", expanded=True):
        st.json(result)


st.divider()
st.caption(
    "Vista Connect · voucher validation. "
    "Ticket vouchers need a session; F&B and cash vouchers do not."
)
