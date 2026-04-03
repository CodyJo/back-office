#!/usr/bin/env node

/**
 * bunny-cli — Private CLI for Bunny.net Magic Containers, DNS, and Pull Zones.
 *
 * Usage:
 *   node bunny-cli.mjs <command> [options]
 *
 * Commands:
 *   apps                          List all Magic Container apps
 *   app <id>                      Get app details
 *   status <id>                   Quick status check (health, instances, errors)
 *   env list <id>                 List env vars for an app
 *   env set <id> <key> <value>    Set a single env var
 *   env load <id> <file>          Load env vars from .env or .json file
 *   deploy <id>                   Trigger redeployment
 *   logs <id>                     Stream logs (if available)
 *   dns zones                     List DNS zones
 *   dns records <zoneId>          List records in a zone
 *   dns set <zoneId> <name> <type> <value> [ttl]   Add/update DNS record
 *   dns pullzone <zoneId> <name> <pullZoneId> [ttl] Add/update Bunny PullZone DNS record
 *   dns delete <zoneId> <recordId>                  Delete DNS record
 *   pz list                       List pull zones
 *   pz create <name> <originUrl>  Create a pull zone
 *   pz origin <pzId> <originUrl>  Update pull zone origin
 *   pz hostname <pzId> <hostname> Add hostname to pull zone
 *   pz ssl <pzId> <hostname>      Activate free SSL for hostname
 *   pz purge <pzId>               Purge pull zone cache
 *   health <url>                  HTTP health check a URL
 */

import { readFileSync } from 'fs';
import { resolve } from 'path';

// ─── Config ───

const CONFIG_PATH = resolve(process.env.HOME, '.config/bunnynet.json');
let API_KEY;

try {
  const config = JSON.parse(readFileSync(CONFIG_PATH, 'utf8'));
  API_KEY = config.profiles?.default?.api_key;
} catch {
  // fall through
}

API_KEY = process.env.BUNNY_API_KEY || API_KEY;

if (!API_KEY) {
  console.error('No Bunny API key found. Set BUNNY_API_KEY or configure ~/.config/bunnynet.json');
  process.exit(1);
}

const BASE = 'https://api.bunny.net';

// ─── HTTP helpers ───

async function api(method, path, body) {
  const opts = {
    method,
    headers: { 'AccessKey': API_KEY, 'Content-Type': 'application/json' },
  };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(`${BASE}${path}`, opts);
  const text = await res.text();
  if (!res.ok) {
    console.error(`HTTP ${res.status} ${method} ${path}`);
    try { console.error(JSON.stringify(JSON.parse(text), null, 2)); } catch { console.error(text); }
    process.exit(1);
  }
  if (!text) return null;
  try { return JSON.parse(text); } catch { return text; }
}

const get = (path) => api('GET', path);
const post = (path, body) => api('POST', path, body);
const patch = (path, body) => api('PATCH', path, body);
const put = (path, body) => api('PUT', path, body);
const del = (path) => api('DELETE', path);

// ─── Magic Containers ───

async function listApps() {
  const data = await get('/mc/apps');
  const apps = data.items || [];
  if (apps.length === 0) { console.log('No apps found.'); return; }
  console.log('');
  for (const app of apps) {
    console.log(`  ${app.id}  ${app.name.padEnd(20)}  ${app.status.padEnd(12)}  ${app.displayEndpoint?.address || ''}`);
  }
  console.log('');
}

