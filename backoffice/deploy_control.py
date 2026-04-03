"""Deploy control data and workflow dispatch helpers for Back Office."""

from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
import os

from backoffice.delivery import detect_workflow_status, list_workflows


@dataclass(frozen=True)
class DeployTarget:
    key: str
    label: str
    repo_path: str
    forgejo_repo: str | None
    github_repo: str | None
    runtime: str
    environment: str
    deploy_workflow: str | None
    ci_workflow: str | None
    bunny_app_id: str | None = None
    bunny_pull_zone_id: str | None = None
    bunny_dns_zone_id: str | None = None
    public_url: str | None = None
    notes: str = ""


PORTFOLIO_TARGETS: tuple[DeployTarget, ...] = (
    DeployTarget(
        key="auth-service",
        label="Auth Service",
        repo_path="/home/merm/projects/auth-service",
        forgejo_repo="CodyJo/auth-service",
        github_repo="CodyJo/auth-service",
        runtime="bunny-magic-container",
        environment="production",
        deploy_workflow="deploy.yml",
        ci_workflow="ci.yml",
        bunny_app_id="UD0svg5olkCq0tn",
        bunny_pull_zone_id="5603096",
        public_url="https://auth.thenewbeautifulme.com/health",
        notes="Shared auth service. GitHub default branch is master.",
    ),
    DeployTarget(
        key="certstudy",
        label="CertStudy",
        repo_path="/home/merm/projects/certstudy",
        forgejo_repo="CodyJo/certstudy",
        github_repo="CodyJo/certstudy",
        runtime="bunny-magic-container",
        environment="production",
        deploy_workflow="deploy.yml",
        ci_workflow="ci.yml",
        bunny_app_id="tZ7v1Y9QeSxg0E4",
        bunny_pull_zone_id="5587595",
        public_url="https://study.codyjo.com/health",
    ),
    DeployTarget(
        key="codyjo.com",
        label="codyjo.com",
        repo_path="/home/merm/projects/codyjo.com",
        forgejo_repo="CodyJo/codyjo.com",
        github_repo="CodyJo/codyjo.com",
        runtime="bunny-storage-pull-zone",
        environment="production",
        deploy_workflow="deploy.yml",
        ci_workflow="ci.yml",
        bunny_pull_zone_id="5582774",
        bunny_dns_zone_id="759174",
        public_url="https://www.codyjo.com/",
    ),
    DeployTarget(
        key="cordivent",
        label="Cordivent",
        repo_path="/home/merm/projects/cordivent",
        forgejo_repo="CodyJo/cordivent",
        github_repo="CodyJo/cordivent",
        runtime="bunny-magic-container",
        environment="production",
        deploy_workflow="deploy.yml",
        ci_workflow="ci.yml",
        bunny_app_id="dLK8UyDiv1e4sHu",
        bunny_pull_zone_id="5588277",
        public_url="https://www.cordivent.com/health",
    ),
    DeployTarget(
        key="fuel",
        label="Fuel",
        repo_path="/home/merm/projects/fuel",
        forgejo_repo="CodyJo/fuel",
        github_repo="CodyJo/fuel",
        runtime="bunny-magic-container",
        environment="production",
        deploy_workflow="deploy.yml",
        ci_workflow="ci.yml",
        bunny_app_id="F8cKya950t3vhvH",
        bunny_pull_zone_id="5587003",
        public_url="https://fuel.codyjo.com/health",
    ),
    DeployTarget(
        key="pattern",
        label="Pattern",
        repo_path="/home/merm/projects/pattern",
        forgejo_repo="CodyJo/pattern",
        github_repo=None,
        runtime="bunny-magic-container",
        environment="production",
        deploy_workflow="deploy.yml",
        ci_workflow="ci.yml",
        bunny_app_id="uuow5uE05olUn52",
        bunny_pull_zone_id="5589111",
        public_url="https://pattern.codyjo.com/",
        notes="GitHub repo slug not confirmed from this checkout.",
    ),
    DeployTarget(
        key="search",
        label="Search",
        repo_path="/home/merm/projects/search",
        forgejo_repo="CodyJo/search",
        github_repo="CodyJo/search",
        runtime="bunny-multi-container",
        environment="production",
        deploy_workflow="deploy.yml",
        ci_workflow="ci.yml",
        bunny_app_id="j4oVIwXaqYKmr2i",
        bunny_pull_zone_id="5588299",
        public_url="https://search.codyjo.com/health",
        notes="GitHub default branch is master.",
    ),
    DeployTarget(
        key="selah",
        label="Selah",
        repo_path="/home/merm/projects/selah",
        forgejo_repo="CodyJo/selah",
        github_repo="CodyJo/selah",
        runtime="bunny-magic-container",
        environment="production",
        deploy_workflow="deploy.yml",
        ci_workflow="ci.yml",
        bunny_app_id="YgU9xD2yYez1bhz",
        bunny_pull_zone_id="5587594",
        public_url="https://www.selahscripture.com/health",
    ),
    DeployTarget(
        key="thenewbeautifulme",
        label="The New Beautiful Me",
        repo_path="/home/merm/projects/thenewbeautifulme",
        forgejo_repo="CodyJo/thenewbeautifulme",
        github_repo="CodyJo/thenewbeautifulme",
        runtime="bunny-magic-container",
        environment="production",
        deploy_workflow="deploy.yml",
        ci_workflow="ci.yml",
        bunny_app_id="8NwgOJyUv5cq6qk",
        bunny_pull_zone_id="5588617",
        public_url="https://thenewbeautifulme.com/health",
        notes="Backed by thenewbeautifulme-v2 on Bunny.",
    ),
    DeployTarget(
        key="analogify",
        label="Analogify",
        repo_path="/home/merm/projects/analogify",
        forgejo_repo="CodyJo/analogify",
        github_repo="CodyJo/analogify",
        runtime="deferred-legacy-aws",
        environment="deferred",
        deploy_workflow=None,
        ci_workflow=None,
        bunny_dns_zone_id="759177",
        notes="Legacy AWS runtime. Not in the first Bunny GitHub Actions wave.",
    ),
    DeployTarget(
        key="continuum",
        label="Continuum",
        repo_path="/home/merm/projects/continuum",
        forgejo_repo="CodyJo/continuum",
        github_repo="CodyJo/continuum",
        runtime="deferred-bunny",
        environment="deferred",
        deploy_workflow=None,
        ci_workflow=None,
        notes="Blocked by cross-repo shared package coupling.",
    ),
    DeployTarget(
        key="back-office",
        label="Back Office",
        repo_path="/home/merm/projects/back-office",
        forgejo_repo="CodyJo/back-office",
        github_repo="CodyJo/back-office",
        runtime="control-plane",
        environment="production",
        deploy_workflow=None,
        ci_workflow=None,
        notes="This dashboard itself. Extend rather than replace.",
    ),
    DeployTarget(
        key="pe-dashboards",
        label="PE Dashboards",
        repo_path="/home/merm/projects/pe-dashboards",
        forgejo_repo="CodyJo/pe-dashboards",
        github_repo="CodyJo/pe-dashboards",
        runtime="deferred-demo",
        environment="deferred",
        deploy_workflow=None,
        ci_workflow=None,
        notes="Demo stack, not part of the first product deploy wave.",
    ),
    DeployTarget(
        key="postal-gcp",
        label="Postal GCP",
        repo_path="/home/merm/projects/postal-gcp",
        forgejo_repo="CodyJo/postal-gcp",
        github_repo="CodyJo/postal-gcp",
        runtime="gcp-production",
        environment="production",
        deploy_workflow=None,
        ci_workflow=None,
        notes="GCP remains the active production path.",
    ),
    DeployTarget(
        key="pe-bootstrap",
        label="PE Bootstrap",
        repo_path="/home/merm/projects/pe-bootstrap",
        forgejo_repo="CodyJo/pe-bootstrap",
        github_repo="CodyJo/pe-bootstrap",
        runtime="gcp-production",
        environment="production",
        deploy_workflow=None,
        ci_workflow=None,
        notes="GCP-focused infra repo.",
    ),
)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _source_control_provider() -> str:
    provider = os.environ.get("BACK_OFFICE_SOURCE_CONTROL", "auto").strip().lower()
    if provider in {"forgejo", "github"}:
        return provider
    if os.environ.get("FORGEJO_BASE_URL") and os.environ.get("FORGEJO_TOKEN"):
        return "forgejo"
    return "github"


