// voucher-validator-server.js
// Local interactive server for validating all 3 voucher types against the
// Vista Connect API from your machine.
//
//   - Ticket voucher  -> GET /vouchers/{barcode} + POST /vouchers/validate-ticket-voucher-for-session
//   - F&B voucher      -> GET /vouchers/{barcode} (check miscellaneousRedemptions)
//   - Cash voucher     -> GET /vouchers/{barcode} (check paymentRedemptions)
//
// Run:
//   set NODE_TLS_REJECT_UNAUTHORIZED=0
//   set CONNECT_API_TOKEN=<your token>
//   (or put it in .env.local and load it however you prefer)
//   "C:/Users/leejh/.workbuddy-ai/binaries/node/versions/22.22.2-6/node.exe" voucher-validator-server.js
//
// Then open:  http://localhost:8787

const http  = require('http');
const https = require('https');
const fs    = require('fs');
const path  = require('path');
const { URL } = require('url');

const PORT = 8787;

// --------- Config ---------
const VISTA_HOST  = 'https://ufawsprdwebapp506/WSVistaWebClient';
const SCHEDULE_HOST = 'http://172.31.22.65';
const TOKEN = process.env.CONNECT_API_TOKEN || '';
if (!TOKEN) {
  console.error('ERROR: CONNECT_API_TOKEN is not set.');
  console.error('  set CONNECT_API_TOKEN=<your token>   (Windows cmd)');
  console.error('  export CONNECT_API_TOKEN=<your token> (bash)');
  process.exit(1);
}

process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';

// Load the cinema id->name map (from /OData.svc/Cinemas)
let CINEMA_MAP = {}; // id -> full name (e.g. "TGV Pavilion Kuala Lumpur")
try {
  CINEMA_MAP = JSON.parse(fs.readFileSync(path.join(__dirname, 'cinema-map.json'), 'utf8'));
} catch (_) {
  console.warn('[voucher-validator] WARNING: cinema-map.json not found — ticket voucher validation will fail.');
}

// Build reverse lookup: schedule cinema name -> Connect cinema id (fuzzy)
function resolveCinemaId(scheduleName) {
  if (!scheduleName) return null;
  const target = scheduleName.toLowerCase().replace(/[^a-z0-9]/g, '');
  // Direct stripped match first
  for (const [id, fullName] of Object.entries(CINEMA_MAP)) {
    const stripped = fullName.replace(/^TGV\s+/i, '').trim().toLowerCase().replace(/[^a-z0-9]/g, '');
    if (stripped === target) return id;
  }
  // Substring match (one-way) — longer string contains shorter
  for (const [id, fullName] of Object.entries(CINEMA_MAP)) {
    const stripped = fullName.replace(/^TGV\s+/i, '').trim().toLowerCase().replace(/[^a-z0-9]/g, '');
    if (stripped.includes(target) || target.includes(stripped)) return id;
  }
  // Special-case common short names used by the schedule that don't fuzzy-match
  const specials = {
    'pavilionkl':         'PKL',
    'pavilion bukit jalil': 'PBJ',
    'paviliondamansaraheight': 'PDH',
    'suriaklcc':          'KLC',
    '1utama':             'BU0',
    'vivacity':           'VIV',
    'icity':              'ICT',
    'tasekcentral':       'TSC',
    'station18':          'S18',
    'thestrand':          'STR',
    'thestrand':          'STR',
    'strand':             'STR',
    'sunwaypyramid':      'SW0',
    'bukittinggi':        'BBT',
    'bukitindah':         'BI0',
    'bukitmertajam':      'BKM',
    'bukitraja':          'BR0',
    'cherasselatan':      'CHR',
    'cherassentral':      'CTR',
    'seremban2':          'S20',
    'serimanjung':        'MAN',
    'wangsa walk':        'WWM',
    'wangsa walk':        'WWM',
  };
  if (specials[target]) return specials[target];
  // Last resort: any partial word overlap
  for (const [id, fullName] of Object.entries(CINEMA_MAP)) {
    const stripped = fullName.replace(/^TGV\s+/i, '').trim().toLowerCase().replace(/[^a-z0-9]/g, '');
    // strip common prefixes/suffixes
    const strippedShort = stripped.replace(/kualalumpur/i,'kl').replace(/megamall/i,'').replace(/damansaraheights?/i,'damansaraheight');
    const targetShort = target.replace(/kualalumpur/i,'kl').replace(/megamall/i,'');
    if (strippedShort.includes(targetShort) || targetShort.includes(strippedShort)) return id;
  }
  return null;
}

// --------- Low-level helpers ---------