async function getApp(id) {
  const app = await get(`/mc/apps/${id}`);
  console.log('');
  console.log(`  App:       ${app.name} (${app.id})`);
  console.log(`  Status:    ${app.status}`);
  console.log(`  Endpoint:  ${app.displayEndpoint?.address || 'none'}`);
  console.log(`  Instances: ${app.containerInstances?.length || 0}`);
  console.log(`  Regions:   ${app.regionSettings?.requiredRegionIds?.join(', ') || 'auto'}`);
  console.log('');
  if (app.containerTemplates?.length) {
    for (const t of app.containerTemplates) {
      console.log(`  Container: ${t.name}`);
      console.log(`    Image:   ${t.imageNamespace}/${t.imageName}:${t.imageTag}`);
      console.log(`    Env:     ${t.environmentVariables?.length || 0} vars`);
      if (t.endpoints?.length) {
        for (const ep of t.endpoints) {
          console.log(`    Endpoint: ${ep.type} → ${ep.publicHost}`);
        }
      }
    }
  }
  console.log('');
}

async function createApp(name, imageNamespace, imageName, imageTag, registryId, port, envFile) {
  const payload = {
    name,
    runtimeType: 'shared',
    autoScaling: { min: 1, max: 3 },
    containerTemplates: [{
      name: 'app',
      imageName,
      imageNamespace,
      imageTag: imageTag || 'latest',
      imageRegistryId: registryId,
      imagePullPolicy: 'always',
      endpoints: [{
        displayName: `${name}-cdn`,
        type: 'cdn',
        cdn: { portMappings: [{ containerPort: parseInt(port || '3000') }] },
      }],
      environmentVariables: [],
    }],
  };

  // Load env vars if file provided
  if (envFile) {
    const content = readFileSync(resolve(envFile), 'utf8');
    if (envFile.endsWith('.json')) {
      payload.containerTemplates[0].environmentVariables = Object.entries(JSON.parse(content))
        .map(([name, value]) => ({ name, value: String(value) }));
    } else {
      payload.containerTemplates[0].environmentVariables = content.split('\n')
        .map(l => l.trim()).filter(l => l && !l.startsWith('#'))
        .map(l => { const eq = l.indexOf('='); if (eq < 0) return null; let v = l.substring(eq+1).trim(); if ((v.startsWith('"')&&v.endsWith('"'))||(v.startsWith("'")&&v.endsWith("'"))) v=v.slice(1,-1); return { name: l.substring(0,eq).trim(), value: v }; })
        .filter(Boolean);
    }
  }

  const app = await post('/mc/apps', payload);
  console.log(`App created: ${app.id} (${app.name})`);
  console.log(`Status: ${app.status}`);
  const ep = app.containerTemplates?.[0]?.endpoints?.[0];
  console.log(`CDN: ${ep?.publicHost || app.displayEndpoint?.address || 'pending'}`);
  console.log(`Env vars: ${app.containerTemplates?.[0]?.environmentVariables?.length || 0}`);
  return app;
}

async function deleteApp(id) {
  await del(`/mc/apps/${id}`);
  console.log(`App ${id} deleted.`);
}

async function appStatus(id) {
  const app = await get(`/mc/apps/${id}`);
  const endpoint = app.displayEndpoint?.address;

  console.log('');
  console.log(`  ${app.name}: ${app.status}`);
  console.log(`  Instances: ${app.containerInstances?.length || 0}`);

  if (endpoint) {
    try {
      const res = await fetch(`https://${endpoint}/health`, { signal: AbortSignal.timeout(5000) });
      const body = await res.text();
      console.log(`  Health:    HTTP ${res.status} — ${body.substring(0, 100)}`);
    } catch (err) {
      console.log(`  Health:    FAILED — ${err.message}`);
    }
  }
  console.log('');
}

async function listEnv(id) {
  const app = await get(`/mc/apps/${id}`);
  const template = app.containerTemplates?.[0];
  if (!template) { console.log('No containers.'); return; }

  const vars = template.environmentVariables || [];
  console.log('');
  if (vars.length === 0) { console.log('  No environment variables set.'); }
  else {
    const maxLen = vars.reduce((m, v) => Math.max(m, v.name.length), 0);
    for (const v of vars) {
      const val = v.value || '';
      const display = val.length > 40 ? val.substring(0, 37) + '...' : val;
      console.log(`  ${v.name.padEnd(maxLen)}  ${display}`);
    }
  }
  console.log('');
}

