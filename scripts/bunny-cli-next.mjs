#!/usr/bin/env node

import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, resolve } from 'path';
import { createHash } from 'crypto';

const __filename = fileURLToPath(import.meta.url);
const CONFIG_PATH = resolve(process.env.HOME || '', '.config/bunnynet.json');
const API_BASE = 'https://api.bunny.net';
const DATABASE_API_BASE = 'https://api.bunny.net/database';
const DATABASE_PRIVATE_SPEC_URL = 'https://api.bunny.net/database/docs/private/api.json';
const DEFAULT_SPEC_CACHE_PATH = resolve(process.env.HOME || '', '.cache/bunny-cli/bunny-database-private-api.json');

class CliError extends Error {}

function fail(message) {
  throw new CliError(message);
}

function isDirectExecution() {
  return process.argv[1] && resolve(process.argv[1]) === __filename;
}

function loadConfig(configPath = CONFIG_PATH) {
  if (!existsSync(configPath)) return {};
  try {
    return JSON.parse(readFileSync(configPath, 'utf8'));
  } catch (error) {
    throw new CliError(`Failed to parse ${configPath}: ${error.message}`);
  }
}

function getApiKey({ env = process.env, config = loadConfig() } = {}) {
  return env.BUNNY_API_KEY || config.profiles?.default?.api_key || null;
}

function getDatabaseAccessKey({ env = process.env, config = loadConfig(), apiKey = getApiKey({ env, config }) } = {}) {
  return env.BUNNY_DB_ACCESS_KEY || config.profiles?.default?.db_access_key || apiKey || null;
}

function getDatabaseBearerToken({ env = process.env, config = loadConfig() } = {}) {
  return env.BUNNY_DB_BEARER_TOKEN || config.profiles?.default?.db_bearer_token || null;
}

function getDatabaseSpecCachePath({ env = process.env, config = loadConfig() } = {}) {
  return env.BUNNY_DB_SPEC_CACHE || config.profiles?.default?.db_spec_cache || DEFAULT_SPEC_CACHE_PATH;
}

