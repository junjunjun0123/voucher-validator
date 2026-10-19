# Voucher Validator — Vista Connect

A small Streamlit app for validating TGV vouchers against the Vista Connect API.
One scan box handles all three voucher types — you never have to say which type
a voucher is.

| Voucher | `GET /vouchers/{barcode}` | Needs a session? |
|---|---|---|
| **Ticket** | fails with `errorCode 100` / `110` | **yes** — cinema + session |
| **F&B** | succeeds, `miscellaneousRedemptions.available > 0` | no |
| **Cash** | succeeds, `paymentRedemptions.available > 0` | no |

### Why a failed lookup is the useful case

F&B and cash vouchers resolve from the barcode alone. Ticket vouchers cannot,
because the API needs to know which cinema and session you intend to redeem
against — so it answers `errorCode 100` ("no cinemas allow online voucher
validation") or `110` instead of returning details.

That means the *error itself* is the fingerprint of a ticket voucher. The app
detects it (`vista.looks_like_ticket_voucher`) and jumps straight to the cinema
+ session picker. No PIN is involved — these vouchers do not use one.

---

## Files

| File | Purpose |
|---|---|
| `app.py` | Streamlit UI only |
| `vista.py` | All API logic: clients, cinema resolution, HTML parsing, interpretation |
| `cinema_map.py` | Connect cinema ID → full name (from `GET /OData.svc/Cinemas`) |
| `test_vista.py` | Logic tests; runs without Streamlit installed |
| `voucher-validator-server.js` | Optional Node gateway (see *Transport modes*) |

Run the tests any time:

```bash
python test_vista.py
```

---

## Running it

```bash
pip install -r requirements.txt
streamlit run app.py
```

Then open the URL Streamlit prints (usually <http://localhost:8501>).

Put your API token in the sidebar, or better, create `.streamlit/secrets.toml`:

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# then edit it and set CONNECT_API_TOKEN
```

`.streamlit/secrets.toml` is git-ignored, so the token never reaches GitHub.

---

## Transport modes

The sidebar has two modes, because Python's TLS stack is not always usable on a
corporate Windows machine.

### Direct (default)

The app calls Vista itself with `requests`. Requires Python to be able to do a
TLS handshake to `https://ufawsprdwebapp506`.

### Node proxy

The app calls `voucher-validator-server.js` on `http://localhost:8787`, and that
process calls Vista. Use this when Python cannot negotiate TLS.

```bash
set NODE_TLS_REJECT_UNAUTHORIZED=0
set CONNECT_API_TOKEN=your-token
node voucher-validator-server.js
```

Start the gateway before the app, then pick **Node proxy** in the sidebar.

> **Why this exists:** on some machines a corporate endpoint-security agent
> breaks Python's OpenSSL handshake — `ssl.SSLContext.wrap_socket()` crashes the
> interpreter with an access violation while Node and .NET work fine. Symptoms:
> `pip install` exits silently or dies with `0xC0000005`, and `requests` fails on
> every HTTPS call. Verify with:
>
> ```bash
> python -c "import socket,ssl;c=ssl.create_default_context();s=socket.create_connection(('pypi.org',443),timeout=10);print(c.wrap_socket(s,server_hostname='pypi.org').version())"
> ```
>
> If that crashes, use the Node proxy — or reinstall Python from python.org.

---

## Deploying on GitHub / Streamlit

`app.py` is at the repo root, so Streamlit Community Cloud can deploy it
directly: **New app → pick the repo → main file `app.py`**. Add
`CONNECT_API_TOKEN` under *Settings → Secrets*.

### ⚠️ Streamlit Community Cloud cannot reach your internal API

`ufawsprdwebapp506` resolves to a private address (`10.100.35.158`) and
`172.31.22.65` is a private address too. A cloud-hosted app has no route to
either, so a Community Cloud deployment will load the UI but every API call
will fail with a connection error.

Realistic options:

1. **Run it inside the company network** (recommended). Either `streamlit run
   app.py` on a machine that can reach both hosts, or deploy the container to
   an internal host and share that URL with colleagues.
2. **Use GitHub only as version control**, and run the app from a checkout on an
   internal machine.
3. If you need a shareable URL, host it on an internal server — not on public
   Streamlit Cloud.

Sharing the code on GitHub is fine. Sharing the *running app* only works from
inside the network.

---

## API endpoints used

| Purpose | Endpoint |
|---|---|
| Voucher lookup (all types) | `GET /vouchers/{barcode}` |
| Validate ticket voucher | `POST /vouchers/validate-ticket-voucher-for-session` |
| API version | `GET /version` |
| Cinema list | `GET /OData.svc/Cinemas` (cached in `cinema_map.py`) |
| Sessions + session IDs | schedule page `POST /screenschedule/Schedule/Results` |

The validate payload is just:

```json
{ "Barcode": "JP0010001235", "SessionId": "123456", "CinemaId": "PKL" }
```

### Adding a cinema

If a schedule name fails to resolve (the app shows *"Could not map … to a
Connect cinema ID"*), add it to `_SPECIAL_CINEMAS` in `vista.py`:

```python
"mynewcinema": "XYZ",   # key must be lowercase, letters and digits only
```

Then add a test case to `test_vista.py` and run the tests.
