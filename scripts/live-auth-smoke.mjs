#!/usr/bin/env node

import {
  buildSqlPipelineUrl,
  buildSqlRequests,
  createApiClient,
  normalizeSqlResult,
} from './bunny-cli-next.mjs';

const APPS = [
  {
    key: 'fuel',
    label: 'Fuel',
    baseUrl: 'https://fuel.codyjo.com',
    dbName: 'fuel',
    resetCodeMode: 'plain',
    resetLookup: { table: 'password_resets', keyColumn: 'email', codeColumn: 'code' },
    legacyRegisterDob: '1990-01-01',
  },
  {
    key: 'selah',
    label: 'Selah',
    baseUrl: 'https://www.selahscripture.com',
    dbName: 'selah',
    resetCodeMode: 'hashed',
    resetLookup: { table: 'password_resets', keyColumn: 'email', codeColumn: 'code' },
  },
  {
    key: 'certstudy',
    label: 'CertStudy',
    baseUrl: 'https://study.codyjo.com',
    dbName: 'certstudy',
    resetCodeMode: 'plain',
    resetLookup: { table: 'password_resets', keyColumn: 'email', codeColumn: 'code' },
  },
  {
    key: 'tnbm',
    label: 'The New Beautiful Me',
    baseUrl: 'https://thenewbeautifulme.com',
    dbName: 'tnbm',
    resetCodeMode: 'plain',
    resetLookup: { table: 'reset_tokens', keyColumn: 'user_id', codeColumn: 'token' },
  },
  {
    key: 'cordivent',
    label: 'Cordivent',
    baseUrl: 'https://www.cordivent.com',
    dbName: 'cordivent',
    resetCodeMode: 'plain',
    resetLookup: { table: 'password_resets', keyColumn: 'email', codeColumn: 'code' },
  },
];

const DEFAULT_TIMEOUT_MS = 15000;
const PASSWORD = 'SmokePass123!';
const RESET_PASSWORD = 'ResetPass123!';
const PRIVACY_POLICY_VERSION = '2026-03';

function parseArgs(argv) {
  const result = {
    app: null,
    allowPartial: true,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];
    if (value === '--app') {
      result.app = argv[index + 1] || null;
      index += 1;
      continue;
    }
    if (value === '--no-allow-partial') {
      result.allowPartial = false;
      continue;
    }
    throw new Error(`Unknown argument: ${value}`);
  }

  return result;
}

function buildEmail(appKey) {
  const suffix = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  return `live-auth-${appKey}-${suffix}@codyjo.com`;
}

function buildRegisterPayload(appKey) {
  const email = buildEmail(appKey);
  return {
    email,
    name: `Live Smoke ${appKey}`,
    password: PASSWORD,
    consent: true,
    ageConfirmed16Plus: true,
    consentTimestamp: new Date().toISOString(),
    privacyPolicyVersion: PRIVACY_POLICY_VERSION,
  };
}

async function requestJson(url, { method = 'GET', body, headers = {}, timeoutMs = DEFAULT_TIMEOUT_MS } = {}) {
  let lastError;
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      const response = await fetch(url, {
        method,
        headers: {
          Accept: 'application/json',
          ...(body ? { 'Content-Type': 'application/json' } : {}),
          ...headers,
        },
        body: body ? JSON.stringify(body) : undefined,
        signal: AbortSignal.timeout(timeoutMs),
      });
      const text = await response.text();
      let data = null;
      try {
        data = text ? JSON.parse(text) : null;
      } catch {
        data = text;
      }
      return { status: response.status, ok: response.ok, data, text };
    } catch (error) {
      lastError = error;
      if (attempt === 3) break;
      await new Promise((resolve) => setTimeout(resolve, 500 * attempt));
    }
  }
  throw lastError instanceof Error ? lastError : new Error(String(lastError));
}

async function getDatabase(client, dbName) {
  const data = await client.dbGet('/v1/databases');
  const databases = data.databases || data.items || [];
  const database = databases.find((item) => item.name === dbName || item.id === dbName);
  if (!database) {
    throw new Error(`Database not found: ${dbName}`);
  }
  return database;
}

async function createDatabaseToken(client, databaseId) {
  const response = await client.dbPut(`/v2/databases/${databaseId}/auth/generate`, { authorization: 'full-access' });
  if (!response?.token) {
    throw new Error(`Bunny did not return a DB token for ${databaseId}`);
  }
  return response.token;
}