function parseCsv(value) {
  return String(value || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

function pad(value, width) {
  return String(value ?? '').padEnd(width);
}

function parseEnvText(text) {
  const variables = [];
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;
    const offset = line.indexOf('=');
    if (offset === -1) fail(`Invalid env line: ${rawLine}`);
    const name = line.slice(0, offset).trim();
    let value = line.slice(offset + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    variables.push({ name, value });
  }
  return variables;
}

function loadEnvFile(file) {
  const content = readFileSync(resolve(file), 'utf8');
  if (file.endsWith('.json')) {
    return Object.entries(JSON.parse(content)).map(([name, value]) => ({ name, value: String(value) }));
  }
  return parseEnvText(content);
}

function dedupeEnvVars(variables) {
  const map = new Map();
  for (const item of variables) {
    map.set(item.name, { name: item.name, value: String(item.value ?? '') });
  }
  return [...map.values()].sort((a, b) => a.name.localeCompare(b.name));
}

function mergeEnvVars(existing, incoming) {
  return dedupeEnvVars([...(existing || []), ...(incoming || [])]);
}

function removeEnvVar(existing, key) {
  return (existing || []).filter((item) => item.name !== key);
}

function parseImageRef(value) {
  if (!value) fail('Image reference is required.');
  const slash = value.indexOf('/');
  const colon = value.lastIndexOf(':');
  if (slash === -1 || colon === -1 || colon < slash) {
    fail(`Expected image reference in namespace/name:tag format, got: ${value}`);
  }
  return {
    imageNamespace: value.slice(0, slash),
    imageName: value.slice(slash + 1, colon),
    imageTag: value.slice(colon + 1),
  };
}

function normalizeEndpoints(endpoints) {
  return (endpoints || []).map((endpoint) => {
    const type = String(endpoint.type || '').toLowerCase();
    const normalized = {
      displayName: endpoint.displayName,
      type,
    };

    if (type === 'cdn') {
      normalized.cdn = {
        portMappings: endpoint.cdn?.portMappings || endpoint.portMappings || [],
      };
      if (endpoint.cdn?.stickySessions ?? endpoint.stickySessions) {
        normalized.cdn.stickySessions = endpoint.cdn?.stickySessions || endpoint.stickySessions;
      }
      if (endpoint.cdn?.pullZoneId ?? endpoint.pullZoneId) {
        normalized.cdn.pullZoneId = endpoint.cdn?.pullZoneId || endpoint.pullZoneId;
      }
    } else if (type === 'anycast') {
      normalized.anycast = {
        portMappings: endpoint.anycast?.portMappings || endpoint.portMappings || [],
      };
    } else {
      fail(`Unsupported endpoint type: ${endpoint.type}`);
    }

    return normalized;
  });
}

function buildTemplatePatch(template = {}, overrides = {}) {
  const payload = {
    name: overrides.name ?? template.name,
    imageName: overrides.imageName ?? template.imageName,
    imageNamespace: overrides.imageNamespace ?? template.imageNamespace,
    imageTag: overrides.imageTag ?? template.imageTag,
    imagePullPolicy: overrides.imagePullPolicy ?? template.imagePullPolicy ?? 'always',
    environmentVariables: overrides.environmentVariables ?? dedupeEnvVars(template.environmentVariables || []),
    endpoints: overrides.endpoints ?? normalizeEndpoints(template.endpoints),
  };

  const imageRegistryId = overrides.imageRegistryId ?? template.imageRegistryId;
  const entryPoint = overrides.entryPoint ?? template.entryPoint;
  const volumeMounts = overrides.volumeMounts ?? template.volumeMounts;
  if (template.id) payload.id = template.id;
  if (template.packageId) payload.packageId = template.packageId;
  if (imageRegistryId) payload.imageRegistryId = imageRegistryId;
  if (entryPoint) payload.entryPoint = entryPoint;
  if (volumeMounts) payload.volumeMounts = volumeMounts;

  return payload;
}

function buildAppSpec(app) {
  const templates = (app.containerTemplates || []).map((template) => ({
    id: template.id,
    name: template.name,
    image: `${template.imageNamespace}/${template.imageName}:${template.imageTag}`,
    imageRegistryId: template.imageRegistryId || null,
    imagePullPolicy: template.imagePullPolicy || null,
    entryPoint: template.entryPoint || null,
    volumeMounts: template.volumeMounts || [],
    environmentVariables: dedupeEnvVars(template.environmentVariables || []),
    endpoints: normalizeEndpoints(template.endpoints),
  }));
  const template = templates[0];
  if (!template) fail(`App ${app.id} has no container templates.`);

  return {
    id: app.id,
    name: app.name,
    status: app.status,
    runtimeType: app.runtimeType || 'shared',
    autoScaling: app.autoScaling || null,
    regionSettings: app.regionSettings || null,
    displayEndpoint: app.displayEndpoint?.address || null,
    containerTemplate: template,
    containerTemplates: templates,
  };
}

function formatSpecSummary(spec) {
  return [
    `App:       ${spec.name} (${spec.id})`,
    `Status:    ${spec.status}`,
    `Endpoint:  ${spec.displayEndpoint || 'none'}`,
    `Image:     ${spec.containerTemplate.image}`,
    `Scale:     ${spec.autoScaling?.min ?? '?'}..${spec.autoScaling?.max ?? '?'}`,
    `Env vars:  ${spec.containerTemplate.environmentVariables.length}`,
    `Endpoints: ${spec.containerTemplate.endpoints.length}`,
  ].join('\n');
}

function getDatabaseUrlGroupId(db) {
  const match = db?.url?.match(/^libsql:\/\/([^-]+)-/);
  return match ? `group_${match[1]}` : null;
}

function buildSqlPipelineUrl(url) {
  if (!url) fail('Database URL is required to execute SQL.');
  if (url.startsWith('https://')) {
    return url.endsWith('/v2/pipeline') ? url : `${url.replace(/\/$/, '')}/v2/pipeline`;
  }
  if (url.startsWith('libsql://')) {
    return `${url.replace(/^libsql:\/\//, 'https://').replace(/\/$/, '')}/v2/pipeline`;
  }
  fail(`Unsupported database URL format: ${url}`);
}

function parseSqlApiValue(value) {
  if (value === null) return { type: 'null', value: null };
  if (typeof value === 'number' && Number.isInteger(value)) return { type: 'integer', value: String(value) };
  if (typeof value === 'number') return { type: 'float', value: String(value) };
  if (typeof value === 'boolean') return { type: 'integer', value: value ? '1' : '0' };
  return { type: 'text', value: String(value) };
}

function normalizeSqlResult(result) {
  const execute = result?.response?.result;
  if (!execute) return result;
  const columns = (execute.cols || []).map((column) => column.name);
  const rows = (execute.rows || []).map((row) => {
    const item = {};
    row.forEach((cell, index) => {
      item[columns[index] || `col_${index + 1}`] = cell?.value ?? null;
    });
    return item;
  });
  return {
    columns,
    rows,
    affected_row_count: execute.affected_row_count,
    last_insert_rowid: execute.last_insert_rowid,
    replication_index: execute.replication_index,
  };
}

function buildSqlRequests(sql, argsJson, { close = true } = {}) {
  const args = argsJson ? JSON.parse(argsJson).map((value) => parseSqlApiValue(value)) : undefined;
  const requests = [{
    type: 'execute',
    stmt: {
      sql,
      ...(args ? { args } : {}),
    },
  }];
  if (close) requests.push({ type: 'close' });
  return requests;
}

function sha256(text) {
  return createHash('sha256').update(text).digest('hex');
}

function readCachedDatabaseSpec(cachePath) {
  if (!cachePath || !existsSync(cachePath)) return null;
  const content = readFileSync(cachePath, 'utf8');
  const parsed = JSON.parse(content);
  const stat = statSync(cachePath);
  return {
    path: cachePath,
    fetchedAt: parsed.fetchedAt || stat.mtime.toISOString(),
    specUrl: parsed.specUrl || DATABASE_PRIVATE_SPEC_URL,
    hash: parsed.hash || sha256(JSON.stringify(parsed.spec || {})),
    spec: parsed.spec || parsed,
  };
}

async function fetchLatestDatabaseSpec(fetchImpl = fetch) {
  const response = await fetchImpl(DATABASE_PRIVATE_SPEC_URL, {
    headers: {
      Accept: 'application/json',
    },
  });
  const text = await response.text();
  if (!response.ok) {
    throw new CliError(`HTTP ${response.status} GET ${DATABASE_PRIVATE_SPEC_URL}\n${text}`);
  }
  let spec;
  try {
    spec = JSON.parse(text);
  } catch (error) {
    throw new CliError(`Failed to parse Bunny DB private API spec: ${error.message}`);
  }
  return {
    fetchedAt: new Date().toISOString(),
    specUrl: DATABASE_PRIVATE_SPEC_URL,
    hash: sha256(text),
    spec,
  };
}

function writeDatabaseSpecCache(cachePath, payload) {
  mkdirSync(dirname(cachePath), { recursive: true });
  writeFileSync(cachePath, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
}

function getOperationFromSpec(spec, method, path) {
  const specPath = spec?.paths?.[path];
  if (!specPath) return null;
  return specPath[String(method || '').toLowerCase()] || null;
}

function mapDatabasePathToSpecPath(path) {
  const cleaned = String(path || '').replace(/\?.*$/, '');
  if (/^\/v2\/databases\/[^/]+\/auth\/generate$/.test(cleaned)) return '/v2/databases/{db_id}/auth/generate';
  if (/^\/v2\/databases\/[^/]+\/auth\/revoke$/.test(cleaned)) return '/v2/databases/{db_id}/auth/revoke';
  if (/^\/v2\/databases\/[^/]+\/statistics$/.test(cleaned)) return '/v2/databases/{db_id}/statistics';
  if (/^\/v2\/databases\/[^/]+\/usage$/.test(cleaned)) return '/v2/databases/{db_id}/usage';
  if (/^\/v2\/databases\/[^/]+$/.test(cleaned)) return '/v2/databases/{db_id}';
  if (/^\/v1\/databases\/[^/]+\/auth\/invalidate$/.test(cleaned)) return '/v1/databases/{db_id}/auth/invalidate';
  if (/^\/v1\/databases\/[^/]+\/auth\/tokens$/.test(cleaned)) return '/v1/databases/{db_id}/auth/tokens';
  if (/^\/v1\/databases\/[^/]+\/fork$/.test(cleaned)) return '/v1/databases/{db_id}/fork';
  if (/^\/v1\/databases\/[^/]+\/list_versions$/.test(cleaned)) return '/v1/databases/{db_id}/list_versions';
  if (/^\/v1\/databases\/[^/]+\/restore$/.test(cleaned)) return '/v1/databases/{db_id}/restore';
  if (/^\/v1\/databases\/[^/]+$/.test(cleaned)) return '/v1/databases/{db_id}';
  if (/^\/v1\/groups\/[^/]+\/aggregated_usage$/.test(cleaned)) return '/v1/groups/{group_id}/aggregated_usage';
  if (/^\/v1\/groups\/[^/]+\/auth\/generate$/.test(cleaned)) return '/v1/groups/{group_id}/auth/generate';
  if (/^\/v1\/groups\/[^/]+\/stats$/.test(cleaned)) return '/v1/groups/{group_id}/stats';
  if (/^\/v1\/groups\/[^/]+$/.test(cleaned)) return '/v1/groups/{group_id}';
  return cleaned;
}

function buildDatabaseSpecDriftMessage({ method, path, cached, latest }) {
  const specPath = mapDatabasePathToSpecPath(path);
  const cachedOp = getOperationFromSpec(cached?.spec, method, specPath);
  const latestOp = getOperationFromSpec(latest?.spec, method, specPath);
  const lines = [];

  lines.push(`Checked Bunny DB private API spec: ${DATABASE_PRIVATE_SPEC_URL}`);
  if (cached?.path) {
    lines.push(`Local spec cache: ${cached.path}`);
  }
  if (!cached) {
    lines.push('No local spec cache was present before this failure.');
  } else if (cached.hash !== latest.hash) {
    lines.push(`Spec changed since cache: ${cached.hash.slice(0, 12)} -> ${latest.hash.slice(0, 12)}`);
  } else {
    lines.push(`Spec hash unchanged: ${latest.hash.slice(0, 12)}`);
  }

  if (!latest?.spec?.paths?.[specPath]) {
    lines.push(`Current spec no longer exposes path ${specPath}.`);
  } else if (!latestOp) {
    lines.push(`Current spec exposes ${specPath}, but not method ${String(method).toUpperCase()}.`);
  } else {
    lines.push(`Current spec still exposes ${String(method).toUpperCase()} ${specPath}.`);
  }

  if (cached && cachedOp && !latestOp) {
    lines.push('The cached spec had this operation but the latest spec does not. The CLI likely needs an update.');
  } else if (cached && !cachedOp && latestOp) {
    lines.push('The latest spec now exposes this operation even though the cached spec did not.');
  }

  return lines.join('\n');
}

async function refreshDatabaseSpecCache(client, { quiet = false } = {}) {
  const payload = await fetchLatestDatabaseSpec(client.fetchImpl);
  writeDatabaseSpecCache(client.dbSpecCachePath, payload);
  if (!quiet) {
    client.stdout.write(`${JSON.stringify({
      cachePath: client.dbSpecCachePath,
      fetchedAt: payload.fetchedAt,
      hash: payload.hash,
      pathCount: Object.keys(payload.spec?.paths || {}).length,
    }, null, 2)}\n`);
  }
  return payload;
}

async function showDatabaseSpecCacheStatus(client) {
  const cached = readCachedDatabaseSpec(client.dbSpecCachePath);
  if (!cached) {
    client.stdout.write(`${JSON.stringify({
      cachePath: client.dbSpecCachePath,
      present: false,
      specUrl: DATABASE_PRIVATE_SPEC_URL,
    }, null, 2)}\n`);
    return;
  }

  client.stdout.write(`${JSON.stringify({
    cachePath: cached.path,
    present: true,
    fetchedAt: cached.fetchedAt,
    hash: cached.hash,
    pathCount: Object.keys(cached.spec?.paths || {}).length,
    specUrl: cached.specUrl,
  }, null, 2)}\n`);
}

function shouldCheckDatabaseSpec(error, argv) {
  if (!(error instanceof CliError)) return false;
  if (argv[0] !== 'db') return false;
  return /HTTP \d+ .*\/(v1|v2)\//.test(error.message);
}

async function enrichDatabaseFailureWithSpec(client, argv, error) {
  if (!shouldCheckDatabaseSpec(error, argv)) return error;
  const match = error.message.match(/HTTP \d+ ([A-Z]+) (\/(?:v1|v2)\/[^\n]+)/);
  if (!match) return error;

  const [, method, path] = match;
  let cached = null;
  try {
    cached = readCachedDatabaseSpec(client.dbSpecCachePath);
  } catch {
    cached = null;
  }

  try {
    const latest = await refreshDatabaseSpecCache(client, { quiet: true });
    return new CliError(`${error.message}\n\n${buildDatabaseSpecDriftMessage({ method, path, cached, latest })}`);
  } catch (specError) {
    return new CliError(`${error.message}\n\nChecked Bunny DB private API spec, but refresh failed: ${specError.message}`);
  }
}

function createApiClient({
  env = process.env,
  config = loadConfig(),
  fetchImpl = fetch,
  stdout = process.stdout,
} = {}) {
  const apiKey = getApiKey({ env, config });
  if (!apiKey) fail('No Bunny API key found. Set BUNNY_API_KEY or configure ~/.config/bunnynet.json');

  const dbAccessKey = getDatabaseAccessKey({ env, config, apiKey });
  const dbBearerToken = getDatabaseBearerToken({ env, config });
  const dbSpecCachePath = getDatabaseSpecCachePath({ env, config });

  async function request(baseUrl, method, path, body, extraHeaders = {}) {
    const response = await fetchImpl(`${baseUrl}${path}`, {
      method,
      headers: {
        ...extraHeaders,
        'Content-Type': 'application/json',
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });

    const text = await response.text();
    if (!response.ok) {
      let details = text;
      try {
        details = JSON.stringify(JSON.parse(text), null, 2);
      } catch {
        // Keep text fallback.
      }
      throw new CliError(`HTTP ${response.status} ${method} ${path}\n${details}`);
    }
    if (!text) return null;
    try {
      return JSON.parse(text);
    } catch {
      return text;
    }
  }

  return {
    stdout,
    config,
    get: (path) => request(API_BASE, 'GET', path, undefined, { AccessKey: apiKey }),
    post: (path, body) => request(API_BASE, 'POST', path, body, { AccessKey: apiKey }),
    put: (path, body) => request(API_BASE, 'PUT', path, body, { AccessKey: apiKey }),
    patch: (path, body) => request(API_BASE, 'PATCH', path, body, { AccessKey: apiKey }),
    delete: (path) => request(API_BASE, 'DELETE', path, undefined, { AccessKey: apiKey }),
    dbGet: (path) => request(DATABASE_API_BASE, 'GET', path, undefined, { AccessKey: dbAccessKey }),
    dbPatch: (path, body) => request(DATABASE_API_BASE, 'PATCH', path, body, { AccessKey: dbAccessKey }),
    dbPut: (path, body) => request(DATABASE_API_BASE, 'PUT', path, body, { AccessKey: dbAccessKey }),
    dbPost: (path, body) => request(DATABASE_API_BASE, 'POST', path, body, { AccessKey: dbAccessKey }),
    dbDelete: (path) => request(DATABASE_API_BASE, 'DELETE', path, undefined, { AccessKey: dbAccessKey }),
    fetchImpl,
    dbBearerToken,
    dbSpecCachePath,
  };
}

async function getApp(client, id) {
  if (!id) fail('App id is required.');
  return client.get(`/mc/apps/${id}`);
}

async function patchApp(client, appId, payload) {
  return client.patch(`/mc/apps/${appId}`, payload);
}

async function listApps(client) {
  const data = await client.get('/mc/apps');
  const apps = data.items || [];
  if (apps.length === 0) {
    client.stdout.write('No apps found.\n');
    return;
  }

  client.stdout.write('\n');
  for (const app of apps) {
    client.stdout.write(`  ${pad(app.id, 12)} ${pad(app.name, 24)} ${pad(app.status, 12)} ${app.displayEndpoint?.address || ''}\n`);
  }
  client.stdout.write('\n');
}

async function showApp(client, id, { json = false } = {}) {
  const app = await getApp(client, id);
  const spec = buildAppSpec(app);
  if (json) {
    client.stdout.write(`${JSON.stringify(spec, null, 2)}\n`);
    return;
  }
  client.stdout.write(`\n${formatSpecSummary(spec)}\n\n`);
}

async function exportAppSpec(client, id) {
  const app = await getApp(client, id);
  client.stdout.write(`${JSON.stringify(buildAppSpec(app), null, 2)}\n`);
}

function normalizeDesiredContainerTemplates(desired) {
  if (Array.isArray(desired.containerTemplates) && desired.containerTemplates.length > 0) {
    return desired.containerTemplates;
  }
  if (desired.containerTemplate) {
    return [desired.containerTemplate];
  }
  fail('App spec must include containerTemplates or containerTemplate.');
}

async function createApp(client, name, imageRef, registryId, port = '3000', envFile) {
  if (!name) fail('Usage: app create <name> <namespace/name:tag> [registryId] [port] [envFile]');
  const image = parseImageRef(imageRef);
  const environmentVariables = envFile ? dedupeEnvVars(loadEnvFile(envFile)) : [];
  const payload = {
    name,
    runtimeType: 'shared',
    autoScaling: { min: 1, max: 3 },
    containerTemplates: [{
      name: 'app',
      imageName: image.imageName,
      imageNamespace: image.imageNamespace,
      imageTag: image.imageTag,
      imageRegistryId: registryId || undefined,
      imagePullPolicy: 'always',
      endpoints: [{
        displayName: `${name}-cdn`,
        type: 'cdn',
        cdn: { portMappings: [{ containerPort: Number(port) }] },
      }],
      environmentVariables,
    }],
  };

  const app = await client.post('/mc/apps', payload);
  client.stdout.write(`${JSON.stringify({
    id: app.id,
    name: app.name,
    status: app.status,
    endpoint: app.displayEndpoint?.address || null,
    envCount: app.containerTemplates?.[0]?.environmentVariables?.length || 0,
  }, null, 2)}\n`);
}

async function createAppFromSpec(client, file) {
  if (!file) fail('Usage: app create-spec <spec.json>');
  const desired = JSON.parse(readFileSync(resolve(file), 'utf8'));
  const desiredTemplates = normalizeDesiredContainerTemplates(desired);
  const payload = {
    name: desired.name,
    runtimeType: desired.runtimeType || 'shared',
    autoScaling: desired.autoScaling || { min: 1, max: 3 },
    containerTemplates: desiredTemplates.map((template) => {
      const image = template.image ? parseImageRef(template.image) : {};
      return buildTemplatePatch({}, {
        name: template.name,
        ...image,
        imageRegistryId: template.imageRegistryId,
        imagePullPolicy: template.imagePullPolicy || 'always',
        entryPoint: template.entryPoint || undefined,
        volumeMounts: template.volumeMounts || undefined,
        environmentVariables: dedupeEnvVars(template.environmentVariables || []),
        endpoints: normalizeEndpoints(template.endpoints || []),
      });
    }),
  };

  if (!payload.name) fail('App spec name is required.');
  if (desired.regionSettings) payload.regionSettings = desired.regionSettings;

  const app = await client.post('/mc/apps', payload);
  client.stdout.write(`${JSON.stringify({
    id: app.id,
    name: app.name,
    status: app.status,
    endpoint: app.displayEndpoint?.address || null,
    containerCount: app.containerTemplates?.length || 0,
  }, null, 2)}\n`);
}

async function deleteApp(client, id) {
  if (!id) fail('Usage: app delete <id>');
  const app = await getApp(client, id);
  await client.delete(`/mc/apps/${id}`);
  client.stdout.write(`Deleted ${app.name} (${id}).\n`);
}

async function updateAppImage(client, id, imageRef, registryId) {
  const app = await getApp(client, id);
  const template = app.containerTemplates?.[0];
  if (!template) fail(`App ${id} has no container templates.`);
  const image = parseImageRef(imageRef);

  await patchApp(client, id, {
    containerTemplates: [buildTemplatePatch(template, { ...image, imageRegistryId: registryId ?? template.imageRegistryId, imagePullPolicy: 'always' })],
  });

  client.stdout.write(`Updated ${app.name} to ${imageRef}. Bunny should redeploy the app.\n`);
}

async function scaleApp(client, id, minInstances, maxInstances) {
  const min = Number(minInstances);
  const max = Number(maxInstances);
  if (!Number.isInteger(min) || !Number.isInteger(max) || min < 0 || max < min) {
    fail('Scale values must be integers and satisfy 0 <= min <= max.');
  }

  const app = await getApp(client, id);
  await patchApp(client, id, {
    autoScaling: { min, max },
  });

  client.stdout.write(`Updated ${app.name} autoscaling to min=${min}, max=${max}.\n`);
}

async function syncEnv(client, id, file, { merge = false } = {}) {
  const incoming = loadEnvFile(file);
  const app = await getApp(client, id);
  const template = app.containerTemplates?.[0];
  if (!template) fail(`App ${id} has no container templates.`);

  const environmentVariables = merge
    ? mergeEnvVars(template.environmentVariables || [], incoming)
    : dedupeEnvVars(incoming);

  await patchApp(client, id, {
    containerTemplates: [buildTemplatePatch(template, { environmentVariables })],
  });

  client.stdout.write(`${merge ? 'Merged' : 'Synced'} ${incoming.length} env vars into ${app.name}. App will redeploy.\n`);
}

async function unsetEnv(client, id, key) {
  const app = await getApp(client, id);
  const template = app.containerTemplates?.[0];
  if (!template) fail(`App ${id} has no container templates.`);

  const environmentVariables = removeEnvVar(template.environmentVariables || [], key);
  await patchApp(client, id, {
    containerTemplates: [buildTemplatePatch(template, { environmentVariables })],
  });

  client.stdout.write(`Removed ${key} from ${app.name}. App will redeploy.\n`);
}

async function listEndpoints(client, id) {
  const app = await getApp(client, id);
  const endpoints = app.containerTemplates?.[0]?.endpoints || [];
  if (endpoints.length === 0) {
    client.stdout.write(`No endpoints found for ${app.name}.\n`);
    return;
  }

  client.stdout.write('\n');
  for (const endpoint of endpoints) {
    const ports = endpoint.cdn?.portMappings || endpoint.anycast?.portMappings || endpoint.portMappings || [];
    const publicHost = endpoint.publicHost || endpoint.publicUrl || '';
    client.stdout.write(`  ${pad(endpoint.displayName, 24)} ${pad(endpoint.type, 8)} ${pad(publicHost, 36)} ${JSON.stringify(ports)}\n`);
  }
  client.stdout.write('\n');
}

async function addCdnEndpoint(client, id, port = '3000', displayName) {
  const app = await getApp(client, id);
  const template = app.containerTemplates?.[0];
  if (!template) fail(`App ${id} has no container templates.`);

  const endpoints = normalizeEndpoints(template.endpoints);
  endpoints.push({
    displayName: displayName || `${app.name}-cdn-${port}`,
    type: 'cdn',
    cdn: { portMappings: [{ containerPort: Number(port) }] },
  });

  const result = await patchApp(client, id, {
    containerTemplates: [buildTemplatePatch(template, { endpoints })],
  });

  client.stdout.write(`Added CDN endpoint to ${app.name}: ${result.displayEndpoint?.address || 'pending'}\n`);
}

async function removeEndpoint(client, id, selector) {
  const app = await getApp(client, id);
  const template = app.containerTemplates?.[0];
  if (!template) fail(`App ${id} has no container templates.`);

  const existing = template.endpoints || [];
  const filtered = existing.filter((endpoint) =>
    endpoint.displayName !== selector
    && endpoint.publicHost !== selector
    && endpoint.publicUrl !== selector,
  );

  if (filtered.length === existing.length) {
    fail(`Endpoint not found: ${selector}`);
  }

  await patchApp(client, id, {
    containerTemplates: [buildTemplatePatch(template, { endpoints: normalizeEndpoints(filtered) })],
  });

  client.stdout.write(`Removed endpoint ${selector} from ${app.name}. App will redeploy.\n`);
}

async function applyAppSpec(client, id, file) {
  const desired = JSON.parse(readFileSync(resolve(file), 'utf8'));
  const app = await getApp(client, id);
  const existingTemplates = app.containerTemplates || [];
  if (existingTemplates.length === 0) fail(`App ${id} has no container templates.`);

  const specTemplates = normalizeDesiredContainerTemplates(desired);
  const templateById = new Map(existingTemplates.filter((template) => template.id).map((template) => [template.id, template]));
  const templateByName = new Map(existingTemplates.filter((template) => template.name).map((template) => [template.name, template]));
  const payload = {
    autoScaling: desired.autoScaling || app.autoScaling,
    containerTemplates: specTemplates.map((specTemplate, index) => {
      const template = templateById.get(specTemplate.id)
        || templateByName.get(specTemplate.name)
        || existingTemplates[index]
        || {};
      const image = specTemplate.image ? parseImageRef(specTemplate.image) : {};
      return buildTemplatePatch(template, {
        name: specTemplate.name ?? template.name,
        ...image,
        imageRegistryId: specTemplate.imageRegistryId ?? template.imageRegistryId,
        imagePullPolicy: specTemplate.imagePullPolicy ?? template.imagePullPolicy,
        entryPoint: specTemplate.entryPoint ?? template.entryPoint,
        volumeMounts: specTemplate.volumeMounts ?? template.volumeMounts,
        environmentVariables: specTemplate.environmentVariables ? dedupeEnvVars(specTemplate.environmentVariables) : dedupeEnvVars(template.environmentVariables || []),
        endpoints: specTemplate.endpoints ? normalizeEndpoints(specTemplate.endpoints) : normalizeEndpoints(template.endpoints),
      });
    }),
  };

  if (desired.regionSettings) {
    payload.regionSettings = desired.regionSettings;
  }

  await patchApp(client, id, payload);
  client.stdout.write(`Applied app spec from ${file} to ${app.name}.\n`);
}

async function waitForApp(client, id, timeoutSeconds = '300', intervalSeconds = '10', opts = {}) {
  const timeoutMs = Number(timeoutSeconds) * 1000;
  const intervalMs = Number(intervalSeconds) * 1000;
  const deadline = (opts.now || Date.now)() + timeoutMs;
  const sleep = opts.sleep || ((ms) => new Promise((resolvePromise) => setTimeout(resolvePromise, ms)));
  const fetchImpl = opts.fetchImpl || fetch;

  while ((opts.now || Date.now)() <= deadline) {
    const app = await getApp(client, id);
    const endpoint = app.displayEndpoint?.address;
    let health = null;

    if (endpoint) {
      try {
        const response = await fetchImpl(`https://${endpoint}/health`, { signal: AbortSignal.timeout(5000) });
        health = response.status;
      } catch {
        health = null;
      }
    }

    client.stdout.write(`status=${app.status} instances=${app.containerInstances?.length || 0} health=${health ?? 'n/a'}\n`);

    if (['running', 'active'].includes(String(app.status).toLowerCase()) && (!endpoint || (health && health < 400))) {
      client.stdout.write(`App ${app.name} is ready.\n`);
      return;
    }

    await sleep(intervalMs);
  }

  fail(`Timed out waiting for app ${id} to become healthy after ${timeoutSeconds}s.`);
}

async function listZones(client) {
  const data = await client.get('/dnszone?page=1&perPage=100');
  const zones = data.Items || data.items || data || [];
  if (zones.length === 0) {
    client.stdout.write('No DNS zones found.\n');
    return;
  }

  client.stdout.write('\n');
  for (const zone of zones) {
    client.stdout.write(`  ${pad(zone.Id || zone.id, 12)} ${pad(zone.Domain || zone.domain, 32)} records=${zone.RecordsCount ?? zone.recordsCount ?? '?'}\n`);
  }
  client.stdout.write('\n');
}

async function showZone(client, zoneId) {
  if (!zoneId) fail('Usage: dns zone <zoneId>');
  const zone = await client.get(`/dnszone/${zoneId}`);
  client.stdout.write(`${JSON.stringify(zone, null, 2)}\n`);
}

async function getZoneRecords(client, zoneId) {
  if (!zoneId) fail('Usage: dns records <zoneId>');
  const zone = await client.get(`/dnszone/${zoneId}`);
  return {
    zone,
    records: zone.Records || zone.records || [],
  };
}

async function listRecords(client, zoneId) {
  const { zone, records } = await getZoneRecords(client, zoneId);
  const types = {
    0: 'A',
    1: 'AAAA',
    2: 'CNAME',
    3: 'TXT',
    4: 'MX',
    5: 'REDIRECT',
    6: 'FLATTEN',
    7: 'PULLZONE',
    8: 'SRV',
    9: 'CAA',
    12: 'NS',
  };

  client.stdout.write(`\nZone: ${zone.Domain || zone.domain} (${zoneId})\n\n`);
  for (const record of records) {
    const type = types[record.Type ?? record.type] || String(record.Type ?? record.type);
    client.stdout.write(`  ${pad(record.Id || record.id, 12)} ${pad(type, 8)} ${pad(record.Name || record.name || '@', 28)} ${pad((record.Value || record.value || '').slice(0, 60), 60)} ttl=${record.Ttl || record.ttl || ''}\n`);
  }
  client.stdout.write('\n');
}

async function setDnsRecord(client, zoneId, name, type, value, ttl = '300') {
  if (!zoneId || !name || !type || value === undefined) {
    fail('Usage: dns set <zoneId> <name> <type> <value> [ttl]');
  }

  const typeMap = { A: 0, AAAA: 1, CNAME: 2, TXT: 3, MX: 4, REDIRECT: 5, FLATTEN: 6, PULLZONE: 7 };
  const typeNum = typeMap[String(type).toUpperCase()] ?? Number(type);
  if (!Number.isInteger(typeNum)) fail(`Unsupported DNS record type: ${type}`);

  const { records } = await getZoneRecords(client, zoneId);
  const existing = records.find((record) =>
    (record.Name || record.name) === name
    && Number(record.Type ?? record.type) === typeNum,
  );

  const parsedTtl = Number(ttl);
  const body = typeNum === 7
    ? { PullZoneId: Number(value), Ttl: parsedTtl, AutoSslIssuance: true }
    : { Value: value, Ttl: parsedTtl };

  if (existing) {
    const recordId = existing.Id || existing.id;
    await client.post(`/dnszone/${zoneId}/records/${recordId}`, {
      ...body,
      Id: recordId,
      Name: name,
      Type: typeNum,
    });
    client.stdout.write(`Updated ${type} ${name} -> ${value} (ttl=${parsedTtl}).\n`);
    return;
  }

  await client.put(`/dnszone/${zoneId}/records`, {
    Type: typeNum,
    Name: name,
    ...body,
  });
  client.stdout.write(`Created ${type} ${name} -> ${value} (ttl=${parsedTtl}).\n`);
}

async function setPullZoneRecord(client, zoneId, name, pullZoneId, ttl = '60') {
  await setDnsRecord(client, zoneId, name, 'PULLZONE', pullZoneId, ttl);
}

async function deleteDnsRecord(client, zoneId, recordId) {
  if (!zoneId || !recordId) fail('Usage: dns delete <zoneId> <recordId>');
  await client.delete(`/dnszone/${zoneId}/records/${recordId}`);
  client.stdout.write(`Deleted DNS record ${recordId} from zone ${zoneId}.\n`);
}

async function listPullZones(client) {
  const data = await client.get('/pullzone?page=1&perPage=100');
  const zones = data.Items || data.items || data || [];
  if (zones.length === 0) {
    client.stdout.write('No pull zones found.\n');
    return;
  }

  client.stdout.write('\n');
  for (const zone of zones) {
    const hostnames = (zone.Hostnames || zone.hostnames || []).map((host) => host.Value || host.value).join(', ');
    client.stdout.write(`  ${pad(zone.Id || zone.id, 10)} ${pad(zone.Name || zone.name, 24)} ${pad(zone.OriginUrl || zone.originUrl, 42)} ${hostnames}\n`);
  }
  client.stdout.write('\n');
}

async function createPullZone(client, name, originUrl) {
  if (!name || !originUrl) fail('Usage: pz create <name> <originUrl>');
  const zone = await client.post('/pullzone', { Name: name, OriginUrl: originUrl });
  client.stdout.write(`${JSON.stringify({
    id: zone.Id || zone.id,
    name: zone.Name || zone.name,
    originUrl: zone.OriginUrl || zone.originUrl,
  }, null, 2)}\n`);
}

async function updatePullZoneOrigin(client, pullZoneId, originUrl) {
  if (!pullZoneId || !originUrl) fail('Usage: pz origin <pullZoneId> <originUrl>');
  const zone = await client.post(`/pullzone/${pullZoneId}`, { OriginUrl: originUrl });
  client.stdout.write(`Updated pull zone ${zone.Id || zone.id} origin to ${zone.OriginUrl || zone.originUrl}.\n`);
}

async function addPullZoneHostname(client, pullZoneId, hostname) {
  if (!pullZoneId || !hostname) fail('Usage: pz hostname <pullZoneId> <hostname>');
  await client.post(`/pullzone/${pullZoneId}/addHostname`, { Hostname: hostname });
  client.stdout.write(`Added hostname ${hostname} to pull zone ${pullZoneId}.\n`);
}

async function activatePullZoneSsl(client, pullZoneId, hostname) {
  if (!pullZoneId || !hostname) fail('Usage: pz ssl <pullZoneId> <hostname>');
  await client.get(`/pullzone/loadFreeCertificate?hostname=${encodeURIComponent(hostname)}`);
  await client.post(`/pullzone/${pullZoneId}/setForceSSL`, { Hostname: hostname, ForceSSL: true });
  client.stdout.write(`Activated SSL for ${hostname} on pull zone ${pullZoneId}.\n`);
}

async function purgePullZoneCache(client, pullZoneId) {
  if (!pullZoneId) fail('Usage: pz purge <pullZoneId>');
  await client.post(`/pullzone/${pullZoneId}/purgeCache`);
  client.stdout.write(`Purged cache for pull zone ${pullZoneId}.\n`);
}

async function healthCheck(client, url, { fetchImpl = fetch } = {}) {
  if (!url) fail('Usage: health <url>');
  const target = url.startsWith('http') ? url : `https://${url}`;
  const start = Date.now();
  try {
    const response = await fetchImpl(target, { signal: AbortSignal.timeout(10000) });
    const body = await response.text();
    client.stdout.write(`HTTP ${response.status} (${Date.now() - start}ms)\n`);
    client.stdout.write(`${body.slice(0, 200)}\n`);
  } catch (error) {
    fail(`Health check failed for ${target}: ${error.message}`);
  }
}

async function getAllDatabases(client) {
  const data = await client.dbGet('/v1/databases');
  return data.databases || data.items || [];
}

async function getDatabaseConfig(client) {
  return client.dbGet('/v1/config');
}

function formatIsoDate(value) {
  if (!value) fail('A date/time value is required.');
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    fail(`Invalid date/time value: ${value}`);
  }
  return date.toISOString();
}

async function listDatabases(client) {
  printExperimentalWarning(client);
  const databases = await getAllDatabases(client);
  if (databases.length === 0) {
    client.stdout.write('No Bunny databases found.\n');
    return;
  }

  client.stdout.write('\n');
  for (const database of databases) {
    client.stdout.write(`  ${pad(database.id, 28)} ${pad(database.name, 22)} ${pad(database.group_id || getDatabaseUrlGroupId(database) || '-', 34)} ${database.url || ''}\n`);
  }
  client.stdout.write('\n');
}

async function showDatabaseLimits(client) {
  printExperimentalWarning(client);
  const limits = await client.dbGet('/v1/config/limits');
  client.stdout.write(`${JSON.stringify(limits, null, 2)}\n`);
}

async function resolveDatabaseIdentifier(client, identifier) {
  if (!identifier) fail('Database identifier is required.');
  const databases = await getAllDatabases(client);
  const database = databases.find((db) =>
    db.id === identifier
    || db.name === identifier
    || db.group_id === identifier
    || db.url === identifier
    || getDatabaseUrlGroupId(db) === identifier
  );
  if (!database) fail(`Database not found for identifier: ${identifier}`);
  return database;
}

async function getDatabaseDetails(client, identifier) {
  const database = await resolveDatabaseIdentifier(client, identifier);
  const response = await client.dbGet(`/v2/databases/${database.id}`);
  return response.db || response;
}

async function getDatabaseGroup(client, identifier) {
  const database = await resolveDatabaseIdentifier(client, identifier);
  const groupId = database.group_id || getDatabaseUrlGroupId(database);
  if (!groupId) fail(`Could not resolve a database group for ${identifier}`);
  const response = await client.dbGet(`/v1/groups/${groupId}`);
  return response.group || response;
}

async function showDatabaseGroup(client, identifier) {
  printExperimentalWarning(client);
  const group = await getDatabaseGroup(client, identifier);
  client.stdout.write(`${JSON.stringify(group, null, 2)}\n`);
}

function printExperimentalWarning(client) {
  client.stdout.write('Experimental Bunny Database control-plane command. Bunny warned these endpoints may change.\n');
}

async function showDatabaseSpec(client, identifier) {
  printExperimentalWarning(client);
  const [database, group] = await Promise.all([
    getDatabaseDetails(client, identifier),
    getDatabaseGroup(client, identifier),
  ]);
  client.stdout.write(`${JSON.stringify({ database, group }, null, 2)}\n`);
}

async function createDatabase(client, name, primaryRegion, storageRegion, replicaCsv = '') {
  printExperimentalWarning(client);
  if (!name) fail('Usage: db create <name> [primaryRegion] [storageRegion] [replicaCsv]');
  const config = await getDatabaseConfig(client);
  const resolvedPrimary = primaryRegion
    ? parseCsv(primaryRegion)
    : [config.primary_regions?.[0]?.id].filter(Boolean);
  const resolvedStorage = storageRegion || config.storage_region_available?.[0]?.id;
  if (resolvedPrimary.length === 0 || !resolvedStorage) {
    fail('Could not resolve default Bunny Database regions from /database/v1/config.');
  }

  const result = await client.dbPost('/v2/databases', {
    name,
    primary_regions: resolvedPrimary,
    replicas_regions: parseCsv(replicaCsv),
    storage_region: resolvedStorage,
  });
  const createdId = result.db_id || result.id;
  if (!createdId) {
    client.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
    fail('Database was created but Bunny did not return a database id.');
  }

  const database = await getDatabaseDetails(client, createdId);
  client.stdout.write(`${JSON.stringify(database, null, 2)}\n`);
}

async function generateDatabaseToken(client, identifier, authorization = 'full-access') {
  printExperimentalWarning(client);
  if (!['full-access', 'read-only'].includes(authorization)) {
    fail('Authorization must be full-access or read-only.');
  }
  const database = await resolveDatabaseIdentifier(client, identifier);
  const result = await client.dbPut(`/v2/databases/${database.id}/auth/generate`, { authorization });
  if (!result.token) {
    client.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
    fail('Token generation succeeded but Bunny did not return a token.');
  }
  client.stdout.write(`${result.token}\n`);
}

async function generateDatabaseGroupToken(client, identifier, authorization = 'full-access') {
  printExperimentalWarning(client);
  if (!['full-access', 'read-only'].includes(authorization)) {
    fail('Authorization must be full-access or read-only.');
  }
  const group = await getDatabaseGroup(client, identifier);
  const result = await client.dbPost(`/v1/groups/${group.id}/auth/generate`, { authorization });
  if (!result.token) {
    client.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
    fail('Group token generation succeeded but Bunny did not return a token.');
  }
  client.stdout.write(`${result.token}\n`);
}

async function deleteDatabase(client, identifier) {
  printExperimentalWarning(client);
  const database = await resolveDatabaseIdentifier(client, identifier);
  await client.dbDelete(`/v2/databases/${database.id}`);
  client.stdout.write(`Deleted database ${database.name} (${database.id}).\n`);
}

async function setDatabaseRegions(client, identifier, primaryCsv, storageRegion, replicaCsv = '') {
  printExperimentalWarning(client);
  const group = await getDatabaseGroup(client, identifier);
  const payload = {
    primary_regions: primaryCsv === '-' ? (group.primary_regions || []) : parseCsv(primaryCsv),
    storage_region: storageRegion === '-' ? group.storage_region : storageRegion,
    replicas_regions: replicaCsv === '-' ? (group.replicas_regions || []) : parseCsv(replicaCsv),
  };

  if (payload.primary_regions.length === 0) {
    fail('At least one primary region is required.');
  }
  if (!payload.storage_region) {
    fail('Storage region is required.');
  }

  const response = await client.dbPatch(`/v1/groups/${group.id}`, payload);
  client.stdout.write(`${JSON.stringify(response.group || response, null, 2)}\n`);
}

async function mutateReplicaRegion(client, identifier, region, action) {
  printExperimentalWarning(client);
  const group = await getDatabaseGroup(client, identifier);
  const replicas = new Set(group.replicas_regions || []);
  if (action === 'add') replicas.add(region);
  if (action === 'remove') replicas.delete(region);

  const response = await client.dbPatch(`/v1/groups/${group.id}`, {
    storage_region: group.storage_region,
    primary_regions: group.primary_regions || [],
    replicas_regions: [...replicas],
  });
  client.stdout.write(`${JSON.stringify(response.group || response, null, 2)}\n`);
}

async function mirrorDatabaseRegions(client, sourceIdentifier, targetIdentifiers) {
  printExperimentalWarning(client);
  if (!sourceIdentifier || targetIdentifiers.length === 0) {
    fail('Usage: db mirror <sourceIdOrName> <targetIdOrName...>');
  }

  const sourceGroup = await getDatabaseGroup(client, sourceIdentifier);
  const payload = {
    storage_region: sourceGroup.storage_region,
    primary_regions: sourceGroup.primary_regions || [],
    replicas_regions: sourceGroup.replicas_regions || [],
  };

  const results = [];
  for (const targetIdentifier of targetIdentifiers) {
    const targetGroup = await getDatabaseGroup(client, targetIdentifier);
    const response = await client.dbPatch(`/v1/groups/${targetGroup.id}`, payload);
    results.push({
      target: targetIdentifier,
      group: response.group || response,
    });
  }

  client.stdout.write(`${JSON.stringify({
    source: sourceIdentifier,
    mirrored: results,
  }, null, 2)}\n`);
}

async function runDatabaseSql(client, identifier, sql, argsJson, { normalize = true } = {}) {
  const database = await getDatabaseDetails(client, identifier);
  const bearer = client.dbBearerToken;
  if (!bearer) {
    fail('Database SQL execution requires BUNNY_DB_BEARER_TOKEN or config.profiles.default.db_bearer_token.');
  }

  const pipelineUrl = buildSqlPipelineUrl(database.url);
  const response = await client.fetchImpl(pipelineUrl, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${bearer.replace(/^Bearer\s+/i, '')}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      requests: buildSqlRequests(sql, argsJson),
    }),
  });

  const text = await response.text();
  if (!response.ok) {
    throw new CliError(`HTTP ${response.status} POST ${pipelineUrl}\n${text}`);
  }
  const parsed = JSON.parse(text);
  client.stdout.write(`${JSON.stringify(normalize ? normalizeSqlResult(parsed.results?.[0]) : parsed, null, 2)}\n`);
}

