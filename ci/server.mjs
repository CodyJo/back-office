import Fastify from 'fastify';
import { createHmac, timingSafeEqual } from 'node:crypto';
import { runPipeline } from './pipeline.mjs';

export const app = Fastify({ logger: true });

// Health probe — registered FIRST per Cody Jo Bunny pattern
app.get('/health', async (_req, reply) => {
  return reply.send({ status: 'ok' });
});

// Webhook receiver — GitHub push events
app.post('/webhook', async (req, reply) => {
  const signature = req.headers['x-hub-signature-256'];

  if (!signature) {
    return reply.status(401).send({ error: 'Missing X-Hub-Signature-256' });
  }

  const rawBody = JSON.stringify(req.body);
  const valid = verifySignature(rawBody, signature);

  if (!valid) {
    return reply.status(401).send({ error: 'Invalid signature' });
  }

  const event = req.headers['x-github-event'];
  const payload = req.body;

  if (event !== 'push') {
    return reply.send({ accepted: false, reason: 'non-push event ignored' });
  }

  const ref = payload.ref ?? '';
  const sha = payload.after ?? '';
  const cloneUrl = payload.repository?.clone_url ?? '';
  const isMain = ref === 'refs/heads/main';

  // Fire-and-forget — don't block the webhook response
  setImmediate(() => {
    runPipeline({ repo: cloneUrl, sha, ref, isMain }).catch((err) => {
      console.error('[pipeline] unhandled error:', err);
    });
  });

  return reply.send({ accepted: true, sha, isMain });
});

/**
 * Verify a GitHub HMAC-SHA256 webhook signature.
 *
 * @param {string} body - Raw request body as a string
 * @param {string} signature - Value of X-Hub-Signature-256 header
 * @returns {boolean}
 */
export function verifySignature(body, signature) {
  const secret = process.env.GITHUB_WEBHOOK_SECRET;
  if (!secret) return false;

  try {
    const digest = 'sha256=' + createHmac('sha256', secret).update(body).digest('hex');
    const a = Buffer.from(digest);
    const b = Buffer.from(signature);
    if (a.length !== b.length) return false;
    return timingSafeEqual(a, b);
  } catch {
    return false;
  }
}

// Start server when run directly
if (process.argv[1] && new URL(import.meta.url).pathname === process.argv[1]) {
  const port = parseInt(process.env.PORT ?? '3000', 10);
  await app.listen({ port, host: '0.0.0.0' });
}