function httpRequest(urlStr, { method='GET', headers={}, body=null, timeout=20000 } = {}) {
  return new Promise((resolve, reject) => {
    const u = new URL(urlStr);
    const lib = u.protocol === 'https:' ? https : http;
    const opts = {
      method,
      hostname: u.hostname,
      port: u.port || (u.protocol === 'https:' ? 443 : 80),
      path: u.pathname + u.search,
      headers: { 'User-Agent': 'voucher-validator/1.0', ...headers },
      timeout,
    };
    if (u.protocol === 'https:') opts.rejectUnauthorized = false;
    const req = lib.request(opts, (res) => {
      let data = '';
      res.setEncoding('utf8');
      res.on('data', c => (data += c));
      res.on('end', () => {
        let parsed = null;
        try { parsed = data ? JSON.parse(data) : null; } catch (_) {}
        resolve({ status: res.statusCode, headers: res.headers, raw: data, body: parsed });
      });
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('timeout')); });
    if (body) req.write(body);
    req.end();
  });
}

function vistaGet(p) {
  return httpRequest(VISTA_HOST + p, {
    headers: { 'Accept':'application/json', 'connectApiToken': TOKEN }
  });
}
function vistaPost(p, bodyObj) {
  const body = JSON.stringify(bodyObj);
  return httpRequest(VISTA_HOST + p, {
    method: 'POST',
    headers: {
      'Accept':'application/json', 'Content-Type':'application/json',
      'connectApiToken': TOKEN, 'Content-Length': Buffer.byteLength(body)
    },
    body
  });
}

// --------- Schedule (screen-schedule) helpers ---------

async function getScheduleAntiforgery() {
  const r = await httpRequest(SCHEDULE_HOST + '/screenschedule/?tab=main', {});
  const tokenMatch = r.raw.match(/name="__RequestVerificationToken"\s+type="hidden"\s+value="([^"]+)"/);
  const token = tokenMatch ? tokenMatch[1] : null;
  const cookieStr = (r.headers['set-cookie'] || []).map(c => c.split(';')[0]).join('; ');
  return { token, cookieStr };
}

async function getScheduleResults(dateStr, cinemaName) {
  const { token, cookieStr } = await getScheduleAntiforgery();
  const params = new URLSearchParams();
  params.append('SelectedDate', dateStr);
  params.append('SelectedCinema', cinemaName);
  params.append('GroupBy', 'By film');
  params.append('StatusFilter', 'O');
  const data = params.toString();
  const r = await httpRequest(SCHEDULE_HOST + '/screenschedule/Schedule/Results', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      'Content-Length': Buffer.byteLength(data),
      'RequestVerificationToken': token,
      'X-Requested-With': 'XMLHttpRequest',
      'Cookie': cookieStr,
    },
    body: data
  });
  return r.raw; // HTML
}