async function runDatabaseBatch(client, identifier, file) {
  const database = await getDatabaseDetails(client, identifier);
  const bearer = client.dbBearerToken;
  if (!bearer) {
    fail('Database batch execution requires BUNNY_DB_BEARER_TOKEN or config.profiles.default.db_bearer_token.');
  }

  const pipelineUrl = buildSqlPipelineUrl(database.url);
  const requests = JSON.parse(readFileSync(resolve(file), 'utf8'));
  const response = await client.fetchImpl(pipelineUrl, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${bearer.replace(/^Bearer\s+/i, '')}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ requests }),
  });
  const text = await response.text();
  if (!response.ok) {
    throw new CliError(`HTTP ${response.status} POST ${pipelineUrl}\n${text}`);
  }
  client.stdout.write(`${JSON.stringify(JSON.parse(text), null, 2)}\n`);
}

async function listDatabaseTables(client, identifier) {
  await runDatabaseSql(client, identifier, "select name, type from sqlite_master where type in ('table','view') and name not like 'sqlite_%' order by type, name");
}

async function showDatabaseSchema(client, identifier, table) {
  const sql = table
    ? "select type, name, tbl_name, sql from sqlite_master where name = ? order by type, name"
    : "select type, name, tbl_name, sql from sqlite_master where name not like 'sqlite_%' order by type, name";
  await runDatabaseSql(client, identifier, sql, table ? JSON.stringify([table]) : undefined);
}

