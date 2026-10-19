// vista-test.js — quick smoke test against the Vista Connect API from your machine.
//
// Run:
//   set NODE_TLS_REJECT_UNAUTHORIZED=0
//   set CONNECT_API_TOKEN=<your token here>
//   "C:/Users/leejh/.workbuddy-ai/binaries/node/versions/22.22.2-6/node.exe" vista-test.js
//
// Without a token it will still hit the diagnostic endpoints (health/version)
// and confirm the host is reachable + the client works.

const { createClient } = require('./vista-connect-client');

const client = createClient(); // picks up CONNECT_API_TOKEN from env

(async () => {
  console.log('--- Vista Connect API smoke test ---');
  console.log('Host: https://ufawsprdwebapp506/WSVistaWebClient');
  console.log('Token present:', !!process.env.CONNECT_API_TOKEN);
  console.log();

  // 1. Diagnostic: version (does not require a token)
  try {
    const v = await client.version();
    console.log('[version] status:', v.status);
    console.log('[version] body  :', v.body || v.raw.slice(0, 200));
  } catch (e) {
    console.log('[version] error:', e.message);
  }

  // 2. Auth-required: GetVoucherDetails for the example barcode from the docs
  //    (will return 401 if no token, 404 if the example barcode doesn't exist in your data)
  try {
    const r = await client.getVoucherDetails('JP0010001235');
    console.log();
    console.log('[getVoucherDetails] status:', r.status);
    if (r.body) {
      console.log('[getVoucherDetails] body  :', JSON.stringify(r.body, null, 2));
    } else {
      console.log('[getVoucherDetails] raw   :', r.raw.slice(0, 300));
    }
  } catch (e) {
    console.log('[getVoucherDetails] error:', e.message);
  }
})();
