"""Logic tests for vista.py — runs without requests/streamlit installed."""
import sys, types

# --- stub `requests` so vista.py can be imported on this machine -------------
fake = types.ModuleType("requests")
class RequestException(Exception): pass
fake.RequestException = RequestException
fake.Session = object
sys.modules["requests"] = fake

import vista

failures = []
def check(name, got, want):
    ok = got == want
    print(("  PASS  " if ok else "  FAIL  ") + f"{name}: got={got!r} want={want!r}")
    if not ok:
        failures.append(name)

print("\n=== resolve_cinema_id ===")
cases = [
    ("Pavilion KL", "PKL"),
    ("Pavilion Kuala Lumpur", "PKL"),
    ("The Strand", "STR"),
    ("Encorp Strand", "STR"),
    ("1 Utama", "BU0"),
    ("Suria KLCC", "KLC"),
    ("Vivacity", "VIV"),
    ("i-City", "ICT"),
    ("Tasek Central", "TSC"),
    ("Station 18", "S18"),
    ("Sunway Pyramid", "SW0"),
    ("Bukit Tinggi", "BBT"),
    ("Wangsa Walk", "WWM"),
    ("Cheras Selatan", "CHR"),
    ("Seremban 2", "S20"),
    ("Gurney Paragon", "GUR"),
    ("Pavilion Bukit Jalil", "PBJ"),
    ("Pavilion Damansara Heights", "PDH"),
    ("DPulze", "CYB"),
    ("KSL City", "KSL"),
    ("Toppen", "TOP"),
]
for name, want in cases:
    check(f"{name!r}", vista.resolve_cinema_id(name), want)

check("empty string", vista.resolve_cinema_id(""), None)
check("None", vista.resolve_cinema_id(None), None)

print("\n=== looks_like_ticket_voucher ===")
check("errorCode 100", vista.looks_like_ticket_voucher({"errorCode": 100}), True)
check("errorCode '110'", vista.looks_like_ticket_voucher({"errorCode": "110"}), True)
check("errorCode 200", vista.looks_like_ticket_voucher({"errorCode": 200}), False)
check("success body", vista.looks_like_ticket_voucher({"id": "x", "status": "Issued"}), False)

print("\n=== detect_type ===")
check("ticket only", vista.detect_type({"ticketRedemptions": {"available": 2}})[0], "ticket")
check("cash only", vista.detect_type({"paymentRedemptions": {"available": 1, "paymentValueInCents": 2500}})[0], "cash")
check("fb only", vista.detect_type({"miscellaneousRedemptions": {"available": 3, "deals": [{}, {}]}})[0], "fb")
check("mixed", vista.detect_type({"ticketRedemptions": {"available": 1}, "paymentRedemptions": {"available": 2}})[0], "mixed")
check("none", vista.detect_type({})[0], "unknown")
cash_summary = vista.detect_type({"paymentRedemptions": {"available": 1, "paymentValueInCents": 2500}})[1]
check("cash value formatting", cash_summary, "1 cash redemption(s) available · value 25.00")
fb_summary = vista.detect_type({"miscellaneousRedemptions": {"available": 3, "deals": [{}, {}]}})[1]
check("fb deal count", fb_summary, "3 F&B redemption(s) available · 2 deal(s) attached")

print("\n=== parse_sessions ===")
html = """
<table><tbody>
<tr class="row" data-session-id="100001" data-film-code="HO0001" data-orig-film="Film A"
    data-real-show="2026-10-19 14:30" data-orig-show="14:30" data-screen-num="3"
    data-orig-screen="Hall 3">
  <td><a href="#">Film A</a></td><td>Hall 3</td><td>14:30</td><td>16:45</td>
  <td>Open</td><td>x</td><td>y</td><td>Adult RM18</td>
</tr>
<tr class="row" data-session-id="100002" data-film-code="HO0001" data-orig-film="Film A"
    data-real-show="2026-10-19 19:00" data-orig-show="19:00" data-screen-num="1"
    data-orig-screen="Hall 1">
  <td>Film A</td><td>Hall 1</td><td>19:00</td><td>21:15</td>
  <td>Open</td><td>x</td><td>y</td><td>Adult RM20</td>
</tr>
<tr><td>header row with no session</td></tr>
<tr class="row" data-session-id="100001" data-orig-film="Film A">
  <td>Film A</td><td>Hall 3</td><td>14:30</td><td>16:45</td><td>Open</td><td>x</td><td>y</td><td>Adult RM18</td>
</tr>
</tbody></table>
"""
sessions = vista.parse_sessions(html)
check("session count (dedup)", len(sessions), 2)
check("first session id", sessions[0]["sessionId"], "100001")
check("first film", sessions[0]["film"], "Film A")
check("first screen", sessions[0]["screen"], "Hall 3")
check("first showing", sessions[0]["showing"], "14:30")
check("first finishing", sessions[0]["finishing"], "16:45")
check("first status", sessions[0]["status"], "Open")
check("first priceCard", sessions[0]["priceCard"], "Adult RM18")
check("second showing", sessions[1]["showing"], "19:00")
check("empty html", vista.parse_sessions(""), [])

print("\n=== fmt_dt ===")
check("iso", vista.fmt_dt("2026-10-19T14:30:00"), "19 Oct 2026, 14:30")
check("none", vista.fmt_dt(None), "—")
check("garbage", vista.fmt_dt("not-a-date"), "not-a-date")

print("\n=== error_text ===")
check("errors array", vista.error_text({"errors": [{"description": "Bad voucher"}]}), "Bad voucher")
check("error field", vista.error_text({"error": "boom"}), "boom")

print("\n" + ("ALL TESTS PASSED" if not failures else f"{len(failures)} FAILURES: {failures}"))
sys.exit(1 if failures else 0)