async function listDatabaseIndexes(client, identifier, table) {
  const sql = table
    ? "select name, tbl_name, sql from sqlite_master where type = 'index' and tbl_name = ? order by name"
    : "select name, tbl_name, sql from sqlite_master where type = 'index' and name not like 'sqlite_%' order by tbl_name, name";
  await runDatabaseSql(client, identifier, sql, table ? JSON.stringify([table]) : undefined);
}

async function showDatabasePragma(client, identifier, pragmaName) {
  if (!pragmaName) fail('Usage: db pragma <idOrName> <pragmaName>');
  await runDatabaseSql(client, identifier, `pragma ${pragmaName}`);
}

async function runDatabaseIntegrityCheck(client, identifier) {
  await runDatabaseSql(client, identifier, 'pragma integrity_check');
}

async function runDatabaseForeignKeyCheck(client, identifier) {
  await runDatabaseSql(client, identifier, 'pragma foreign_key_check');
}

async function dumpDatabaseSchema(client, identifier) {
  await runDatabaseSql(
    client,
    identifier,
    "select sql from sqlite_master where sql is not null and name not like 'sqlite_%' order by case type when 'table' then 0 when 'index' then 1 when 'trigger' then 2 else 3 end, name",
  );
}

async function runDatabaseDoctor(client, identifier) {
  const checks = [
    { name: 'integrity_check', sql: 'pragma integrity_check' },
    { name: 'foreign_keys', sql: 'pragma foreign_keys' },
    { name: 'journal_mode', sql: 'pragma journal_mode' },
    { name: 'tables', sql: "select count(*) as count from sqlite_master where type='table' and name not like 'sqlite_%'" },
    { name: 'indexes', sql: "select count(*) as count from sqlite_master where type='index' and name not like 'sqlite_%'" },
  ];

  const report = {};
  for (const check of checks) {
    const chunks = [];
    const scopedClient = { ...client, stdout: { write(chunk) { chunks.push(chunk); } } };
    await runDatabaseSql(scopedClient, identifier, check.sql);
    report[check.name] = JSON.parse(chunks.join(''));
  }
  client.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
}