def _run(args: list[str], timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _run_json(args: list[str], timeout: int = 20) -> tuple[dict | list | None, str | None]:
    result = _run(args, timeout=timeout)
    if result.returncode != 0:
        return None, (result.stderr or result.stdout or "command failed").strip()
    try:
        return json.loads(result.stdout), None
    except json.JSONDecodeError:
        return None, "invalid json output"


def _workflow_inventory(repo_path: Path) -> dict:
    if not repo_path.exists():
        return {"present": False, "files": [], "statuses": detect_workflow_status([])}
    workflows = list_workflows(repo_path)
    return {
        "present": bool(workflows),
        "files": [workflow["file"] for workflow in workflows],
        "statuses": detect_workflow_status(workflows),
    }


def _request_json(url: str, token: str, timeout: int = 20) -> tuple[dict | list | None, str | None]:
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/json",
            "User-Agent": "back-office-deploy-control/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return json.load(response), None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return None, f"HTTP {exc.code}: {body or exc.reason}"
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def _forgejo_repo_summary(repo: str | None) -> dict:
    if not repo:
        return {"configured": False, "error": "forgejo repo slug not configured"}

    base_url = os.environ.get("FORGEJO_BASE_URL", "").rstrip("/")
    token = os.environ.get("FORGEJO_TOKEN", "")
    if not base_url or not token:
        return {
            "configured": False,
            "repo": repo,
            "error": "FORGEJO_BASE_URL and FORGEJO_TOKEN are required for Forgejo control",
        }

    repo_data, repo_error = _request_json(f"{base_url}/api/v1/repos/{repo}", token)
    runs_data, runs_error = _request_json(f"{base_url}/api/v1/repos/{repo}/actions/runs?limit=8", token)

    runs = []
    if isinstance(runs_data, dict):
        runs = runs_data.get("workflow_runs") or runs_data.get("runs") or []
    elif isinstance(runs_data, list):
        runs = runs_data

    return {
        "configured": repo_error is None,
        "provider": "forgejo",
        "repo": repo,
        "default_branch": (repo_data or {}).get("default_branch") if isinstance(repo_data, dict) else None,
        "private": (repo_data or {}).get("private") if isinstance(repo_data, dict) else None,
        "html_url": (repo_data or {}).get("html_url") if isinstance(repo_data, dict) else None,
        "secrets_count": None,
        "runner_count": None,
        "recent_runs": runs,
        "errors": {
            "repo": repo_error,
            "runs": runs_error,
        },
    }


def _github_repo_summary(repo: str | None) -> dict:
    if not repo:
        return {"configured": False, "error": "github repo slug not configured"}

    repo_data, repo_error = _run_json(["gh", "api", f"repos/{repo}"])
    secrets_data, secrets_error = _run_json(["gh", "api", f"repos/{repo}/actions/secrets"])
    runners_data, runners_error = _run_json(["gh", "api", f"repos/{repo}/actions/runners"])
    runs_data, runs_error = _run_json(
        [
            "gh",
            "run",
            "list",
            "--repo",
            repo,
            "--limit",
            "8",
            "--json",
            "databaseId,workflowName,status,conclusion,displayTitle,headBranch,headSha,event,createdAt,updatedAt,url",
        ],
        timeout=30,
    )

    return {
        "configured": repo_error is None,
        "provider": "github",
        "repo": repo,
        "default_branch": (repo_data or {}).get("default_branch") if isinstance(repo_data, dict) else None,
        "private": (repo_data or {}).get("private") if isinstance(repo_data, dict) else None,
        "html_url": (repo_data or {}).get("html_url") if isinstance(repo_data, dict) else None,
        "secrets_count": (secrets_data or {}).get("total_count") if isinstance(secrets_data, dict) else None,
        "runner_count": (runners_data or {}).get("total_count") if isinstance(runners_data, dict) else None,
        "recent_runs": runs_data if isinstance(runs_data, list) else [],
        "errors": {
            "repo": repo_error,
            "secrets": secrets_error,
            "runners": runners_error,
            "runs": runs_error,
        },
    }


def _repo_summary(target: DeployTarget) -> dict:
    provider = _source_control_provider()
    if provider == "forgejo":
        return _forgejo_repo_summary(target.forgejo_repo)
    return _github_repo_summary(target.github_repo)


def _bunny_summary(root: Path, app_id: str | None) -> dict:
    if not app_id:
        return {"configured": False, "error": "no bunny app id"}

    payload, error = _run_json(
        [
            "node",
            str(root / "scripts" / "bunny-cli-next.mjs"),
            "app",
            app_id,
            "--json",
        ],
        timeout=30,
    )
    if error:
        return {"configured": False, "error": error}
    if not isinstance(payload, dict):
        return {"configured": False, "error": "unexpected bunny payload"}
    return {
        "configured": True,
        "app_id": payload.get("id"),
        "name": payload.get("name"),
        "status": payload.get("status"),
        "display_endpoint": payload.get("displayEndpoint"),
        "container_count": len(payload.get("containerTemplates") or []),
        "containers": [
            {
                "name": container.get("name"),
                "image": container.get("image"),
                "registry_id": container.get("imageRegistryId"),
                "env_count": len(container.get("environmentVariables") or []),
                "endpoints": container.get("endpoints") or [],
            }
            for container in (payload.get("containerTemplates") or [])
        ],
    }


def _health_summary(url: str | None) -> dict:
    if not url:
        return {"configured": False, "status": "unknown"}
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "back-office-deploy-control/1.0"})
        with urllib.request.urlopen(request, timeout=6) as response:  # noqa: S310
            return {
                "configured": True,
                "status": "healthy" if 200 <= response.status < 400 else "unhealthy",
                "http_status": response.status,
            }
    except urllib.error.HTTPError as exc:
        return {"configured": True, "status": "unhealthy", "http_status": exc.code, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"configured": True, "status": "unknown", "error": str(exc)}