async function setEnv(id, key, value) {
  const app = await get(`/mc/apps/${id}`);
  const template = app.containerTemplates?.[0];
  if (!template) { console.error('No containers.'); process.exit(1); }

  const vars = template.environmentVariables || [];
  const existing = vars.findIndex(v => v.name === key);
  if (existing >= 0) { vars[existing].value = value; }
  else { vars.push({ name: key, value }); }

  await patch(`/mc/apps/${id}`, {
    containerTemplates: [{
      id: template.id,
      name: template.name,
      packageId: template.packageId,
      imageName: template.imageName,
      imageNamespace: template.imageNamespace,
      imageTag: template.imageTag,
      imageRegistryId: template.imageRegistryId,
      imagePullPolicy: template.imagePullPolicy,
      environmentVariables: vars,
      endpoints: normalizeEndpoints(template.endpoints),  // preserve endpoints!
    }]
  });

  console.log(`Set ${key} on ${app.name} (${vars.length} total vars). App will redeploy.`);
}

async function loadEnv(id, file) {
  const app = await get(`/mc/apps/${id}`);
  const template = app.containerTemplates?.[0];
  if (!template) { console.error('No containers.'); process.exit(1); }

  const content = readFileSync(resolve(file), 'utf8');
  let newVars;

  if (file.endsWith('.json')) {
    const obj = JSON.parse(content);
    newVars = Object.entries(obj).map(([name, value]) => ({ name, value: String(value) }));
  } else {
    // .env format
    newVars = content.split('\n')
      .map(l => l.trim())
      .filter(l => l && !l.startsWith('#'))
      .map(l => {
        const eq = l.indexOf('=');
        if (eq < 0) return null;
        const name = l.substring(0, eq).trim();
        let value = l.substring(eq + 1).trim();
        // Strip surrounding quotes
        if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
          value = value.slice(1, -1);
        }
        return { name, value };
      })
      .filter(Boolean);
  }

  // Merge with existing
  const vars = template.environmentVariables || [];
  for (const nv of newVars) {
    const existing = vars.findIndex(v => v.name === nv.name);
    if (existing >= 0) { vars[existing].value = nv.value; }
    else { vars.push(nv); }
  }

  await patch(`/mc/apps/${id}`, {
    containerTemplates: [{
      id: template.id,
      name: template.name,
      packageId: template.packageId,
      imageName: template.imageName,
      imageNamespace: template.imageNamespace,
      imageTag: template.imageTag,
      imageRegistryId: template.imageRegistryId,
      imagePullPolicy: template.imagePullPolicy,
      environmentVariables: vars,
      endpoints: normalizeEndpoints(template.endpoints),  // preserve endpoints!
    }]
  });

  console.log(`Loaded ${newVars.length} vars from ${file} → ${app.name} (${vars.length} total). App will redeploy.`);
}

function normalizeEndpoints(endpoints) {
  // The GET response has a flat structure, but PATCH expects nested cdn/anycast objects
  return (endpoints || []).map(ep => {
    const normalized = {
      displayName: ep.displayName,
      type: ep.type,
    };
    if (ep.type === 'cdn' || ep.type === 'CDN') {
      normalized.cdn = {
        portMappings: ep.portMappings || ep.cdn?.portMappings || [],
        stickySessions: ep.stickySessions || ep.cdn?.stickySessions || undefined,
      };
      if (ep.pullZoneId) normalized.cdn.pullZoneId = ep.pullZoneId;
    } else if (ep.type === 'anycast') {
      normalized.anycast = {
        portMappings: ep.portMappings || ep.anycast?.portMappings || [],
      };
    }
    return normalized;
  });
}

