import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const GITHUB_TOKEN = process.env.GITHUB_TOKEN ?? '';
const GITHUB_REPO_OWNER = process.env.GITHUB_REPO_OWNER ?? '';
const GITHUB_REPO_NAME = process.env.GITHUB_REPO_NAME ?? '';

/**
 * Run the full CI/CD pipeline for a given push event.
 *
 * SECURITY: All external inputs (repo URL, branch name, sha) are passed as
 * discrete arguments to execFileSync — never interpolated into a shell string.
 * This prevents shell injection from webhook payloads.
 *
 * @param {{ repo: string, sha: string, ref: string, isMain: boolean }} opts
 */
export async function runPipeline({ repo, sha, ref, isMain }) {
  const branch = ref.replace('refs/heads/', '');
  const workdir = mkdtempSync(join(tmpdir(), 'back-office-ci-'));

  console.log(`[pipeline] start sha=${sha} branch=${branch} isMain=${isMain} workdir=${workdir}`);

  try {
    await postStatus(sha, 'pending', 'CI pipeline started');

    // Clone — each argument is a discrete value, no shell interpretation
    execFileSync('git', ['clone', '--depth', '1', '--branch', branch, repo, workdir], {
      stdio: 'inherit',
    });

    // Install Python dependencies
    execFileSync('pip', ['install', '-r', join(workdir, 'requirements.txt')], {
      cwd: workdir,
      stdio: 'inherit',
    });

    // Lint with ruff
    execFileSync('ruff', ['check', '.'], {
      cwd: workdir,
      stdio: 'inherit',
    });

    // Run test suite
    execFileSync('python', ['-m', 'pytest', 'tests/', '-v'], {
      cwd: workdir,
      stdio: 'inherit',
    });

    // Deploy only from main
    if (isMain) {
      execFileSync('python', ['-m', 'backoffice', 'sync'], {
        cwd: workdir,
        stdio: 'inherit',
        env: { ...process.env, BUNNY_CI: '1' },
      });
    }

    await postStatus(sha, 'success', isMain ? 'CI passed + deployed' : 'CI passed');
    console.log(`[pipeline] success sha=${sha}`);
  } catch (err) {
    const message = err?.message ?? String(err);
    console.error(`[pipeline] failure sha=${sha}:`, message);
    await postStatus(sha, 'failure', 'CI pipeline failed');
    throw err;
  } finally {
    try {
      rmSync(workdir, { recursive: true, force: true });
    } catch (cleanupErr) {
      console.warn('[pipeline] cleanup warning:', cleanupErr?.message);
    }
  }
}

/**
 * Post a commit status to the GitHub Statuses API.
 *
 * @param {string} sha
 * @param {'pending'|'success'|'failure'|'error'} state
 * @param {string} description
 */
export async function postStatus(sha, state, description) {
  if (!GITHUB_TOKEN || !GITHUB_REPO_OWNER || !GITHUB_REPO_NAME) {
    console.warn('[pipeline] skipping GitHub status post — GITHUB_TOKEN/REPO_OWNER/REPO_NAME not set');
    return;
  }

  const url = `https://api.github.com/repos/${GITHUB_REPO_OWNER}/${GITHUB_REPO_NAME}/statuses/${sha}`;

  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${GITHUB_TOKEN}`,
        'Content-Type': 'application/json',
        'User-Agent': 'back-office-ci/1.0',
      },
      body: JSON.stringify({
        state,
        description,
        context: 'back-office-ci',
      }),
    });

    if (!res.ok) {
      const text = await res.text();
      console.warn(`[pipeline] GitHub status API returned ${res.status}: ${text}`);
    }
  } catch (err) {
    console.warn('[pipeline] failed to post GitHub status:', err?.message);
  }
}
