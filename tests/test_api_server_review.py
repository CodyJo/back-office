"""API contract for /api/previews, /api/approve, /api/discard."""
from __future__ import annotations

import http.server
import json
import subprocess
import threading
import urllib.error
import urllib.request

import pytest

from backoffice.api_server import create_api_handler
from backoffice.config import Target


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _post(url, body, headers=None):
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def _get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


@pytest.fixture
def review_env(tmp_path):
    """Back-office root with a target repo, a preview branch, and a preview artifact."""
    bo_root = tmp_path / "back-office"
    bo_root.mkdir()
    results = bo_root / "results" / "target"
    results.mkdir(parents=True)

    repo = tmp_path / "target"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "a.py").write_text("print('hi')\n")
    _git(repo, "add", "a.py")
    _git(repo, "commit", "-m", "init")
    _git(repo, "checkout", "-b", "back-office/preview/pv-1")
    (repo / "a.py").write_text("print('hi, world')\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "fix: FIND-001")
    _git(repo, "checkout", "main")

    (results / "preview-pv-1.json").write_text(json.dumps({
        "version": 1,
        "job_id": "pv-1",
        "repo": "target",
        "branch": "back-office/preview/pv-1",
        "base_ref": "main",
        "changes": [{"file": "a.py", "insertions": 1, "deletions": 1}],
        "commits": [{"sha": "dead", "subject": "fix"}],
        "checklist": [],
    }))

    targets = {"target": Target(path=str(repo))}

    handler_cls = create_api_handler(
        root=bo_root,
        api_key="test-key",
        allowed_origins=["*"],
        targets=targets,
    )
    srv = http.server.HTTPServer(("127.0.0.1", 0), handler_cls)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield {
            "srv": srv,
            "port": srv.server_address[1],
            "repo": repo,
            "results": results,
        }
    finally:
        srv.shutdown()
        srv.server_close()


def test_list_previews_is_public(review_env):
    port = review_env["port"]
    code, body = _get(f"http://127.0.0.1:{port}/api/previews")
    assert code == 200
    assert isinstance(body.get("previews"), list)
    assert body["previews"][0]["job_id"] == "pv-1"


def test_approve_requires_api_key(review_env):
    port = review_env["port"]
    code, _ = _post(
        f"http://127.0.0.1:{port}/api/approve",
        {"target": "target", "job_id": "pv-1"},
    )
    assert code == 401


def test_approve_merges_preview(review_env):
    port = review_env["port"]
    code, body = _post(
        f"http://127.0.0.1:{port}/api/approve",
        {"target": "target", "job_id": "pv-1"},
        headers={"X-API-Key": "test-key"},
    )
    assert code == 200, body
    assert body["status"] == "approved"
    assert body["merged_into"] == "main"
    assert "hi, world" in (review_env["repo"] / "a.py").read_text()
    assert not (review_env["results"] / "preview-pv-1.json").exists()


def test_approve_unknown_job_returns_404(review_env):
    port = review_env["port"]
    code, body = _post(
        f"http://127.0.0.1:{port}/api/approve",
        {"target": "target", "job_id": "does-not-exist"},
        headers={"X-API-Key": "test-key"},
    )
    assert code == 404
    assert "error" in body


def test_discard_deletes_branch(review_env):
    port = review_env["port"]
    code, body = _post(
        f"http://127.0.0.1:{port}/api/discard",
        {"target": "target", "job_id": "pv-1"},
        headers={"X-API-Key": "test-key"},
    )
    assert code == 200
    assert body["status"] == "discarded"
    # Base unchanged
    assert (review_env["repo"] / "a.py").read_text() == "print('hi')\n"
    assert not (review_env["results"] / "preview-pv-1.json").exists()


def test_approve_unknown_target(review_env):
    port = review_env["port"]
    code, body = _post(
        f"http://127.0.0.1:{port}/api/approve",
        {"target": "missing", "job_id": "pv-1"},
        headers={"X-API-Key": "test-key"},
    )
    assert code == 400
    assert "error" in body