def build_deploy_control_payload(root: Path | None = None) -> dict:
    repo_root = (root or Path(__file__).resolve().parents[1]).resolve()
    targets = []

    for target in PORTFOLIO_TARGETS:
        repo_path = Path(target.repo_path)
        workflow_inventory = _workflow_inventory(repo_path)
        source_control_summary = _repo_summary(target)
        bunny_summary = _bunny_summary(repo_root, target.bunny_app_id)
        health_summary = _health_summary(target.public_url)

        runner_count = source_control_summary.get("runner_count")
        secrets_count = source_control_summary.get("secrets_count")
        is_ready = bool(
            target.deploy_workflow
            and (target.github_repo or target.forgejo_repo)
            and workflow_inventory["statuses"]["cd"]["configured"]
            and (runner_count is None or runner_count > 0)
            and (secrets_count is None or secrets_count > 0)
            and source_control_summary.get("configured")
        )

        targets.append(
            {
                **asdict(target),
                "repo_exists": repo_path.exists(),
                "workflow_inventory": workflow_inventory,
                "source_control": source_control_summary,
                "github": _github_repo_summary(target.github_repo) if target.github_repo else {"configured": False},
                "forgejo": _forgejo_repo_summary(target.forgejo_repo) if os.environ.get("FORGEJO_BASE_URL") and os.environ.get("FORGEJO_TOKEN") else {"configured": False},
                "bunny": bunny_summary,
                "health": health_summary,
                "deploy_ready": is_ready,
            }
        )

    summary = {
        "total": len(targets),
        "ready": sum(1 for target in targets if target["deploy_ready"]),
        "blocked": sum(1 for target in targets if not target["deploy_ready"]),
        "bunny": sum(1 for target in targets if target["runtime"].startswith("bunny")),
        "gcp": sum(1 for target in targets if target["runtime"].startswith("gcp")),
        "deferred": sum(1 for target in targets if target["environment"] == "deferred"),
    }

    return {
        "generated_at": iso_now(),
        "summary": summary,
        "targets": targets,
    }


