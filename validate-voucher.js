// validate-voucher.js — focused CLI tool for validating a ticket voucher
// against the Vista Connect API, from your machine.
//
// Spec (from /api-docs/creating-orders/ticket-voucher-redemption):
//   POST /vouchers/validate-ticket-voucher-for-session
//   Body: { Barcode, Pin, SessionId, CinemaId }
//   Success -> { ticketTypes:[{ticketTypeCode}], numberOfRedemptionsRemaining }
//   Errors via standard HTTP status codes (V2-style endpoint).
//
// Usage:
//   set NODE_TLS_REJECT_UNAUTHORIZED=0
//   set CONNECT_API_TOKEN=<your token>
//   "C:/Users/leejh/.workbuddy-ai/binaries/node/versions/22.22.2-6/node.exe" validate-voucher.js ^
//     --barcode JP0010001235 --pin 6839 --session 1234 --cinema 0001
//
// Flags:
//   --barcode   Voucher barcode (required)
//   --pin       Voucher PIN (optional — only if the voucher requires one)
//   --session   Session ID (required)
//   --cinema    Cinema ID (required)
//   --details   Also call GetVoucherDetails first for status/expiry/redemptions
//   --json      Output raw JSON only (no pretty interpretation)

const { createClient } = require('./vista-connect-client');

function parseArgs(argv) {
  const out = { json: false, details: false };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--json') out.json = true;
    else if (a === '--details') out.details = true;
    else if (a.startsWith('--')) {
      const key = a.slice(2);
      out[key] = argv[++i];
    }
  }
  return out;
}

function bail(msg) {
  console.error('ERROR: ' + msg);
  process.exit(2);
}

async function main() {
  const args = parseArgs(process.argv);

  // Read token from env (or --token)
  if (args.token) process.env.CONNECT_API_TOKEN = args.token;
  const client = createClient();

  const barcode = args.barcode || bail('--barcode is required');
  const sessionId = args.session || bail('--session is required');
  const cinemaId = args.cinema || bail('--cinema is required');
  const pin = args.pin; // optional

  const out = { barcode, pin: pin || null, sessionId, cinemaId };

  if (args.json) {
    // Raw mode — just print raw responses
    if (args.details) {
      const d = await client.getVoucherDetails(barcode);
      console.log(JSON.stringify({ step: 'getVoucherDetails', status: d.status, body: d.body || d.raw }, null, 2));
    }
    const v = await client.validateTicketVoucherForSession({
      barcode, pin, sessionId, cinemaId,
    });
    console.log(JSON.stringify({ step: 'validateTicketVoucherForSession', status: v.status, body: v.body || v.raw }, null, 2));
    return;
  }

  console.log('=== Voucher Validation ===');
  console.log(`Barcode : ${barcode}`);
  console.log(`Pin     : ${pin ? '**** (provided)' : '(none)'}`);
  console.log(`Session : ${sessionId}`);
  console.log(`Cinema  : ${cinemaId}`);
  console.log(`Token   : ${process.env.CONNECT_API_TOKEN ? 'present' : 'MISSING — will get HTTP 401'}`);
  console.log();

  // Optional pre-flight: GetVoucherDetails
  if (args.details) {
    console.log('--- Step 1: GetVoucherDetails ---');
    const d = await client.getVoucherDetails(barcode);
    if (d.status === 200 && d.body) {
      console.log(`Status        : ${d.body.status}`);
      console.log(`Type          : ${d.body.typeName}`);
      console.log(`Ticket redems : ${d.body.ticketRedemptions?.available}`);
      console.log(`Payment redems: ${d.body.paymentRedemptions?.available} (value ${d.body.paymentRedemptions?.paymentValueInCents}c)`);
      console.log(`Valid from    : ${d.body.validFromDateTime}`);
      console.log(`Expires       : ${d.body.expiryDateTime}`);
      const expired = d.body.expiryDateTime && new Date(d.body.expiryDateTime) < new Date();
      if (expired) console.log('!! Voucher has expired');
    } else {
      console.log(`HTTP ${d.status}: ${(d.body && d.body.errorCode) || d.raw.slice(0,200)}`);
    }
    console.log();
  }

  // Main: ValidateTicketVoucherForSession
  console.log('--- Step 2: ValidateTicketVoucherForSession ---');
  const r = await client.validateTicketVoucherForSession({
    barcode, pin, sessionId, cinemaId,
  });

  out.validateStatus = r.status;

  if (r.status === 200 && r.body && r.body.ticketTypes) {
    // Success
    console.log(`RESULT: VALID`);
    console.log(`Redemptions remaining: ${r.body.numberOfRedemptionsRemaining}`);
    console.log(`Available ticket types:`);
    for (const t of r.body.ticketTypes) {
      console.log(`  - code: ${t.ticketTypeCode}`);
    }
    out.valid = true;
    out.ticketTypes = r.body.ticketTypes;
    out.redemptionsRemaining = r.body.numberOfRedemptionsRemaining;
  } else if (r.status === 200 && r.body && typeof r.body.errorCode !== 'undefined') {
    // V2 error inside 200? unusual, but handle
    console.log(`RESULT: INVALID`);
    console.log(`errorCode : ${r.body.errorCode}`);
    console.log(`description: ${(r.body.errors||[]).map(e=>e.description).join('; ')}`);
    out.valid = false;
    out.error = r.body;
  } else if (r.status === 400 || r.status === 401 || r.status === 403 || r.status === 404) {
    console.log(`RESULT: REJECTED (HTTP ${r.status})`);
    if (r.body && r.body.errorCode) {
      console.log(`errorCode   : ${r.body.errorCode}`);
      console.log(`description : ${(r.body.errors||[]).map(e=>e.description).join('; ')}`);
    } else {
      console.log(`body        : ${r.raw.slice(0,300)}`);
    }
    out.valid = false;
    out.error = r.body || r.raw;
  } else {
    console.log(`RESULT: UNEXPECTED (HTTP ${r.status})`);
    console.log(`body: ${r.raw.slice(0,400)}`);
    out.valid = false;
  }

  console.log();
  console.log('Full response object:');
  console.log(JSON.stringify(r.body || r.raw, null, 2));
}

main().catch(e => {
  console.error('FATAL:', e.message);
  process.exit(1);
});
