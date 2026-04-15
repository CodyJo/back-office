import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

import {
  CliError,
  applyAppSpec,
  buildSqlPipelineUrl,
  buildSqlRequests,
  buildAppSpec,
  createDatabase,
  createAppFromSpec,
  formatIsoDate,
  generateDatabaseGroupToken,
  generateDatabaseToken,
  getDatabaseSpecCachePath,
  readCachedDatabaseSpec,
  refreshDatabaseSpecCache,
  showActiveDatabaseUsage,
  showDatabaseLimits,
  showDatabaseSpecCacheStatus,
  showDatabaseUsage,
  listDatabaseTables,
  mutateReplicaRegion,
  parseEnvText,
  parseImageRef,
  runDatabaseDoctor,
  runDatabaseSql,
  runCli,
  runDomainDoctor,
  setDatabaseRegions,
  showPullZone,
  syncEnv,
  waitForApp,
} from '../scripts/bunny-cli-next.mjs';

function createApp(overrides = {}) {
  return {
    id: 'app_123',
    name: 'fuel-web',
    status: 'deploying',
    runtimeType: 'shared',
    autoScaling: { min: 1, max: 3 },
    displayEndpoint: { address: 'fuel-web.bunnyapp.io' },
    regionSettings: { requiredRegionIds: ['de'] },
    containerInstances: [{ id: 'instance-1' }],
    containerTemplates: [{
      id: 'tpl_1',
      name: 'app',
      packageId: 'pkg_1',
      imageNamespace: 'merm',
      imageName: 'fuel',
      imageTag: 'v1',
      imageRegistryId: 'registry_1',
      imagePullPolicy: 'always',
      environmentVariables: [
        { name: 'APP_ENV', value: 'prod' },
        { name: 'OLD_KEY', value: 'legacy' },
      ],
      endpoints: [{
        displayName: 'fuel-web-cdn',
        type: 'cdn',
        publicHost: 'fuel.example.com',
        cdn: { portMappings: [{ containerPort: 3000 }] },
      }],
    }],
    ...overrides,
  };
}

function createClient(app = createApp()) {
  const patches = [];
  const dbPatches = [];
  const sqlRequests = [];
  const stdout = { chunks: [], write(chunk) { this.chunks.push(chunk); } };
  return {
    stdout,
    patches,
    dbPatches,
    sqlRequests,
    dbBearerToken: 'db-token',
    async get(path) {
      assert.equal(path, '/mc/apps/app_123');
      return app;
    },
    async patch(path, body) {
      assert.equal(path, '/mc/apps/app_123');
      patches.push(body);
      return { displayEndpoint: { address: 'fuel.example.com' } };
    },
    async dbGet(path) {
      if (path === '/v1/config/limits') {
        return { current_databases: 4, max_databases: 50 };
      }
      if (path === '/v2/databases/active_usage') {
        return { stats: [{ db_id: 'db_123', reads: 10 }] };
      }
      if (path === '/v1/config') {
        return {
          primary_regions: [{ id: 'de' }],
          storage_region_available: [{ id: 'de' }],
        };
      }
      if (path === '/v1/databases') {
        return {
          databases: [{
            id: 'db_123',
            name: 'fuel-db',
            group_id: 'group_abc',
            url: 'libsql://abc-fuel.aws.bunnydb.io',
          }],
        };
      }
      if (path === '/v2/databases/db_123') {
        return {
          db: {
            id: 'db_123',
            name: 'fuel-db',
            group_id: 'group_abc',
            url: 'libsql://abc-fuel.aws.bunnydb.io',
          },
        };
      }
      if (path === '/v1/groups/group_abc') {
        return {
          group: {
            id: 'group_abc',
            storage_region: 'de',
            primary_regions: ['de'],
            replicas_regions: ['uk'],
          },
        };
      }
      throw new Error(`Unexpected dbGet path: ${path}`);
    },
    async dbPatch(path, body) {
      assert.equal(path, '/v1/groups/group_abc');
      dbPatches.push(body);
      return { group: { id: 'group_abc', ...body } };
    },
    async dbPost(path, body) {
      if (path === '/v2/databases') {
        dbPatches.push({ create: body });
        return { db_id: 'db_123' };
      }
      if (path === '/v1/groups/group_abc/auth/generate') {
        dbPatches.push({ groupToken: body });
        return { token: 'group-token' };
      }
      throw new Error(`Unexpected dbPost path: ${path}`);
    },
    async dbPut(path, body) {
      if (path === '/v2/databases/db_123/auth/generate') {
        dbPatches.push({ token: body });
        return { token: 'generated-token' };
      }
      throw new Error(`Unexpected dbPut path: ${path}`);
    },
    async dbDelete(path) {
      assert.equal(path, '/v2/databases/db_123');
      dbPatches.push({ delete: true });
      return null;
    },
    async fetchImpl(url, init) {
      sqlRequests.push({ url, init });
      return {
        ok: true,
        status: 200,
        async text() {
          return JSON.stringify({
            results: [{
              response: {
                result: {
                  cols: [{ name: 'id' }, { name: 'name' }],
                  rows: [[{ value: '1' }, { value: 'fuel' }]],
                  affected_row_count: 0,
                  last_insert_rowid: null,
                  replication_index: 'ri_1',
                },
              },
            }],
          });
        },
      };
    },
  };
}

