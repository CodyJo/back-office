import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';

// Set a test secret before importing the server so verifySignature can use it
process.env.GITHUB_WEBHOOK_SECRET = 'test-secret-1234';

const { app, verifySignature } = await import('./server.mjs');

before(async () => {
  await app.ready();
});

after(async () => {
  await app.close();
});

// ─── Helper ───────────────────────────────────────────────────────────────────

function makeSignature(body, secret = 'test-secret-1234') {
  return 'sha256=' + createHmac('sha256', secret).update(body).digest('hex');
}

function makePushPayload() {
  return {
    ref: 'refs/heads/feature-branch',
    after: 'abc123def456',
    repository: {
      clone_url: 'https://github.com/example/repo.git',
    },
  };
}

// ─── Tests ────────────────────────────────────────────────────────────────────

test('GET /health returns 200 with { status: "ok" }', async () => {
  const res = await app.inject({ method: 'GET', url: '/health' });

  assert.equal(res.statusCode, 200);
  assert.deepEqual(JSON.parse(res.body), { status: 'ok' });
});

test('POST /webhook rejects request with missing signature (401)', async () => {
  const payload = makePushPayload();

  const res = await app.inject({
    method: 'POST',
    url: '/webhook',
    headers: {
      'content-type': 'application/json',
      'x-github-event': 'push',
    },
    body: JSON.stringify(payload),
  });

  assert.equal(res.statusCode, 401);
  const body = JSON.parse(res.body);
  assert.ok(body.error, 'response should include error message');
});

test('POST /webhook rejects request with invalid HMAC signature (401)', async () => {
  const payload = makePushPayload();
  const bodyStr = JSON.stringify(payload);
  const badSig = makeSignature(bodyStr, 'wrong-secret');

  const res = await app.inject({
    method: 'POST',
    url: '/webhook',
    headers: {
      'content-type': 'application/json',
      'x-github-event': 'push',
      'x-hub-signature-256': badSig,
    },
    body: bodyStr,
  });

  assert.equal(res.statusCode, 401);
  const body = JSON.parse(res.body);
  assert.ok(body.error);
});

test('POST /webhook accepts valid push with correct HMAC and returns accepted + sha + isMain', async () => {
  const payload = makePushPayload();
  const bodyStr = JSON.stringify(payload);
  const sig = makeSignature(bodyStr);

  const res = await app.inject({
    method: 'POST',
    url: '/webhook',
    headers: {
      'content-type': 'application/json',
      'x-github-event': 'push',
      'x-hub-signature-256': sig,
    },
    body: bodyStr,
  });

  assert.equal(res.statusCode, 200);
  const body = JSON.parse(res.body);
  assert.equal(body.accepted, true);
  assert.equal(body.sha, 'abc123def456');
  assert.equal(body.isMain, false); // refs/heads/feature-branch is not main
});

test('POST /webhook sets isMain=true for refs/heads/main push', async () => {
  const payload = { ...makePushPayload(), ref: 'refs/heads/main' };
  const bodyStr = JSON.stringify(payload);
  const sig = makeSignature(bodyStr);

  const res = await app.inject({
    method: 'POST',
    url: '/webhook',
    headers: {
      'content-type': 'application/json',
      'x-github-event': 'push',
      'x-hub-signature-256': sig,
    },
    body: bodyStr,
  });

  assert.equal(res.statusCode, 200);
  const body = JSON.parse(res.body);
  assert.equal(body.accepted, true);
  assert.equal(body.isMain, true);
});

test('verifySignature returns true for a correctly signed body', () => {
  const body = '{"hello":"world"}';
  const sig = makeSignature(body);
  assert.equal(verifySignature(body, sig), true);
});

test('verifySignature returns false for a tampered body', () => {
  const body = '{"hello":"world"}';
  const sig = makeSignature(body);
  assert.equal(verifySignature('{"hello":"tampered"}', sig), false);
});

test('verifySignature returns false for wrong secret', () => {
  const body = '{"hello":"world"}';
  const sig = makeSignature(body, 'other-secret');
  assert.equal(verifySignature(body, sig), false);
});