// Parse session rows from the schedule HTML
function parseSessions(html) {
  const sessions = [];
  const re = /data-session-id="(\d+)"\s+data-film-code="([^"]+)"\s+data-orig-film="([^"]+)"\s+data-real-show="([^"]+)"\s+data-orig-show="([^"]+)"\s+data-screen-num="([^"]+)"\s+data-orig-screen="([^"]+)"[^>]*>/g;
  let m;
  while ((m = re.exec(html)) !== null) {
    const pos = m.index;
    const rowStart = html.lastIndexOf('<tr>', pos);
    const rowEnd = html.indexOf('</tr>', pos);
    const rowHtml = html.slice(rowStart, rowEnd);
    const tds = [...rowHtml.matchAll(/<td[^>]*>([\s\S]*?)<\/td>/g)].map(x => x[1].replace(/<[^>]+>/g,'').trim());
    sessions.push({
      sessionId:    m[1],
      filmCode:     m[2],
      film:         tds[0] || '',
      screen:       tds[1] || '',
      showing:      tds[2] || '',
      finishing:    tds[3] || '',
      status:       tds[4] || '',
      priceCard:    tds[7] || '',
      realShow:     m[4],
    });
  }
  return sessions;
}

// --------- API route handlers ---------

async function handleApi(req, res, urlObj) {
  const p = urlObj.pathname;
  const q = urlObj.searchParams;
  res.setHeader('Content-Type', 'application/json');

  try {
    // -- Cinemas list (V2 doesn't have a cinemas list endpoint; we use the schedule dropdown list)
    if (p === '/api/cinemas') {
      const { token, cookieStr } = await getScheduleAntiforgery();
      const r = await httpRequest(SCHEDULE_HOST + '/screenschedule/Schedule/Tab', {
        headers: { 'RequestVerificationToken': token, 'X-Requested-With':'XMLHttpRequest', 'Cookie': cookieStr }
      });
      const opts = [...r.raw.matchAll(/<option value="([^"]+)">/g)].map(m => m[1]);
      return sendJson(res, 200, { cinemas: opts });
    }

    // -- Cinemas list with Connect IDs (from OData.svc/Cinemas, mapped to schedule names)
    if (p === '/api/cinemas-full') {
      const list = Object.entries(CINEMA_MAP).map(([id, fullName]) => {
        const stripped = fullName.replace(/^TGV\s+/i, '').trim();
        return { cinemaId: id, name: stripped, fullName };
      });
      list.sort((a, b) => a.name.localeCompare(b.name));
      return sendJson(res, 200, { count: list.length, cinemas: list });
    }

    // -- Resolve a schedule cinema name to a Connect cinema id (for debugging)
    if (p === '/api/resolve-cinema-id') {
      const name = q.get('name');
      const id = resolveCinemaId(name);
      return sendJson(res, 200, { scheduleName: name, cinemaId: id });
    }

    // -- Sessions for a cinema on a date
    if (p === '/api/sessions') {
      const cinema = q.get('cinema') || '';
      const date = q.get('date') || new Date().toISOString().slice(0,10).replace(/-/g,'/');
      const html = await getScheduleResults(date, cinema);
      const sessions = parseSessions(html);
      return sendJson(res, 200, { cinema, date, count: sessions.length, sessions });
    }

    // -- Voucher details (universal — works for all 3 types)
    if (p === '/api/voucher-details') {
      const barcode = q.get('barcode');
      if (!barcode) return sendJson(res, 400, { error: 'barcode required' });
      const r = await vistaGet('/vouchers/' + encodeURIComponent(barcode));
      // Always return HTTP 200 from our proxy, but annotate the body with the upstream
      // status + errorCode so the frontend can detect "ticket voucher needs session"
      // without fetch() treating the upstream 400 as a network failure.
      const body = r.body || { raw: r.raw };
      if (body && typeof body === 'object' && !Array.isArray(body)) {
        body.statusCode = r.status;
        body.barcodeQueried = barcode;
      }
      return sendJson(res, 200, body);
    }

    // -- Validate ticket voucher for session (ticket-type only)
    if (p === '/api/validate-ticket-voucher') {
      const barcode  = q.get('barcode');
      const sessionId = q.get('sessionId');
      const cinemaIdOrName = q.get('cinemaId'); // UI passes the schedule cinema name
      if (!barcode || !sessionId || !cinemaIdOrName)
        return sendJson(res, 400, { error: 'barcode, sessionId, cinemaId required' });

      // Resolve schedule cinema name -> Connect cinema id (e.g. "Pavilion KL" -> "PKL")
      let cinemaId = cinemaIdOrName;
      if (!CINEMA_MAP[cinemaIdOrName]) {
        const resolved = resolveCinemaId(cinemaIdOrName);
        if (resolved) cinemaId = resolved;
      }
      console.log(`    [cinemaId resolve] "${cinemaIdOrName}" -> "${cinemaId}"`);

      // PIN is omitted — these vouchers don't use one.
      const r = await vistaPost('/vouchers/validate-ticket-voucher-for-session', {
        Barcode: barcode, SessionId: sessionId, CinemaId: cinemaId
      });
      const resp = r.body || { raw: r.raw };
      // Annotate the response with what we resolved, for transparency
      if (resp && typeof resp === 'object' && !Array.isArray(resp)) {
        resp._resolvedCinemaId = cinemaId;
        resp._resolvedFrom     = cinemaIdOrName;
      }
      return sendJson(res, r.status, resp);
    }

    // -- Version (diagnostic, no auth)
    if (p === '/api/version') {
      const r = await vistaGet('/version');
      return sendJson(res, r.status, r.body || { raw: r.raw });
    }

    return sendJson(res, 404, { error: 'unknown api path: ' + p });
  } catch (e) {
    return sendJson(res, 500, { error: e.message });
  }
}

function sendJson(res, status, obj) {
  const body = JSON.stringify(obj, null, 2);
  console.log(`    -> ${status}  ${body.slice(0,400).replace(/\s+/g,' ')}`);
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end(body);
}

// --------- Static file serving ---------

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js':   'application/javascript',
  '.css':  'text/css',
  '.json': 'application/json',
  '.png':  'image/png',
  '.ico':  'image/x-icon',
};

function serveStatic(req, res, urlObj) {
  let p = urlObj.pathname;
  if (p === '/' || p === '') p = '/voucher-validator.html';
  // Only serve files inside the workspace dir
  const filePath = path.join(__dirname, p);
  if (!filePath.startsWith(__dirname)) {
    res.writeHead(403); res.end('forbidden'); return;
  }
  fs.readFile(filePath, (err, data) => {
    if (err) { res.writeHead(404); res.end('not found: ' + p); return; }
    const ext = path.extname(filePath).toLowerCase();
    res.writeHead(200, { 'Content-Type': MIME[ext] || 'application/octet-stream' });
    res.end(data);
  });
}

// --------- Main server ---------

const server = http.createServer(async (req, res) => {
  const urlObj = new URL(req.url, 'http://localhost:' + PORT);
  if (urlObj.pathname.startsWith('/api/')) {
    console.log(`[${new Date().toISOString().slice(11,19)}] ${req.method} ${urlObj.pathname}${urlObj.search}`);
    await handleApi(req, res, urlObj);
  } else {
    serveStatic(req, res, urlObj);
  }
});

server.listen(PORT, () => {
  console.log('========================================');
  console.log('  Voucher Validator running');
  console.log('========================================');
  console.log('Open in browser:  http://localhost:' + PORT);
  console.log();
  console.log('Token:    ' + (TOKEN ? 'present' : 'MISSING'));
  console.log('Vista:    ' + VISTA_HOST);
  console.log('Schedule: ' + SCHEDULE_HOST);
  console.log();
  console.log('Press Ctrl+C to stop.');
});