def dispatch_deploy_workflow(target_key: str, ref: str | None = None) -> dict:
    target = next((item for item in PORTFOLIO_TARGETS if item.key == target_key), None)
    if not target:
        raise ValueError(f"Unknown deploy target: {target_key}")
    if not target.deploy_workflow:
        raise ValueError(f"Target {target_key} has no deploy workflow configured")

    provider = _source_control_provider()

    if provider == "forgejo":
        repo = target.forgejo_repo
        if not repo:
            raise ValueError(f"Target {target_key} has no Forgejo repo configured")
        base_url = os.environ.get("FORGEJO_BASE_URL", "").rstrip("/")
        token = os.environ.get("FORGEJO_TOKEN", "")
        if not base_url or not token:
            raise ValueError("FORGEJO_BASE_URL and FORGEJO_TOKEN are required for Forgejo dispatch")
        payload = {"ref": ref} if ref else {}
        request = urllib.request.Request(
            f"{base_url}/api/v1/repos/{repo}/actions/workflows/{target.deploy_workflow}/dispatches",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "back-office-deploy-control/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                status = response.status
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(body or exc.reason) from exc
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(str(exc)) from exc

        return {
            "ok": True,
            "provider": "forgejo",
            "target": target.key,
            "repo": repo,
            "workflow": target.deploy_workflow,
            "ref": ref,
            "status": status,
        }

    repo = target.github_repo
    if not repo:
        raise ValueError(f"Target {target_key} has no GitHub repo configured")

    args = [
        "gh",
        "workflow",
        "run",
        target.deploy_workflow,
        "--repo",
        repo,
    ]
    if ref:
        args.extend(["--ref", ref])

    result = _run(args, timeout=30)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "workflow dispatch failed").strip())

    return {
        "ok": True,
        "provider": "github",
        "target": target.key,
        "repo": repo,
        "workflow": target.deploy_workflow,
        "ref": ref,
        "output": (result.stdout or "").strip(),
    }