test('parseEnvText handles comments and quoted values', () => {
  const env = parseEnvText(`
    # comment
    APP_ENV=prod
    API_KEY="abc123"
    NAME='fuel web'
  `);

  assert.deepEqual(env, [
    { name: 'APP_ENV', value: 'prod' },
    { name: 'API_KEY', value: 'abc123' },
    { name: 'NAME', value: 'fuel web' },
  ]);
});

test('parseImageRef enforces namespace/name:tag', () => {
  assert.deepEqual(parseImageRef('merm/fuel:v4'), {
    imageNamespace: 'merm',
    imageName: 'fuel',
    imageTag: 'v4',
  });
});

test('syncEnv replaces environment variables in app patch payload', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'bunny-cli-test-'));
  const envFile = join(dir, 'fuel.env');
  writeFileSync(envFile, 'APP_ENV=production\nAPI_URL=https://api.example.com\n', 'utf8');

  try {
    const client = createClient();
    await syncEnv(client, 'app_123', envFile, { merge: false });

    assert.equal(client.patches.length, 1);
    assert.deepEqual(client.patches[0].containerTemplates[0].environmentVariables, [
      { name: 'API_URL', value: 'https://api.example.com' },
      { name: 'APP_ENV', value: 'production' },
    ]);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('showPullZone renders concise pull zone details', async () => {
  const stdout = { chunks: [], write(chunk) { this.chunks.push(chunk); } };
  const client = {
    stdout,
    async get(path) {
      assert.equal(path, '/pullzone/5587167');
      return {
        Id: 5587167,
        Name: 'thenewbeautifulme-www',
        OriginUrl: 'https://mc-lspdkzm5r5.bunny.run',
        Enabled: true,
        Hostnames: [
          { Id: 1, Value: 'thenewbeautifulme.com', ForceSSL: true, CertificateStatus: 'Active', IsSystemHostname: false },
        ],
      };
    },
  };

  await showPullZone(client, '5587167');

  const output = stdout.chunks.join('');
  assert.match(output, /thenewbeautifulme-www/);
  assert.match(output, /mc-lspdkzm5r5\.bunny\.run/);
  assert.match(output, /thenewbeautifulme\.com/);
});

test('runDomainDoctor reports drift and dns records', async () => {
  const stdout = { chunks: [], write(chunk) { this.chunks.push(chunk); } };
  const client = {
    stdout,
    async get(path) {
      if (path === '/mc/apps/app_live') {
        return {
          id: 'app_live',
          name: 'thenewbeautifulme-v2',
          status: 'active',
          displayEndpoint: { address: 'mc-lspdkzm5r5.bunny.run' },
          containerTemplates: [],
        };
      }
      if (path === '/pullzone/5587167') {
        return {
          Id: 5587167,
          Name: 'thenewbeautifulme-www',
          OriginUrl: 'https://mc-old.bunny.run',
          Hostnames: [
            { Value: 'thenewbeautifulme.com', ForceSSL: true, CertificateStatus: 'Active' },
          ],
        };
      }
      if (path === '/dnszone/759177') {
        return {
          Domain: 'thenewbeautifulme.com',
          Records: [
            { Id: 10, Type: 7, Name: '@', Value: '', Ttl: 60 },
            { Id: 11, Type: 7, Name: 'www', Value: '', Ttl: 60 },
          ],
        };
      }
      throw new Error(`Unexpected path: ${path}`);
    },
  };

  await runDomainDoctor(client, 'thenewbeautifulme.com', 'app_live', '5587167', '759177');

  const output = stdout.chunks.join('');
  assert.match(output, /thenewbeautifulme-v2/);
  assert.match(output, /pull zone origin does not match the app display endpoint/);
  assert.match(output, /DNS zone:\s+thenewbeautifulme\.com/);
  assert.match(output, /PULLZONE @/);
  assert.match(output, /PULLZONE www/);
});

test('applyAppSpec patches image, scale, env, and endpoints from exported spec', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'bunny-cli-spec-'));
  const specFile = join(dir, 'fuel-spec.json');
  const spec = buildAppSpec(createApp({ status: 'running' }));
  spec.autoScaling = { min: 2, max: 5 };
  spec.containerTemplate.image = 'merm/fuel:v9';
  spec.containerTemplate.environmentVariables = [{ name: 'APP_ENV', value: 'preview' }];
  spec.containerTemplate.endpoints = [{
    displayName: 'preview-cdn',
    type: 'cdn',
    cdn: { portMappings: [{ containerPort: 4000 }] },
  }];
  writeFileSync(specFile, `${JSON.stringify(spec, null, 2)}\n`, 'utf8');

  try {
    const client = createClient();
    await applyAppSpec(client, 'app_123', specFile);

    const patch = client.patches[0];
    assert.deepEqual(patch.autoScaling, { min: 2, max: 5 });
    assert.equal(patch.containerTemplates[0].imageTag, 'v9');
    assert.deepEqual(patch.containerTemplates[0].environmentVariables, [{ name: 'APP_ENV', value: 'preview' }]);
    assert.deepEqual(patch.containerTemplates[0].endpoints, [{
      displayName: 'preview-cdn',
      type: 'cdn',
      cdn: { portMappings: [{ containerPort: 4000 }] },
    }]);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('buildAppSpec includes all container templates for multi-container apps', () => {
  const spec = buildAppSpec(createApp({
    containerTemplates: [
      ...createApp().containerTemplates,
      {
        id: 'tpl_2',
        name: 'worker',
        packageId: 'pkg_2',
        imageNamespace: 'merm',
        imageName: 'fuel-worker',
        imageTag: 'v1',
        imageRegistryId: 'registry_1',
        imagePullPolicy: 'always',
        environmentVariables: [{ name: 'WORKER', value: 'true' }],
        endpoints: [],
      },
    ],
  }));

  assert.equal(spec.containerTemplates.length, 2);
  assert.equal(spec.containerTemplates[1].name, 'worker');
  assert.equal(spec.containerTemplates[1].image, 'merm/fuel-worker:v1');
});

test('createAppFromSpec creates a multi-container app from a spec file', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'bunny-cli-create-spec-'));
  const specFile = join(dir, 'search-spec.json');
  writeFileSync(specFile, `${JSON.stringify({
    name: 'search',
    runtimeType: 'shared',
    autoScaling: { min: 1, max: 1 },
    regionSettings: { requiredRegionIds: ['DE'] },
    containerTemplates: [
      {
        name: 'edge',
        image: 'ghcr.io/codyjo/search-openresty:v1',
        imageRegistryId: '6323',
        environmentVariables: [{ name: 'JWT_SECRET', value: 'secret' }],
        endpoints: [{ displayName: 'search-cdn', type: 'cdn', cdn: { portMappings: [{ containerPort: 8088 }] } }],
      },
      {
        name: 'searxng',
        image: 'ghcr.io/codyjo/search-searxng:v1',
        imageRegistryId: '6323',
        environmentVariables: [{ name: 'SEARXNG_SECRET', value: 'another-secret' }],
        endpoints: [],
      },
    ],
  }, null, 2)}\n`, 'utf8');

  const stdout = { chunks: [], write(chunk) { this.chunks.push(chunk); } };
  const posts = [];
  const client = {
    stdout,
    async post(path, body) {
      assert.equal(path, '/mc/apps');
      posts.push(body);
      return {
        id: 'app_search',
        name: 'search',
        status: 'active',
        displayEndpoint: { address: 'mc-search.bunny.run' },
        containerTemplates: body.containerTemplates,
      };
    },
  };

  try {
    await createAppFromSpec(client, specFile);
    assert.equal(posts.length, 1);
    assert.equal(posts[0].containerTemplates.length, 2);
    assert.equal(posts[0].containerTemplates[0].imageNamespace, 'ghcr.io');
    assert.equal(posts[0].containerTemplates[0].imageName, 'codyjo/search-openresty');
    assert.equal(posts[0].containerTemplates[1].name, 'searxng');
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('applyAppSpec can add a second container template from spec', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'bunny-cli-multi-spec-'));
  const specFile = join(dir, 'multi-spec.json');
  writeFileSync(specFile, `${JSON.stringify({
    autoScaling: { min: 1, max: 1 },
    containerTemplates: [
      {
        name: 'app',
        image: 'merm/fuel:v2',
        environmentVariables: [{ name: 'APP_ENV', value: 'prod' }],
        endpoints: [{ displayName: 'fuel-web-cdn', type: 'cdn', cdn: { portMappings: [{ containerPort: 3000 }] } }],
      },
      {
        name: 'worker',
        image: 'merm/fuel-worker:v1',
        imageRegistryId: 'registry_1',
        environmentVariables: [{ name: 'WORKER', value: 'true' }],
        endpoints: [],
      },
    ],
  }, null, 2)}\n`, 'utf8');

  try {
    const client = createClient();
    await applyAppSpec(client, 'app_123', specFile);

    assert.equal(client.patches[0].containerTemplates.length, 2);
    assert.equal(client.patches[0].containerTemplates[1].name, 'worker');
    assert.equal(client.patches[0].containerTemplates[1].imageName, 'fuel-worker');
    assert.deepEqual(client.patches[0].containerTemplates[1].environmentVariables, [{ name: 'WORKER', value: 'true' }]);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('waitForApp polls until running and healthy', async () => {
  const stdout = { chunks: [], write(chunk) { this.chunks.push(chunk); } };
  let reads = 0;
  const client = {
    stdout,
    async get() {
      reads += 1;
      return createApp({
        status: reads === 1 ? 'deploying' : 'running',
        containerInstances: [{ id: `instance-${reads}` }],
      });
    },
  };

  let now = 0;
  await waitForApp(client, 'app_123', '30', '1', {
    now: () => now,
    sleep: async () => { now += 1000; },
    fetchImpl: async () => ({
      status: reads === 1 ? 503 : 200,
      async text() { return ''; },
    }),
  });

  assert.match(stdout.chunks.join(''), /App fuel-web is ready\./);
});

test('waitForApp treats active status as ready when health passes', async () => {
  const stdout = { chunks: [], write(chunk) { this.chunks.push(chunk); } };
  const client = {
    stdout,
    async get() {
      return createApp({
        status: 'active',
        containerInstances: [{ id: 'instance-1' }],
      });
    },
  };

  await waitForApp(client, 'app_123', '5', '1', {
    now: () => 0,
    sleep: async () => {},
    fetchImpl: async () => ({
      status: 200,
      async text() { return ''; },
    }),
  });

  assert.match(stdout.chunks.join(''), /App fuel-web is ready\./);
});

test('buildSqlPipelineUrl converts libsql URLs to https pipeline endpoints', () => {
  assert.equal(
    buildSqlPipelineUrl('libsql://abc-fuel.aws.bunnydb.io'),
    'https://abc-fuel.aws.bunnydb.io/v2/pipeline',
  );
});

test('buildSqlRequests encodes SQL args for pipeline execution', () => {
  assert.deepEqual(buildSqlRequests('select ?', '[1,true,"x"]'), [
    {
      type: 'execute',
      stmt: {
        sql: 'select ?',
        args: [
          { type: 'integer', value: '1' },
          { type: 'integer', value: '1' },
          { type: 'text', value: 'x' },
        ],
      },
    },
    { type: 'close' },
  ]);
});

test('createDatabase uses config defaults when regions are omitted', async () => {
  const client = createClient();
  await createDatabase(client, 'preview-db');

  assert.deepEqual(client.dbPatches[0], {
    create: {
      name: 'preview-db',
      primary_regions: ['de'],
      replicas_regions: [],
      storage_region: 'de',
    },
  });
});

test('formatIsoDate normalizes date inputs', () => {
  assert.equal(formatIsoDate('2026-03-27T12:00:00Z'), '2026-03-27T12:00:00.000Z');
});

test('generateDatabaseToken emits a generated token', async () => {
  const client = createClient();
  await generateDatabaseToken(client, 'fuel-db', 'read-only');

  assert.deepEqual(client.dbPatches[0], {
    token: { authorization: 'read-only' },
  });
  assert.match(client.stdout.chunks.join(''), /generated-token/);
});

test('generateDatabaseGroupToken emits a generated group token', async () => {
  const client = createClient();
  await generateDatabaseGroupToken(client, 'fuel-db', 'full-access');

  assert.deepEqual(client.dbPatches[0], {
    groupToken: { authorization: 'full-access' },
  });
  assert.match(client.stdout.chunks.join(''), /group-token/);
});

test('setDatabaseRegions patches group topology payload', async () => {
  const client = createClient();
  await setDatabaseRegions(client, 'fuel-db', 'de,us', 'de', 'uk,sg');

  assert.deepEqual(client.dbPatches[0], {
    primary_regions: ['de', 'us'],
    storage_region: 'de',
    replicas_regions: ['uk', 'sg'],
  });
});

test('mutateReplicaRegion adds and removes replicas from group payload', async () => {
  const addClient = createClient();
  await mutateReplicaRegion(addClient, 'fuel-db', 'sg', 'add');
  assert.deepEqual(addClient.dbPatches[0], {
    storage_region: 'de',
    primary_regions: ['de'],
    replicas_regions: ['uk', 'sg'],
  });

  const removeClient = createClient();
  await mutateReplicaRegion(removeClient, 'fuel-db', 'uk', 'remove');
  assert.deepEqual(removeClient.dbPatches[0], {
    storage_region: 'de',
    primary_regions: ['de'],
    replicas_regions: [],
  });
});

test('runDatabaseSql posts SQL pipeline request with bearer auth', async () => {
  const client = createClient();
  await runDatabaseSql(client, 'fuel-db', 'select * from users where id = ?', '[1]');

  assert.equal(client.sqlRequests[0].url, 'https://abc-fuel.aws.bunnydb.io/v2/pipeline');
  assert.equal(client.sqlRequests[0].init.method, 'POST');
  assert.equal(client.sqlRequests[0].init.headers.Authorization, 'Bearer db-token');
  assert.match(client.stdout.chunks.join(''), /"name": "fuel"/);
});

test('listDatabaseTables runs sqlite_master table discovery query', async () => {
  const client = createClient();
  await listDatabaseTables(client, 'fuel-db');

  const body = JSON.parse(client.sqlRequests[0].init.body);
  assert.match(body.requests[0].stmt.sql, /sqlite_master/);
});

test('runDatabaseDoctor aggregates several SQL checks', async () => {
  const client = createClient();
  await runDatabaseDoctor(client, 'fuel-db');

  const report = JSON.parse(client.stdout.chunks.join(''));
  assert.ok(report.integrity_check);
  assert.ok(report.foreign_keys);
  assert.ok(report.tables);
});

test('showDatabaseLimits prints config limits', async () => {
  const client = createClient();
  await showDatabaseLimits(client);
  assert.match(client.stdout.chunks.join(''), /max_databases/);
});

test('showActiveDatabaseUsage prints active stats', async () => {
  const client = createClient();
  await showActiveDatabaseUsage(client);
  assert.match(client.stdout.chunks.join(''), /db_123/);
});

test('getDatabaseSpecCachePath prefers env override', () => {
  assert.equal(
    getDatabaseSpecCachePath({ env: { BUNNY_DB_SPEC_CACHE: '/tmp/custom-spec.json' }, config: {} }),
    '/tmp/custom-spec.json',
  );
});

test('refreshDatabaseSpecCache fetches and persists Bunny DB private spec', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'bunny-cli-spec-cache-'));
  const cachePath = join(dir, 'private-api.json');
  const stdout = { chunks: [], write(chunk) { this.chunks.push(chunk); } };
  const client = {
    stdout,
    dbSpecCachePath: cachePath,
    async fetchImpl(url) {
      assert.equal(url, 'https://api.bunny.net/database/docs/private/api.json');
      return {
        ok: true,
        async text() {
          return JSON.stringify({
            openapi: '3.1.0',
            paths: {
              '/v1/config/limits': {
                get: { operationId: 'limits' },
              },
            },
          });
        },
      };
    },
  };

  try {
    const payload = await refreshDatabaseSpecCache(client);
    const cached = readCachedDatabaseSpec(cachePath);

    assert.equal(payload.spec.paths['/v1/config/limits'].get.operationId, 'limits');
    assert.equal(cached.spec.paths['/v1/config/limits'].get.operationId, 'limits');
    assert.match(stdout.chunks.join(''), /cachePath/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('showDatabaseSpecCacheStatus reports missing cache cleanly', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'bunny-cli-spec-status-'));
  const cachePath = join(dir, 'missing.json');
  const stdout = { chunks: [], write(chunk) { this.chunks.push(chunk); } };

  try {
    await showDatabaseSpecCacheStatus({ dbSpecCachePath: cachePath, stdout });
    const status = JSON.parse(stdout.chunks.join(''));
    assert.equal(status.present, false);
    assert.equal(status.cachePath, cachePath);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('showDatabaseUsage uses encoded ISO date query params', async () => {
  const client = createClient();
  const originalDbGet = client.dbGet;
  client.dbGet = async (path) => {
    if (path === '/v1/databases') {
      return originalDbGet(path);
    }
    assert.match(path, /\/v2\/databases\/db_123\/usage\?from=2026-03-27T00%3A00%3A00.000Z&to=2026-03-28T00%3A00%3A00.000Z/);
    return { ok: true };
  };
  await showDatabaseUsage(client, 'fuel-db', '2026-03-27T00:00:00Z', '2026-03-28T00:00:00Z');
  assert.match(client.stdout.chunks.join(''), /"ok": true/);
});

test('runCli executes app scale command without legacy passthrough', async () => {
  const patches = [];
  const stdout = { chunks: [], write(chunk) { this.chunks.push(chunk); } };
  const client = {
    stdout,
    async get() {
      return createApp({ status: 'running' });
    },
    async patch(_path, body) {
      patches.push(body);
      return {};
    },
  };

  const code = await runCli(['app', 'scale', 'app_123', '2', '4'], {
    client,
    stdout,
    disableLegacyPassthrough: true,
  });

  assert.equal(code, 0);
  assert.deepEqual(patches[0].autoScaling, { min: 2, max: 4 });
});

test('runCli executes database replica add command without legacy passthrough', async () => {
  const client = createClient();
  const code = await runCli(['db', 'replica', 'add', 'fuel-db', 'sg'], {
    client,
    stdout: client.stdout,
    disableLegacyPassthrough: true,
  });

  assert.equal(code, 0);
  assert.deepEqual(client.dbPatches[0], {
    storage_region: 'de',
    primary_regions: ['de'],
    replicas_regions: ['uk', 'sg'],
  });
});

test('runCli refreshes DB spec and appends drift details on DB HTTP failure', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'bunny-cli-spec-drift-'));
  const cachePath = join(dir, 'private-api.json');
  const stdout = { chunks: [], write(chunk) { this.chunks.push(chunk); } };

  writeFileSync(cachePath, `${JSON.stringify({
    fetchedAt: '2026-03-26T00:00:00.000Z',
    specUrl: 'https://api.bunny.net/database/docs/private/api.json',
    hash: 'old',
    spec: {
      paths: {
        '/v1/config/limits': {
          get: { operationId: 'limitsOld' },
        },
      },
    },
  }, null, 2)}\n`, 'utf8');

  const client = {
    stdout,
    dbSpecCachePath: cachePath,
    async dbGet(path) {
      if (path === '/v1/config/limits') {
        throw new Error('This path should not be called directly.');
      }
      throw new Error(`Unexpected path ${path}`);
    },
    async fetchImpl(url) {
      if (url === 'https://api.bunny.net/database/docs/private/api.json') {
        return {
          ok: true,
          async text() {
            return JSON.stringify({
              openapi: '3.1.0',
              paths: {},
            });
          },
        };
      }
      throw new Error(`Unexpected fetch url ${url}`);
    },
  };

  client.dbGet = async () => {
    throw new CliError('HTTP 500 GET /v1/config/limits\n{"error":"Internal error"}');
  };

  try {
    await assert.rejects(
      runCli(['db', 'limits'], {
        client,
        stdout,
        disableLegacyPassthrough: true,
      }),
      (error) => {
        assert.match(error.message, /Checked Bunny DB private API spec/);
        assert.match(error.message, /Current spec no longer exposes path \/v1\/config\/limits/);
        return true;
      },
    );
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