async function listDatabaseVersions(client, identifier, limit = '20') {
  printExperimentalWarning(client);
  const database = await resolveDatabaseIdentifier(client, identifier);
  const result = await client.dbPost(`/v1/databases/${database.id}/list_versions`, {
    limit: Number(limit),
  });
  client.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
}

async function forkDatabase(client, identifier, name) {
  printExperimentalWarning(client);
  if (!name) fail('Usage: db fork <idOrName> <newName>');
  const database = await resolveDatabaseIdentifier(client, identifier);
  const result = await client.dbPost(`/v1/databases/${database.id}/fork`, { name });
  client.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
}

async function restoreDatabaseVersion(client, identifier, version) {
  printExperimentalWarning(client);
  if (!version) fail('Usage: db restore <idOrName> <version>');
  const database = await resolveDatabaseIdentifier(client, identifier);
  const result = await client.dbPost(`/v1/databases/${database.id}/restore`, { version });
  client.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
}

async function showDatabaseUsage(client, identifier, from, to) {
  const database = await resolveDatabaseIdentifier(client, identifier);
  const query = `from=${encodeURIComponent(formatIsoDate(from))}&to=${encodeURIComponent(formatIsoDate(to))}`;
  const result = await client.dbGet(`/v2/databases/${database.id}/usage?${query}`);
  client.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
}