async function runSql(url, token, sql, args = []) {
  const pipelineUrl = buildSqlPipelineUrl(url);
  const response = await fetch(pipelineUrl, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${String(token).replace(/^Bearer\s+/i, '')}`,
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify({
      requests: buildSqlRequests(sql, JSON.stringify(args)),
    }),
    signal: AbortSignal.timeout(DEFAULT_TIMEOUT_MS),
  });
  const text = await response.text();
  if (!response.ok) {
    throw new Error(`SQL request failed: HTTP ${response.status} ${text}`);
  }
  const parsed = JSON.parse(text);
  return normalizeSqlResult(parsed.results?.[0]);
}

function assertStatus(step, response, expectedStatus) {
  if (response.status !== expectedStatus) {
    throw new Error(`${step} expected HTTP ${expectedStatus}, got ${response.status}: ${JSON.stringify(response.data)}`);
  }
}

function assertHasToken(step, response) {
  if (!response.data?.token) {
    throw new Error(`${step} did not return a token: ${JSON.stringify(response.data)}`);
  }
}

async function runAppSmoke(client, app) {
  const result = {
    app: app.key,
    label: app.label,
    baseUrl: app.baseUrl,
    resetMode: app.resetCodeMode,
    status: 'passed',
    steps: [],
    notes: [],
  };

  const registerPayload = buildRegisterPayload(app.key);
  const loginPayload = { email: registerPayload.email, password: PASSWORD };

  const health = await requestJson(`${app.baseUrl}/health`);
  assertStatus('health', health, 200);
  result.steps.push({ step: 'health', status: health.status });

  let register = await requestJson(`${app.baseUrl}/api/auth/register`, {
    method: 'POST',
    body: registerPayload,
  });
  if (
    register.status === 400
    && typeof register.data?.error === 'string'
    && /date of birth is required/i.test(register.data.error)
    && app.legacyRegisterDob
  ) {
    const legacyPayload = { ...registerPayload, dob: app.legacyRegisterDob };
    register = await requestJson(`${app.baseUrl}/api/auth/register`, {
      method: 'POST',
      body: legacyPayload,
    });
    result.notes.push('Live registration still requires legacy DOB input. This app has not fully deployed the 16+ confirmation contract yet.');
  }
  assertStatus('register', register, 200);
  assertHasToken('register', register);
  result.steps.push({ step: 'register', status: register.status });

  const login = await requestJson(`${app.baseUrl}/api/auth/login`, {
    method: 'POST',
    body: loginPayload,
  });
  assertStatus('login', login, 200);
  assertHasToken('login', login);
  result.steps.push({ step: 'login', status: login.status });

  const forgot = await requestJson(`${app.baseUrl}/api/auth/forgot-password`, {
    method: 'POST',
    body: { email: registerPayload.email },
  });
  assertStatus('forgot-password', forgot, 200);
  result.steps.push({ step: 'forgot-password', status: forgot.status });

  const database = await getDatabase(client, app.dbName);
  const dbToken = await createDatabaseToken(client, database.id);
  let resetLookupValue = registerPayload.email;
  if (app.resetLookup.keyColumn === 'user_id') {
    const userRows = await runSql(
      database.url,
      dbToken,
      'SELECT id FROM users WHERE email = ? ORDER BY created_at DESC LIMIT 1',
      [registerPayload.email],
    );
    resetLookupValue = userRows.rows?.[0]?.id;
    if (!resetLookupValue) {
      throw new Error('Registered user row not found in live DB after registration');
    }
  }

  if (app.resetCodeMode === 'plain') {
    const resetRows = await runSql(
      database.url,
      dbToken,
      `SELECT ${app.resetLookup.codeColumn} AS code, attempts, expires_at FROM ${app.resetLookup.table} WHERE ${app.resetLookup.keyColumn} = ? ORDER BY created_at DESC LIMIT 1`,
      [resetLookupValue],
    );
    const resetCode = resetRows.rows?.[0]?.code;
    if (!resetCode) {
      throw new Error('No reset code row found after forgot-password');
    }

    const reset = await requestJson(`${app.baseUrl}/api/auth/reset-password`, {
      method: 'POST',
      body: {
        email: registerPayload.email,
        code: resetCode,
        newPassword: RESET_PASSWORD,
      },
    });
    assertStatus('reset-password', reset, 200);
    result.steps.push({ step: 'reset-password', status: reset.status });

    const loginAfterReset = await requestJson(`${app.baseUrl}/api/auth/login`, {
      method: 'POST',
      body: { email: registerPayload.email, password: RESET_PASSWORD },
    });
    assertStatus('login-after-reset', loginAfterReset, 200);
    assertHasToken('login-after-reset', loginAfterReset);
    result.steps.push({ step: 'login-after-reset', status: loginAfterReset.status });
  } else {
    const resetRows = await runSql(
      database.url,
      dbToken,
      `SELECT ${app.resetLookup.codeColumn} AS code, code_salt, attempts, expires_at FROM ${app.resetLookup.table} WHERE ${app.resetLookup.keyColumn} = ? ORDER BY created_at DESC LIMIT 1`,
      [resetLookupValue],
    );
    if (!resetRows.rows?.[0]?.code) {
      throw new Error('No hashed reset code row found after forgot-password');
    }

    result.status = 'partial';
    result.notes.push(
      'Forgot-password created a live reset row, but reset completion was not automated because this app hashes reset codes before storage. Full live reset for this app requires inbox or Postal message retrieval.',
    );
  }

  return result;
}

async function main() {
  const { app: onlyApp, allowPartial } = parseArgs(process.argv.slice(2));
  const apps = onlyApp ? APPS.filter((item) => item.key === onlyApp) : APPS;
  if (apps.length === 0) {
    throw new Error(`Unknown app: ${onlyApp}`);
  }

  const client = createApiClient();
  const results = [];
  let failed = false;

  for (const app of apps) {
    try {
      const result = await runAppSmoke(client, app);
      if (result.status === 'partial' && !allowPartial) {
        failed = true;
      }
      results.push(result);
    } catch (error) {
      failed = true;
      results.push({
        app: app.key,
        label: app.label,
        baseUrl: app.baseUrl,
        resetMode: app.resetCodeMode,
        status: 'failed',
        error: error instanceof Error ? error.message : String(error),
      });
    }
  }

  process.stdout.write(`${JSON.stringify({ generatedAt: new Date().toISOString(), results }, null, 2)}\n`);
  process.exit(failed ? 1 : 0);
}

main().catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
  process.exit(1);
});