async function deployApp(id, newTag) {
  // Force redeploy. If a new tag is provided, update it. Otherwise bump
  // to a timestamped tag to force Bunny to pull fresh even for 'latest'.
  const app = await get(`/mc/apps/${id}`);
  const template = app.containerTemplates?.[0];
  if (!template) { console.error('No containers.'); process.exit(1); }

  const tag = newTag || template.imageTag || 'latest';

  // If no new tag provided and using 'latest', delete and recreate the app
  // because Bunny doesn't re-pull the same tag. This is a workaround.
  if (!newTag && template.imageTag === tag) {
    console.log(`Bunny doesn't re-pull the same tag. Use: deploy <id> <new-tag>`);
    console.log(`  Example: docker tag image:latest image:v4 && docker push image:v4`);
    console.log(`  Then:    bunny-cli deploy ${id} v4`);
    process.exit(1);
  }

  await patch(`/mc/apps/${id}`, {
    containerTemplates: [{
      id: template.id,
      name: template.name,
      packageId: template.packageId,
      imageName: template.imageName,
      imageNamespace: template.imageNamespace,
      imageTag: tag,
      imageRegistryId: template.imageRegistryId,
      imagePullPolicy: 'always',
      environmentVariables: template.environmentVariables || [],
      endpoints: normalizeEndpoints(template.endpoints),
    }]
  });

  console.log(`Redeployment triggered for ${app.name} with tag '${tag}'.`);
}

// ─── DNS ───

async function listZones() {
  const data = await get('/dnszone?page=1&perPage=100');
  const zones = data.Items || data.items || data || [];
  console.log('');
  for (const z of zones) {
    console.log(`  ${String(z.Id || z.id).padEnd(10)}  ${(z.Domain || z.domain || '').padEnd(30)}  records: ${z.RecordsCount ?? z.recordsCount ?? '?'}`);
  }
  console.log('');
}

async function listRecords(zoneId) {
  const zone = await get(`/dnszone/${zoneId}`);
  const records = zone.Records || zone.records || [];
  console.log('');
  console.log(`  Zone: ${zone.Domain || zone.domain} (${zoneId})`);
  console.log('');
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
  for (const r of records) {
    const t = types[r.Type ?? r.type] || String(r.Type ?? r.type);
    const name = (r.Name || r.name || '@').padEnd(25);
    const val = (r.Value || r.value || '').substring(0, 50);
    const ttl = r.Ttl || r.ttl || '';
    const id = r.Id || r.id || '';
    console.log(`  ${String(id).padEnd(12)} ${t.padEnd(6)} ${name} ${val.padEnd(50)} TTL:${ttl}`);
  }
  console.log('');
}

async function setDnsRecord(zoneId, name, type, value, ttl = 300) {
  const typeMap = { A: 0, AAAA: 1, CNAME: 2, TXT: 3, MX: 4, REDIRECT: 5, FLATTEN: 6, PULLZONE: 7 };
  const typeNum = typeMap[type.toUpperCase()] ?? parseInt(type);

  // Check if record exists
  const zone = await get(`/dnszone/${zoneId}`);
  const records = zone.Records || zone.records || [];
  const existing = records.find(r => (r.Name || r.name) === name && (r.Type ?? r.type) === typeNum);

  const body = typeNum === 7
    ? { PullZoneId: parseInt(value, 10), Ttl: parseInt(ttl), AutoSslIssuance: true }
    : { Value: value, Ttl: parseInt(ttl) };

  if (existing) {
    const rid = existing.Id || existing.id;
    await post(`/dnszone/${zoneId}/records/${rid}`, {
      ...body,
      Id: rid,
      Name: name,
      Type: typeNum,
    });
    console.log(`Updated ${type} ${name} → ${value} (TTL ${ttl})`);
  } else {
    await put(`/dnszone/${zoneId}/records`, { Type: typeNum, Name: name, ...body });
    console.log(`Created ${type} ${name} → ${value} (TTL ${ttl})`);
  }
}

