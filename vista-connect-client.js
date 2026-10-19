// vista-connect-client.js
// Reusable Node.js client for the Vista Connect API (internal host).
// Run with the managed Node 22 binary so we get a modern TLS stack:
//   set NODE_TLS_REJECT_UNAUTHORIZED=0  (host uses a self-signed cert)
//
// Usage:
//   const client = require('./vista-connect-client');
//   await client.getVoucherDetails('JP0010001235');
//
// Token resolution order:
//   1. constructor argument
//   2. env var CONNECT_API_TOKEN
//   3. env var VISTA_CONNECT_API_TOKEN
//
// Multi-tenant: set env CONNECT_TENANT_ID (or pass tenantId in opts) if your
// Connect instance is multi-tenanted.

const https = require('https');

const DEFAULT_HOST = 'https://ufawsprdwebapp506/WSVistaWebClient';
const NODE_BIN = 'C:/Users/leejh/.workbuddy-ai/binaries/node/versions/22.22.2-6/node.exe';

function buildHeaders(token, opts = {}) {
  const h = {
    'User-Agent': 'vista-connect-client/1.0',
    'Accept': 'application/json',
    'Content-Type': 'application/json',
  };
  if (token) h['connectApiToken'] = token;
  if (opts.tenantId || process.env.CONNECT_TENANT_ID) {
    h['tenantId'] = opts.tenantId || process.env.CONNECT_TENANT_ID;
  }
  if (opts.correlationId) h['correlationId'] = opts.correlationId;
  return h;
}

function request(method, path, { token, body, opts } = {}) {
  const base = (opts && opts.base) || DEFAULT_HOST;
  const url = base + path;
  const headers = buildHeaders(token, opts);
  const payload = body ? JSON.stringify(body) : null;
  if (payload) headers['Content-Length'] = Buffer.byteLength(payload);

  return new Promise((resolve, reject) => {
    const req = https.request(url, {
      method,
      rejectUnauthorized: false,
      timeout: 20000,
      headers,
    }, (res) => {
      let data = '';
      res.setEncoding('utf8');
      res.on('data', (c) => (data += c));
      res.on('end', () => {
        let parsed = null;
        try { parsed = data ? JSON.parse(data) : null; } catch (_) {}
        resolve({
          status: res.statusCode,
          headers: res.headers,
          raw: data,
          body: parsed,
        });
      });
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('request timed out')); });
    if (payload) req.write(payload);
    req.end();
  });
}

function createClient(tokenArg) {
  const token = tokenArg
    || process.env.CONNECT_API_TOKEN
    || process.env.VISTA_CONNECT_API_TOKEN;
  if (!token) {
    console.warn('[vista-connect] WARNING: no connectApiToken set. Calls will return HTTP 401.');
    console.warn('                     Set env CONNECT_API_TOKEN or pass a token to createClient().');
  }

  return {
    // ---- low-level ----
    get:    (path, opts) => request('GET',    path, { token, opts }),
    post:   (path, body, opts) => request('POST',   path, { token, body, opts }),
    put:    (path, body, opts) => request('PUT',    path, { token, body, opts }),
    delete: (path, opts) => request('DELETE', path, { token, opts }),

    // ---- voucher endpoints (from the Ticket Voucher Redemption doc) ----

    // GET /vouchers/{barcode}  -> GetVoucherDetails
    getVoucherDetails: (barcode, opts) =>
      request('GET', `/vouchers/${encodeURIComponent(barcode)}`, { token, opts }),

    // POST /vouchers/validate-ticket-voucher-for-session
    validateTicketVoucherForSession: ({ barcode, pin, sessionId, cinemaId }, opts) =>
      request('POST', '/vouchers/validate-ticket-voucher-for-session', {
        token,
        body: {
          Barcode: barcode,
          Pin: pin,
          SessionId: sessionId,
          CinemaId: cinemaId,
        },
        opts,
      }),

    // GET /RESTData.svc/cinemas/{cinemaId}/sessions/{sessionId}/tickets-for-barcode?voucherBarcode={barcode}
    // GetTicketTypesForBarcode (V1 OData endpoint -> PascalCase, response code in body)
    getTicketTypesForBarcode: (cinemaId, sessionId, barcode, opts) => {
      const q = `?voucherBarcode=${encodeURIComponent(barcode)}`;
      return request('GET',
        `/RESTData.svc/cinemas/${encodeURIComponent(cinemaId)}/sessions/${encodeURIComponent(sessionId)}/tickets-for-barcode${q}`,
        { token, opts });
    },

    // POST /orders/{userSessionId}/sessions/{sessionId}/set-tickets
    // Pass ticket objects in body.Tickets[].TicketDetails = { voucherBarcode, voucherPin, voucherAreaCategoryCode?, ticketTypeCode? }
    setTickets: (userSessionId, sessionId, tickets, opts) =>
      request('POST',
        `/orders/${encodeURIComponent(userSessionId)}/sessions/${encodeURIComponent(sessionId)}/set-tickets`,
        { token, body: { Tickets: tickets }, opts }),

    // POST /orders/{userSessionId}/sessions/{sessionId}/add-tickets
    addTickets: (userSessionId, sessionId, tickets, opts) =>
      request('POST',
        `/orders/${encodeURIComponent(userSessionId)}/sessions/${encodeURIComponent(sessionId)}/add-tickets`,
        { token, body: { Tickets: tickets }, opts }),

    // ---- diagnostic endpoints (don't require a token) ----
    health:  (opts) => request('GET', '/health', { token: null, opts }),
    version: (opts) => request('GET', '/version', { token: null, opts }),
  };
}

module.exports = {
  createClient,
  DEFAULT_HOST,
  NODE_BIN,
};