async function showDatabaseStatistics(client, identifier, from, to) {
  const database = await resolveDatabaseIdentifier(client, identifier);
  const query = `from=${encodeURIComponent(formatIsoDate(from))}&to=${encodeURIComponent(formatIsoDate(to))}`;
  const result = await client.dbGet(`/v2/databases/${database.id}/statistics?${query}`);
  client.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
}

async function showGroupStatistics(client, identifier, from, to) {
  printExperimentalWarning(client);
  const group = await getDatabaseGroup(client, identifier);
  const query = `from=${encodeURIComponent(formatIsoDate(from))}&to=${encodeURIComponent(formatIsoDate(to))}`;
  const result = await client.dbGet(`/v1/groups/${group.id}/stats?${query}`);
  client.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
}

async function showActiveDatabaseUsage(client) {
  const result = await client.dbGet('/v2/databases/active_usage');
  client.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
}

function showHelp(stdout = process.stdout) {
  stdout.write(`
bunny-cli-next — Bunny app + database operator CLI

App commands:
  apps
  app <id>
  app create <name> <namespace/name:tag> [registryId] [port] [envFile]
  app create-spec <spec.json>
  app delete <id>
  app spec <id>
  app image <id> <namespace/name:tag> [registryId]
  app scale <id> <min> <max>
  app apply <id> <spec.json>

Env commands:
  env sync <id> <file>             Replace env vars from .env or .json
  env merge <id> <file>            Merge env vars from .env or .json
  env unset <id> <key>

Endpoint commands:
  endpoint list <id>
  endpoint cdn <id> [port] [name]
  endpoint remove <id> <nameOrHost>

DNS commands:
  dns zones
  dns zone <zoneId>
  dns records <zoneId>
  dns set <zoneId> <name> <type> <value> [ttl]
  dns pullzone <zoneId> <name> <pullZoneId> [ttl]
  dns delete <zoneId> <recordId>

Pull zone commands:
  pz list
  pz create <name> <originUrl>
  pz origin <pullZoneId> <originUrl>
  pz hostname <pullZoneId> <hostname>
  pz ssl <pullZoneId> <hostname>
  pz purge <pullZoneId>

Wait:
  wait <id> [timeoutSec] [intervalSec]

Utility:
  health <url>

Database commands:
  db list
  db limits
  db api status
  db api sync-spec
  db create <name> [primaryRegion] [storageRegion] [replicaCsv]
  db delete <idOrName>
  db token <idOrName> [full-access|read-only]
  db group-token <idOrName> [full-access|read-only]
  db group <idOrName>
  db mirror <sourceIdOrName> <targetIdOrName...>
  db spec <idOrName>
  db regions set <idOrName> <primaryCsv|-> <storageRegion|-> [replicaCsv|-]
  db replica add <idOrName> <region>
  db replica remove <idOrName> <region>
  db versions <idOrName> [limit]
  db fork <idOrName> <newName>
  db restore <idOrName> <version>
  db query <idOrName> <sql> [jsonArgs]
  db exec <idOrName> <sql> [jsonArgs]
  db batch <idOrName> <requests.json>
  db tables <idOrName>
  db schema <idOrName> [table]
  db indexes <idOrName> [table]
  db pragma <idOrName> <pragmaName>
  db integrity-check <idOrName>
  db fk-check <idOrName>
  db dump schema <idOrName>
  db doctor <idOrName>
  db usage <idOrName> <fromIso> <toIso>
  db stats <idOrName> <fromIso> <toIso>
  db group-stats <idOrName> <fromIso> <toIso>
  db active-usage
  db sql <idOrName> <sql> [jsonArgs]
  DB failures trigger a best-effort refresh of Bunny's private DB OpenAPI spec and report drift.
  Note: control-plane DB commands use undocumented preview endpoints and may drift.

`);
}