async function setPullZoneRecord(zoneId, name, pullZoneId, ttl = 60) {
  return setDnsRecord(zoneId, name, 'PULLZONE', pullZoneId, ttl);
}

async function deleteDnsRecord(zoneId, recordId) {
  await del(`/dnszone/${zoneId}/records/${recordId}`);
  console.log(`Deleted record ${recordId} from zone ${zoneId}`);
}

// ─── Pull Zones ───

async function listPullZones() {
  const data = await get('/pullzone?page=1&perPage=100');
  const zones = data.Items || data.items || data || [];
  console.log('');
  for (const z of zones) {
    const id = z.Id || z.id;
    const name = z.Name || z.name || '';
    const origin = z.OriginUrl || z.originUrl || '';
    const hostnames = (z.Hostnames || z.hostnames || []).map(h => h.Value || h.value).join(', ');
    console.log(`  ${String(id).padEnd(10)} ${name.padEnd(25)} ${origin.padEnd(40)} ${hostnames}`);
  }
  console.log('');
}

async function createPullZone(name, originUrl) {
  const zone = await post('/pullzone', {
    Name: name,
    OriginUrl: originUrl,
  });
  console.log(`Created pull zone ${zone.Id || zone.id}: ${zone.Name || zone.name}`);
  console.log(`Origin: ${zone.OriginUrl || zone.originUrl}`);
  console.log(`CDN hostname: ${zone.Hostnames?.find((host) => host.IsSystemHostname)?.Value || `${name}.b-cdn.net`}`);
}

async function updatePullZoneOrigin(pzId, originUrl) {
  const zone = await post(`/pullzone/${pzId}`, { OriginUrl: originUrl });
  console.log(`Updated pull zone ${zone.Id || zone.id} origin to ${zone.OriginUrl || zone.originUrl}`);
}

async function addHostname(pzId, hostname) {
  await post(`/pullzone/${pzId}/addHostname`, { Hostname: hostname });
  console.log(`Added hostname ${hostname} to pull zone ${pzId}`);
}

async function activateSsl(pzId, hostname) {
  await get(`/pullzone/loadFreeCertificate?hostname=${encodeURIComponent(hostname)}`);
  await post(`/pullzone/${pzId}/setForceSSL`, { Hostname: hostname, ForceSSL: true });
  console.log(`SSL activated for ${hostname} on pull zone ${pzId}`);
}

async function purgeCache(pzId) {
  await post(`/pullzone/${pzId}/purgeCache`);
  console.log(`Cache purged for pull zone ${pzId}`);
}

// ─── Magic Container Endpoints ───

async function addCdnEndpoint(id, port, displayName) {
  const app = await get(`/mc/apps/${id}`);
  const template = app.containerTemplates?.[0];
  if (!template) { console.error('No containers.'); process.exit(1); }

  const endpoints = template.endpoints || [];
  endpoints.push({
    displayName: displayName || `${app.name}-cdn`,
    type: 'cdn',
    cdn: { portMappings: [{ containerPort: parseInt(port) }] },
  });

  const result = await patch(`/mc/apps/${id}`, {
    containerTemplates: [{
      id: template.id,
      name: template.name,
      packageId: template.packageId,
      imageName: template.imageName,
      imageNamespace: template.imageNamespace,
      imageTag: template.imageTag,
      imageRegistryId: template.imageRegistryId,
      imagePullPolicy: template.imagePullPolicy,
      environmentVariables: template.environmentVariables || [],
      endpoints,
    }]
  });

  const newEp = result.containerTemplates?.[0]?.endpoints?.slice(-1)?.[0];
  console.log(`CDN endpoint created: ${newEp?.publicHost || result.displayEndpoint?.address || 'check dashboard'}`);
}

// ─── Health Check ───

