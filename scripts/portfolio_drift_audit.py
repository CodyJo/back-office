#!/usr/bin/env python3
"""Portfolio drift audit for Cody Jo projects.

Scans /home/merm/projects and reports:
- package sourcing drift for @codyjo/* dependencies
- Next/React/tooling version skew
- missing baseline scripts
- missing app-shell/accessibility/e2e conventions
- obsolete checked-in shared-package mirrors
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


BASELINE_SCRIPTS = ("dev", "build", "lint", "test", "typecheck")
NEXT_APPS = (
    "fuel",
    "certstudy",
    "selah",
    "thenewbeautifulme",
    "cordivent",
    "continuum",
    "pattern",
)
SHARED_ROOT = Path("/home/merm/projects/shared/packages")


@dataclass(frozen=True)
class AppAudit:
    name: str
    path: Path
    next_version: str
    react_version: str
    codyjo_sources: dict[str, str]
    missing_scripts: list[str]
    has_skip_link: bool
    has_accessibility_page: bool
    has_privacy_page: bool
    has_registration_flow: bool
    has_registration_ui_consent: bool
    has_registration_server_consent: bool
    stores_registration_consent_metadata: bool
    has_playwright: bool
    mirror_dirs: list[str]
    app_shell_files: list[str]


def classify_source(raw: str) -> str:
    if raw.startswith("file:../shared/packages/"):
        return "shared"
    if raw.startswith("file:./vendor/shared-packages/"):
        return "vendor"
    if raw.startswith("file:packages/") or raw.startswith("file:./packages/"):
        return "local-mirror"
    return raw


def load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def find_app_shell_files(root: Path) -> list[str]:
    candidates = (
        "src/components/Navigation.tsx",
        "src/components/OnboardingManager.tsx",
        "src/components/Toast.tsx",
        "src/components/PwaInstallPrompt.tsx",
        "src/components/SessionTimeout.tsx",
        "src/lib/auth-context.tsx",
        "src/lib/theme-context.tsx",
        "src/lib/site.ts",
        "src/app/layout.tsx",
    )
    return [rel for rel in candidates if (root / rel).exists()]


def find_mirror_dirs(root: Path) -> list[str]:
    candidates = (
        "vendor/shared-packages",
        "packages",
    )
    return [rel for rel in candidates if (root / rel).exists()]


def detect_skip_link(layout_path: Path) -> bool:
    if not layout_path.exists():
        return False
    text = layout_path.read_text()
    return (
        'href="#main-content"' in text
        or "Skip to content" in text
        or "createSkipLinkOptions" in text
    )


def file_contains(path: Path, *patterns: str) -> bool:
    if not path.exists():
        return False
    text = path.read_text()
    return all(pattern in text for pattern in patterns)


def any_file_contains(paths: Iterable[Path], *patterns: str) -> bool:
    return any(file_contains(path, *patterns) for path in paths)


def audit_app(root: Path) -> AppAudit:
    package_json = load_json(root / "package.json")
    deps = package_json.get("dependencies", {})
    scripts = package_json.get("scripts", {})
    codyjo_sources = {
        name: classify_source(value)
        for name, value in deps.items()
        if name.startswith("@codyjo/")
    }

    registration_ui_files = [
        root / "src/app/register/page.tsx",
        root / "src/components/AuthPageClient.tsx",
        root / "src/components/LoginPageClient.tsx",
    ]
    registration_server_files = [
        root / "server/routes/auth.mjs",
        root / "lambda/api/index.mjs",
    ]
    has_registration_flow = any(path.exists() for path in registration_ui_files) or any(
        file_contains(path, "/auth/register") or file_contains(path, "handleRegister")
        for path in registration_server_files
    )

    return AppAudit(
        name=root.name,
        path=root,
        next_version=deps.get("next", ""),
        react_version=deps.get("react", ""),
        codyjo_sources=codyjo_sources,
        missing_scripts=[script for script in BASELINE_SCRIPTS if script not in scripts],
        has_skip_link=detect_skip_link(root / "src/app/layout.tsx"),
        has_accessibility_page=(root / "src/app/accessibility/page.tsx").exists(),
        has_privacy_page=(root / "src/app/privacy/page.tsx").exists(),
        has_registration_flow=has_registration_flow,
        has_registration_ui_consent=(
            not has_registration_flow
            or (
                any_file_contains(registration_ui_files, "Privacy Policy")
                and (
                    any_file_contains(registration_ui_files, "at least 16")
                    or any_file_contains(registration_ui_files, "minimumAge")
                    or any_file_contains(registration_ui_files, "ageConfirmed16Plus")
                )
            )
            or (
                any_file_contains(registration_ui_files, "consentChecked")
                and any_file_contains(registration_ui_files, "minimumAge")
            )
        ),
        has_registration_server_consent=(
            not has_registration_flow
            or any_file_contains(registration_server_files, "consent", "ageConfirmed16Plus")
        ),
        stores_registration_consent_metadata=(
            not has_registration_flow
            or file_contains(root / "server/routes/auth.mjs", "privacy_policy_version", "consented_at")
            or file_contains(root / "lambda/api/index.mjs", "privacyPolicyVersion", "consentedAt")
        ),
        has_playwright=(root / "playwright.config.ts").exists() or (root / "playwright.config.mjs").exists(),
        mirror_dirs=find_mirror_dirs(root),
        app_shell_files=find_app_shell_files(root),
    )


def version_summary(audits: Iterable[AppAudit]) -> dict[str, set[str]]:
    next_versions: set[str] = set()
    react_versions: set[str] = set()
    for audit in audits:
        if audit.next_version:
            next_versions.add(audit.next_version)
        if audit.react_version:
            react_versions.add(audit.react_version)
    return {"next": next_versions, "react": react_versions}


def shared_package_status() -> list[str]:
    if not SHARED_ROOT.exists():
        return ["shared package repo missing"]
    return sorted(pkg.name for pkg in SHARED_ROOT.iterdir() if pkg.is_dir())


def render_markdown(audits: list[AppAudit]) -> str:
    lines: list[str] = []
    lines.append("# Portfolio Drift Audit")
    lines.append("")
    lines.append(f"Scanned {len(audits)} Next.js apps from `/home/merm/projects`.")
    lines.append("")

    versions = version_summary(audits)
    lines.append("## Runtime Drift")
    lines.append("")
    lines.append(f"- Next versions: {', '.join(sorted(versions['next'])) or 'none'}")
    lines.append(f"- React versions: {', '.join(sorted(versions['react'])) or 'none'}")
    lines.append("")

    lines.append("## Shared Package Source")
    lines.append("")
    lines.append("| App | Shared deps | Vendor deps | Local mirror deps | Other sources |")
    lines.append("| --- | --- | --- | --- | --- |")
    for audit in audits:
        source_counts = {"shared": 0, "vendor": 0, "local-mirror": 0, "other": 0}
        for source in audit.codyjo_sources.values():
            if source in source_counts:
                source_counts[source] += 1
            else:
                source_counts["other"] += 1
        lines.append(
            f"| {audit.name} | {source_counts['shared']} | {source_counts['vendor']} | {source_counts['local-mirror']} | {source_counts['other']} |"
        )
    lines.append("")

    lines.append("## Standards Checklist")
    lines.append("")
    lines.append("| App | Missing scripts | Skip link | Accessibility page | Privacy page | Signup flow | Signup UI consent | Signup server consent | Consent metadata | Playwright | Mirror dirs | App-shell files |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for audit in audits:
        lines.append(
            "| {name} | {missing} | {skip} | {accessibility} | {privacy} | {signup_flow} | {ui_consent} | {server_consent} | {consent_metadata} | {playwright} | {mirror_dirs} | {shell_count} |".format(
                name=audit.name,
                missing=", ".join(audit.missing_scripts) or "none",
                skip="yes" if audit.has_skip_link else "no",
                accessibility="yes" if audit.has_accessibility_page else "no",
                privacy="yes" if audit.has_privacy_page else "no",
                signup_flow="yes" if audit.has_registration_flow else "no",
                ui_consent="yes" if audit.has_registration_ui_consent else "no",
                server_consent="yes" if audit.has_registration_server_consent else "no",
                consent_metadata="yes" if audit.stores_registration_consent_metadata else "no",
                playwright="yes" if audit.has_playwright else "no",
                mirror_dirs=", ".join(audit.mirror_dirs) or "none",
                shell_count=len(audit.app_shell_files),
            )
        )
    lines.append("")

    lines.append("## Shared Package Inventory")
    lines.append("")
    for pkg in shared_package_status():
        lines.append(f"- `{pkg}`")
    lines.append("")

    lines.append("## Immediate Priorities")
    lines.append("")
    vendor_apps = [audit.name for audit in audits if "vendor" in audit.codyjo_sources.values()]
    local_mirror_apps = [audit.name for audit in audits if "local-mirror" in audit.codyjo_sources.values()]
    mirror_dir_apps = [audit.name for audit in audits if audit.mirror_dirs]
    no_e2e = [audit.name for audit in audits if not audit.has_playwright]
    no_skip = [audit.name for audit in audits if not audit.has_skip_link]
    no_accessibility = [audit.name for audit in audits if not audit.has_accessibility_page]
    no_privacy = [audit.name for audit in audits if not audit.has_privacy_page]
    no_signup_ui_consent = [audit.name for audit in audits if audit.has_registration_flow and not audit.has_registration_ui_consent]
    no_signup_server_consent = [audit.name for audit in audits if audit.has_registration_flow and not audit.has_registration_server_consent]
    no_consent_metadata = [audit.name for audit in audits if audit.has_registration_flow and not audit.stores_registration_consent_metadata]
    if vendor_apps:
        lines.append(f"- Move vendored shared packages to `/shared/packages`: {', '.join(vendor_apps)}")
    if local_mirror_apps:
        lines.append(f"- Replace repo-local shared package mirrors with `/shared/packages`: {', '.join(local_mirror_apps)}")
    if mirror_dir_apps:
        lines.append(f"- Delete obsolete checked-in shared package mirrors: {', '.join(mirror_dir_apps)}")
    if no_e2e:
        lines.append(f"- Add baseline Playwright coverage: {', '.join(no_e2e)}")
    if no_skip:
        lines.append(f"- Add skip-link layout baseline: {', '.join(no_skip)}")
    if no_accessibility:
        lines.append(f"- Add accessibility statement baseline: {', '.join(no_accessibility)}")
    if no_privacy:
        lines.append(f"- Add privacy page baseline: {', '.join(no_privacy)}")
    if no_signup_ui_consent:
        lines.append(f"- Add signup privacy + 16+ UI baseline: {', '.join(no_signup_ui_consent)}")
    if no_signup_server_consent:
        lines.append(f"- Enforce signup privacy + 16+ checks server-side: {', '.join(no_signup_server_consent)}")
    if no_consent_metadata:
        lines.append(f"- Store signup consent timestamp + policy version: {', '.join(no_consent_metadata)}")
    if lines[-1] == "":
        lines.append("- None")

    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        default="/home/merm/projects",
        help="Projects root to scan (default: /home/merm/projects)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root)
    audits: list[AppAudit] = []
    for name in NEXT_APPS:
        app_root = root / name
        package_json = app_root / "package.json"
        if not package_json.exists():
            continue
        audits.append(audit_app(app_root))

    print(render_markdown(audits))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