function buildOfficialBunnyArgs(argv) {
  return null;
}

async function runCli(argv = process.argv.slice(2), options = {}) {
  const stdout = options.stdout || process.stdout;
  if (argv.length === 0 || argv[0] === 'help' || argv[0] === '--help' || argv[0] === '-h') {
    showHelp(stdout);
    return 0;
  }

  const client = options.client || createApiClient({
    env: options.env || process.env,
    config: options.config || loadConfig(),
    fetchImpl: options.fetchImpl || fetch,
    stdout,
  });
  const officialArgs = !options.disableOfficialPassthrough ? buildOfficialBunnyArgs(argv) : null;

  if (officialArgs) {
    fail(`Official Bunny passthrough is disabled for this command: ${argv.join(' ')}`);
    return 0;
  }

  const [command, ...args] = argv;

  if (command === 'apps') {
    await listApps(client);
    return 0;
  }

  if (command === 'app') {
    if (args[0] === 'create') {
      await createApp(client, args[1], args[2], args[3], args[4] || '3000', args[5]);
      return 0;
    }
    if (args[0] === 'create-spec') {
      await createAppFromSpec(client, args[1]);
      return 0;
    }
    if (args[0] === 'delete') {
      await deleteApp(client, args[1]);
      return 0;
    }
    if (args[0] === 'spec') {
      await exportAppSpec(client, args[1]);
      return 0;
    }
    if (args[0] === 'image') {
      await updateAppImage(client, args[1], args[2], args[3]);
      return 0;
    }
    if (args[0] === 'scale') {
      await scaleApp(client, args[1], args[2], args[3]);
      return 0;
    }
    if (args[0] === 'apply') {
      await applyAppSpec(client, args[1], args[2]);
      return 0;
    }
    await showApp(client, args[0], { json: args.includes('--json') });
    return 0;
  }

  if (command === 'env') {
    if (args[0] === 'sync') {
      await syncEnv(client, args[1], args[2], { merge: false });
      return 0;
    }
    if (args[0] === 'merge') {
      await syncEnv(client, args[1], args[2], { merge: true });
      return 0;
    }
    if (args[0] === 'unset') {
      await unsetEnv(client, args[1], args[2]);
      return 0;
    }
  }

  if (command === 'endpoint') {
    if (args[0] === 'list') {
      await listEndpoints(client, args[1]);
      return 0;
    }
    if (args[0] === 'cdn') {
      await addCdnEndpoint(client, args[1], args[2] || '3000', args[3]);
      return 0;
    }
    if (args[0] === 'remove') {
      await removeEndpoint(client, args[1], args[2]);
      return 0;
    }
  }

  if (command === 'wait') {
    await waitForApp(client, args[0], args[1] || '300', args[2] || '10', options.waitOptions);
    return 0;
  }

  if (command === 'dns') {
    if (args[0] === 'zones') {
      await listZones(client);
      return 0;
    }
    if (args[0] === 'zone') {
      await showZone(client, args[1]);
      return 0;
    }
    if (args[0] === 'records') {
      await listRecords(client, args[1]);
      return 0;
    }
    if (args[0] === 'set') {
      await setDnsRecord(client, args[1], args[2], args[3], args[4], args[5] || '300');
      return 0;
    }
    if (args[0] === 'pullzone') {
      await setPullZoneRecord(client, args[1], args[2], args[3], args[4] || '60');
      return 0;
    }
    if (args[0] === 'delete') {
      await deleteDnsRecord(client, args[1], args[2]);
      return 0;
    }
  }

  if (command === 'pz') {
    if (args[0] === 'list') {
      await listPullZones(client);
      return 0;
    }
    if (args[0] === 'create') {
      await createPullZone(client, args[1], args[2]);
      return 0;
    }
    if (args[0] === 'origin') {
      await updatePullZoneOrigin(client, args[1], args[2]);
      return 0;
    }
    if (args[0] === 'hostname') {
      await addPullZoneHostname(client, args[1], args[2]);
      return 0;
    }
    if (args[0] === 'ssl') {
      await activatePullZoneSsl(client, args[1], args[2]);
      return 0;
    }
    if (args[0] === 'purge') {
      await purgePullZoneCache(client, args[1]);
      return 0;
    }
  }

  if (command === 'health') {
    await healthCheck(client, args[0], { fetchImpl: options.fetchImpl || fetch });
    return 0;
  }

  if (command === 'db') {
    try {
      if (args[0] === 'list') {
        await listDatabases(client);
        return 0;
      }
      if (args[0] === 'limits') {
        await showDatabaseLimits(client);
        return 0;
      }
      if (args[0] === 'api' && args[1] === 'status') {
        await showDatabaseSpecCacheStatus(client);
        return 0;
      }
      if (args[0] === 'api' && args[1] === 'sync-spec') {
        await refreshDatabaseSpecCache(client);
        return 0;
      }
      if (args[0] === 'create') {
        await createDatabase(client, args[1], args[2], args[3], args[4]);
        return 0;
      }
      if (args[0] === 'delete') {
        await deleteDatabase(client, args[1]);
        return 0;
      }
      if (args[0] === 'token') {
        await generateDatabaseToken(client, args[1], args[2] || 'full-access');
        return 0;
      }
      if (args[0] === 'group-token') {
        await generateDatabaseGroupToken(client, args[1], args[2] || 'full-access');
        return 0;
      }
      if (args[0] === 'group') {
        await showDatabaseGroup(client, args[1]);
        return 0;
      }
      if (args[0] === 'mirror') {
        await mirrorDatabaseRegions(client, args[1], args.slice(2));
        return 0;
      }
      if (args[0] === 'spec') {
        await showDatabaseSpec(client, args[1]);
        return 0;
      }
      if (args[0] === 'regions' && args[1] === 'set') {
        await setDatabaseRegions(client, args[2], args[3], args[4], args[5] || '');
        return 0;
      }
      if (args[0] === 'replica' && args[1] === 'add') {
        await mutateReplicaRegion(client, args[2], args[3], 'add');
        return 0;
      }
      if (args[0] === 'replica' && args[1] === 'remove') {
        await mutateReplicaRegion(client, args[2], args[3], 'remove');
        return 0;
      }
      if (args[0] === 'versions') {
        await listDatabaseVersions(client, args[1], args[2] || '20');
        return 0;
      }
      if (args[0] === 'fork') {
        await forkDatabase(client, args[1], args[2]);
        return 0;
      }
      if (args[0] === 'restore') {
        await restoreDatabaseVersion(client, args[1], args[2]);
        return 0;
      }
      if (args[0] === 'sql') {
        await runDatabaseSql(client, args[1], args[2], args[3]);
        return 0;
      }
      if (args[0] === 'query' || args[0] === 'exec') {
        await runDatabaseSql(client, args[1], args[2], args[3]);
        return 0;
      }
      if (args[0] === 'batch') {
        await runDatabaseBatch(client, args[1], args[2]);
        return 0;
      }
      if (args[0] === 'tables') {
        await listDatabaseTables(client, args[1]);
        return 0;
      }
      if (args[0] === 'schema') {
        await showDatabaseSchema(client, args[1], args[2]);
        return 0;
      }
      if (args[0] === 'indexes') {
        await listDatabaseIndexes(client, args[1], args[2]);
        return 0;
      }
      if (args[0] === 'pragma') {
        await showDatabasePragma(client, args[1], args[2]);
        return 0;
      }
      if (args[0] === 'integrity-check') {
        await runDatabaseIntegrityCheck(client, args[1]);
        return 0;
      }
      if (args[0] === 'fk-check') {
        await runDatabaseForeignKeyCheck(client, args[1]);
        return 0;
      }
      if (args[0] === 'dump' && args[1] === 'schema') {
        await dumpDatabaseSchema(client, args[2]);
        return 0;
      }
      if (args[0] === 'doctor') {
        await runDatabaseDoctor(client, args[1]);
        return 0;
      }
      if (args[0] === 'usage') {
        await showDatabaseUsage(client, args[1], args[2], args[3]);
        return 0;
      }
      if (args[0] === 'stats') {
        await showDatabaseStatistics(client, args[1], args[2], args[3]);
        return 0;
      }
      if (args[0] === 'group-stats') {
        await showGroupStatistics(client, args[1], args[2], args[3]);
        return 0;
      }
      if (args[0] === 'active-usage') {
        await showActiveDatabaseUsage(client);
        return 0;
      }
    } catch (error) {
      throw await enrichDatabaseFailureWithSpec(client, argv, error);
    }
  }

  fail(`Unsupported command: ${argv.join(' ')}`);
}