async function healthCheck(url) {
  if (!url.startsWith('http')) url = `https://${url}`;
  try {
    const start = Date.now();
    const res = await fetch(url, { signal: AbortSignal.timeout(10000) });
    const ms = Date.now() - start;
    const body = await res.text();
    console.log(`  HTTP ${res.status} (${ms}ms)`);
    console.log(`  ${body.substring(0, 200)}`);
  } catch (err) {
    console.log(`  FAILED: ${err.message}`);
  }
}

// ─── Router ───

const [,, cmd, ...args] = process.argv;

const commands = {
  apps: () => listApps(),
  app: () => {
    if (args[0] === 'create') return createApp(args[1], args[2], args[3], args[4], args[5], args[6], args[7]);
    if (args[0] === 'delete') return deleteApp(args[1]);
    return getApp(args[0]);
  },
  status: () => appStatus(args[0]),
  env: () => {
    if (args[0] === 'list') return listEnv(args[1]);
    if (args[0] === 'set') return setEnv(args[1], args[2], args.slice(3).join(' '));
    if (args[0] === 'load') return loadEnv(args[1], args[2]);
    console.error('Usage: env list|set|load <id> ...');
    process.exit(1);
  },
  deploy: () => deployApp(args[0], args[1]),
  endpoint: () => {
    if (args[0] === 'cdn') return addCdnEndpoint(args[1], args[2] || '3000', args[3]);
    console.error('Usage: endpoint cdn <appId> [port] [name]');
    process.exit(1);
  },
  dns: () => {
    if (args[0] === 'zones') return listZones();
    if (args[0] === 'records') return listRecords(args[1]);
    if (args[0] === 'set') return setDnsRecord(args[1], args[2], args[3], args[4], args[5]);
    if (args[0] === 'pullzone') return setPullZoneRecord(args[1], args[2], args[3], args[4]);
    if (args[0] === 'delete') return deleteDnsRecord(args[1], args[2]);
    console.error('Usage: dns zones|records|set|pullzone|delete ...');
    process.exit(1);
  },
  pz: () => {
    if (args[0] === 'list') return listPullZones();
    if (args[0] === 'create') return createPullZone(args[1], args[2]);
    if (args[0] === 'origin') return updatePullZoneOrigin(args[1], args[2]);
    if (args[0] === 'hostname') return addHostname(args[1], args[2]);
    if (args[0] === 'ssl') return activateSsl(args[1], args[2]);
    if (args[0] === 'purge') return purgeCache(args[1]);
    console.error('Usage: pz list|create|origin|hostname|ssl|purge ...');
    process.exit(1);
  },
  health: () => healthCheck(args[0]),
  logs: () => { console.log('Logs are only available via the Bunny dashboard (live streaming).'); },
};

if (!cmd || !commands[cmd]) {
  console.log(`
bunny-cli — Private Bunny.net CLI

Magic Containers:
  apps                              List all apps
  app <id>                          App details
  status <id>                       Quick status + health check
  env list <id>                     List env vars
  env set <id> <key> <value>        Set one env var (triggers redeploy)
  env load <id> <file>              Load from .env or .json (triggers redeploy)
  deploy <id>                       Force redeploy

DNS:
  dns zones                         List DNS zones
  dns records <zoneId>              List records
  dns set <zoneId> <name> <type> <value> [ttl]   Add/update record
  dns pullzone <zoneId> <name> <pullZoneId> [ttl] Add/update pull zone record
  dns delete <zoneId> <recordId>    Delete record

Pull Zones:
  pz list                           List pull zones
  pz create <name> <originUrl>      Create pull zone
  pz origin <pzId> <originUrl>      Update pull zone origin
  pz hostname <pzId> <hostname>     Add custom hostname
  pz ssl <pzId> <hostname>          Activate free SSL
  pz purge <pzId>                   Purge cache

Utility:
  health <url>                      HTTP health check
  logs <id>                         (dashboard only)
`);
  process.exit(0);
}

commands[cmd]().catch(err => {
  console.error('Error:', err.message);
  process.exit(1);
});