export {
  CliError,
  applyAppSpec,
  buildAppSpec,
  buildSqlPipelineUrl,
  buildSqlRequests,
  buildTemplatePatch,
  createApp,
  createAppFromSpec,
  createPullZone,
  createDatabase,
  createApiClient,
  dedupeEnvVars,
  deleteApp,
  deleteDatabase,
  dumpDatabaseSchema,
  formatIsoDate,
  fetchLatestDatabaseSpec,
  forkDatabase,
  generateDatabaseToken,
  generateDatabaseGroupToken,
  getDatabaseSpecCachePath,
  getDatabaseAccessKey,
  getDatabaseBearerToken,
  getDatabaseGroup,
  healthCheck,
  listDatabaseIndexes,
  listDatabaseTables,
  listDatabases,
  listDatabaseVersions,
  listPullZones,
  listRecords,
  listZones,
  loadConfig,
  loadEnvFile,
  mergeEnvVars,
  mirrorDatabaseRegions,
  mutateReplicaRegion,
  normalizeEndpoints,
  normalizeSqlResult,
  parseEnvText,
  parseImageRef,
  parseSqlApiValue,
  readCachedDatabaseSpec,
  refreshDatabaseSpecCache,
  removeEndpoint,
  removeEnvVar,
  runCli,
  runDatabaseBatch,
  runDatabaseDoctor,
  runDatabaseForeignKeyCheck,
  runDatabaseIntegrityCheck,
  scaleApp,
  setDnsRecord,
  setDatabaseRegions,
  setPullZoneRecord,
  restoreDatabaseVersion,
  showActiveDatabaseUsage,
  showDatabaseGroup,
  showDatabaseLimits,
  showDatabaseSpecCacheStatus,
  showDatabasePragma,
  showDatabaseSchema,
  showDatabaseStatistics,
  showDatabaseUsage,
  showGroupStatistics,
  syncEnv,
  updateAppImage,
  waitForApp,
  runDatabaseSql,
};

if (isDirectExecution()) {
  runCli().catch((error) => {
    process.stderr.write(`${error.message}\n`);
    process.exit(error instanceof CliError ? 1 : 1);
  });
}
