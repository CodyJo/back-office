.PHONY: setup qa fix watch dashboard clean help jobs test test-coverage scaffold-workflows cli regression og-remediate
.PHONY: seo ada compliance monetization product cloud-ops audit-all audit-all-parallel audit-live full-scan quick-sync
.PHONY: grafana grafana-stop grafana-logs
.PHONY: monitoring-up monitoring-down monitoring-logs monitoring-status monitoring-restart monitoring-test monitoring-pull
.PHONY: forgejo-up forgejo-down forgejo-mirror
.PHONY: local-targets local-refresh local-audit local-audit-all self-audit-local
.PHONY: overnight overnight-dry overnight-stop overnight-status overnight-rollback

TARGET ?=

define require_remote_sync
	@test "$$CI" = "true" -o -n "$$DEPLOY_CI" -o "$$BACK_OFFICE_ENABLE_REMOTE_SYNC" = "1" || (echo "Remote sync is disabled by default for local use. Set BACK_OFFICE_ENABLE_REMOTE_SYNC=1 to enable." && exit 1)
endef

define require_auto_fix
	@test "$$BACK_OFFICE_ENABLE_AUTOFIX" = "1" || (echo "Auto-fix is disabled by default for local use. Set BACK_OFFICE_ENABLE_AUTOFIX=1 to enable." && exit 1)
endef

define require_unattended
	@test "$$CI" = "true" -o -n "$$DEPLOY_CI" -o "$$BACK_OFFICE_ENABLE_UNATTENDED" = "1" || (echo "Unattended workflows are disabled by default for local use. Set BACK_OFFICE_ENABLE_UNATTENDED=1 to enable." && exit 1)
endef

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

setup: ## Initial setup (create configs, check prerequisites)
	bash scripts/setup.sh

regression: ## Run portfolio regression tests + coverage (best-effort)
	python3 -m backoffice regression

# ── QA Department ─────────────────────────────────────────────────────────────

qa: ## Run QA scan on TARGET repo (make qa TARGET=/path/to/repo)
	@test -n "$(TARGET)" || (echo "Usage: make qa TARGET=/path/to/repo" && exit 1)
	bash agents/qa-scan.sh "$(TARGET)"

fix: ## Run fix agent on TARGET repo (make fix TARGET=/path/to/repo)
	@test -n "$(TARGET)" || (echo "Usage: make fix TARGET=/path/to/repo" && exit 1)
	$(require_auto_fix)
	bash agents/fix-bugs.sh "$(TARGET)"

watch: ## Watch for new findings and auto-fix (make watch TARGET=/path/to/repo)
	@test -n "$(TARGET)" || (echo "Usage: make watch TARGET=/path/to/repo" && exit 1)
	$(require_unattended)
	$(require_auto_fix)
	bash agents/watch.sh "$(TARGET)" --auto-fix --rescan $(if $(INTERVAL),--interval "$(INTERVAL)",)

og-remediate: ## Generate OG images, favicons, and fix meta tags (make og-remediate TARGET=/path/to/repo)
	@test -n "$(TARGET)" || (echo "Usage: make og-remediate TARGET=/path/to/repo" && exit 1)
	bash agents/og-remediation.sh "$(TARGET)"

scan-and-fix: ## Run full cycle: scan then fix (make scan-and-fix TARGET=/path/to/repo)
	@test -n "$(TARGET)" || (echo "Usage: make scan-and-fix TARGET=/path/to/repo" && exit 1)
	$(require_auto_fix)
	bash agents/qa-scan.sh "$(TARGET)"
	bash agents/fix-bugs.sh "$(TARGET)"
	python3 -m backoffice refresh

# ── SEO Department ────────────────────────────────────────────────────────────

seo: ## Run SEO audit on TARGET repo (make seo TARGET=/path/to/repo)
	@test -n "$(TARGET)" || (echo "Usage: make seo TARGET=/path/to/repo" && exit 1)
	bash agents/seo-audit.sh "$(TARGET)"

# ── ADA Compliance ────────────────────────────────────────────────────────────

ada: ## Run ADA compliance audit on TARGET repo (make ada TARGET=/path/to/repo)
	@test -n "$(TARGET)" || (echo "Usage: make ada TARGET=/path/to/repo" && exit 1)
	bash agents/ada-audit.sh "$(TARGET)"

# ── Regulatory Compliance ─────────────────────────────────────────────────────

compliance: ## Run compliance audit on TARGET (make compliance TARGET=/path/to/repo)
	@test -n "$(TARGET)" || (echo "Usage: make compliance TARGET=/path/to/repo" && exit 1)
	bash agents/compliance-audit.sh "$(TARGET)"

# ── Monetization Department ───────────────────────────────────────────────────

monetization: ## Run monetization audit on TARGET (make monetization TARGET=/path/to/repo)
	@test -n "$(TARGET)" || (echo "Usage: make monetization TARGET=/path/to/repo" && exit 1)
	bash agents/monetization-audit.sh "$(TARGET)"

# ── Product Roadmap Department ────────────────────────────────────────────────

product: ## Run product roadmap audit on TARGET (make product TARGET=/path/to/repo)
	@test -n "$(TARGET)" || (echo "Usage: make product TARGET=/path/to/repo" && exit 1)
	bash agents/product-audit.sh "$(TARGET)"

# ── Cloud Ops Department ─────────────────────────────────────────────────────

cloud-ops: ## Run Cloud Ops (Well-Architected Review) on TARGET (make cloud-ops TARGET=/path/to/repo)
	@test -n "$(TARGET)" || (echo "Usage: make cloud-ops TARGET=/path/to/repo" && exit 1)
	bash agents/cloud-ops-audit.sh "$(TARGET)"

# ── Company-Wide ──────────────────────────────────────────────────────────────

audit-all: ## Run ALL audits sequentially on TARGET repo
	@test -n "$(TARGET)" || (echo "Usage: make audit-all TARGET=/path/to/repo" && exit 1)
	@echo "╔══════════════════════════════════════════════════════════╗"
	@echo "║  Cody Jo Method — Full Company Audit                    ║"
	@echo "╚══════════════════════════════════════════════════════════╝"
	@echo ""
	@echo "Running all department audits on: $(TARGET)"
	@echo "Progress: http://localhost:8070"
	@echo ""
	bash scripts/job-status.sh init "$(TARGET)" "qa seo ada compliance monetization product cloud-ops"
	bash agents/qa-scan.sh "$(TARGET)"
	bash agents/seo-audit.sh "$(TARGET)"
	bash agents/ada-audit.sh "$(TARGET)"
	bash agents/compliance-audit.sh "$(TARGET)"
	bash agents/monetization-audit.sh "$(TARGET)"
	bash agents/product-audit.sh "$(TARGET)"
	bash agents/cloud-ops-audit.sh "$(TARGET)"
	bash scripts/job-status.sh finalize
	python3 -m backoffice refresh
	@echo ""
	@echo "All audits complete. Dashboard refreshed locally."

audit-all-parallel: ## Run ALL audits in parallel (2 waves of 3)
	@test -n "$(TARGET)" || (echo "Usage: make audit-all-parallel TARGET=/path/to/repo" && exit 1)
	@echo "╔══════════════════════════════════════════════════════════╗"
	@echo "║  Cody Jo Method — Full Company Audit (Parallel)         ║"
	@echo "╚══════════════════════════════════════════════════════════╝"
	@echo ""
	@echo "Running all department audits in parallel on: $(TARGET)"
	@echo "Progress: http://localhost:8070"
	@echo ""
	bash scripts/job-status.sh init "$(TARGET)" "qa seo ada compliance monetization product cloud-ops"
	bash agents/qa-scan.sh "$(TARGET)" & \
	bash agents/seo-audit.sh "$(TARGET)" & \
	bash agents/ada-audit.sh "$(TARGET)" & \
	bash agents/cloud-ops-audit.sh "$(TARGET)" & \
	wait
	bash agents/compliance-audit.sh "$(TARGET)" & \
	bash agents/monetization-audit.sh "$(TARGET)" & \
	bash agents/product-audit.sh "$(TARGET)" & \
	wait
	bash scripts/job-status.sh finalize
	python3 -m backoffice refresh
	@echo ""
	@echo "All audits complete. Dashboard refreshed locally."

full-scan: ## Run all audits + auto-fix (make full-scan TARGET=/path/to/repo)
	@test -n "$(TARGET)" || (echo "Usage: make full-scan TARGET=/path/to/repo" && exit 1)
	$(require_auto_fix)
	$(MAKE) audit-all TARGET="$(TARGET)"
	bash agents/fix-bugs.sh "$(TARGET)"
	python3 -m backoffice refresh

audit-live: ## Run ALL audits with live dashboard refresh after each (make audit-live TARGET=/path/to/repo)
	@test -n "$(TARGET)" || (echo "Usage: make audit-live TARGET=/path/to/repo" && exit 1)
	$(require_remote_sync)
	@REPO_NAME=$$(basename "$(TARGET)") && \
	echo "╔══════════════════════════════════════════════════════════╗" && \
	echo "║  Cody Jo Method — Live Audit (auto-refresh dashboard)  ║" && \
	echo "╚══════════════════════════════════════════════════════════╝" && \
	echo "" && \
	echo "Target: $(TARGET)" && \
	echo "Repo:   $$REPO_NAME" && \
	echo "Dashboard updates live after each department completes." && \
	echo "" && \
	echo "── Deploying HTML dashboards ──" && \
	bash scripts/quick-sync.sh all "$$REPO_NAME" 2>/dev/null; \
	echo "" && \
	echo "── Wave 1: QA + SEO + ADA + Cloud Ops (parallel) ──" && \
	( bash agents/qa-scan.sh "$(TARGET)" && echo "  QA done — syncing..." && bash scripts/quick-sync.sh qa "$$REPO_NAME" ) & \
	( bash agents/seo-audit.sh "$(TARGET)" && echo "  SEO done — syncing..." && bash scripts/quick-sync.sh seo "$$REPO_NAME" ) & \
	( bash agents/ada-audit.sh "$(TARGET)" && echo "  ADA done — syncing..." && bash scripts/quick-sync.sh ada "$$REPO_NAME" ) & \
	( bash agents/cloud-ops-audit.sh "$(TARGET)" && echo "  Cloud Ops done — syncing..." && bash scripts/quick-sync.sh cloud-ops "$$REPO_NAME" ) & \
	wait && \
	echo "" && \
	echo "── Wave 2: Compliance + Monetization + Product (parallel) ──" && \
	( bash agents/compliance-audit.sh "$(TARGET)" && echo "  Compliance done — syncing..." && bash scripts/quick-sync.sh compliance "$$REPO_NAME" ) & \
	( bash agents/monetization-audit.sh "$(TARGET)" && echo "  Monetization done — syncing..." && bash scripts/quick-sync.sh monetization "$$REPO_NAME" ) & \
	( bash agents/product-audit.sh "$(TARGET)" && echo "  Product done — syncing..." && bash scripts/quick-sync.sh product "$$REPO_NAME" ) & \
	wait && \
	echo "" && \
	echo "All audits complete. Dashboard updated live at each step."

quick-sync: ## Quick-sync one department's data (make quick-sync DEPT=qa REPO=codyjo.com)
	python3 -m backoffice sync --dept $(DEPT)

# ── Tests ─────────────────────────────────────────────────────────────────────

test: ## Run scoring tests (pre-deploy gate)
	python3 -m pytest tests/ -v

test-coverage: ## Run regression tests with Python line coverage reporting
	python3 -m pytest tests/ --cov=backoffice --cov-report=term --cov-report=xml --cov-report=json:coverage.json

local-targets: ## List configured local audit targets
	python3 -m backoffice list-targets

local-refresh: ## Refresh local dashboard data + audit log from existing results
	python3 -m backoffice refresh

local-audit: ## Run local audit for a configured target (make local-audit TARGET_NAME=selah DEPTS=product,qa)
	@test -n "$(TARGET_NAME)" || (echo "Usage: make local-audit TARGET_NAME=<name> [DEPTS=qa,product]" && exit 1)
	python3 -m backoffice audit $(TARGET_NAME) $(if $(DEPTS),--departments "$(DEPTS)",)

local-audit-all: ## Run local audits for all configured targets
	python3 -m backoffice audit-all $(if $(TARGETS),--targets "$(TARGETS)",) $(if $(DEPTS),--departments "$(DEPTS)",)

self-audit-local: ## Run the Back Office self-audit and refresh the local dashboard
	python3 scripts/local_audit_workflow.py run-target --target back-office --departments qa

# ── Dashboard & Infrastructure ────────────────────────────────────────────────

dashboard: ## Deploy all dashboards to Bunny Storage
	$(require_remote_sync)
	python3 -m backoffice sync

scaffold-workflows: ## Scaffold GitHub Actions into a configured target (make scaffold-workflows TARGET_NAME=selah)
	@test -n "$(TARGET_NAME)" || (echo "Usage: make scaffold-workflows TARGET_NAME=<name>" && exit 1)
	python3 scripts/scaffold-github-workflows.py --target "$(TARGET_NAME)"

cli: ## Run the Back Office CLI (make cli CMD="list-targets")
	@test -n "$(CMD)" || (echo "Usage: make cli CMD=\"list-targets\"" && exit 1)
	python3 -m backoffice $(CMD)

jobs: ## Start dashboard server with scan API (make jobs TARGET=/path/to/repo)
	python3 -m backoffice serve --port 8070

grafana: ## Start Grafana monitoring dashboard (alias for monitoring-up)
	$(MAKE) monitoring-up

grafana-stop: ## Stop Grafana (alias for monitoring-down)
	$(MAKE) monitoring-down

grafana-logs: ## Tail Grafana logs
	cd monitoring && docker compose logs -f grafana

# ── Monitoring Stack ─────────────────────────────────────────

monitoring-up: ## Start full monitoring stack (Vector + TimescaleDB + Grafana)
	cd monitoring && docker compose up -d
	@echo "Monitoring stack starting..."
	@echo "  Grafana:     http://localhost:3333"
	@echo "  TimescaleDB: localhost:5433"
	@echo "  Vector API:  http://localhost:8686"
	@echo "  Ingest API:  http://localhost:8087"

monitoring-pull: ## Pre-pull monitoring stack images without starting containers
	cd monitoring && docker compose pull

monitoring-down: ## Stop monitoring stack
	cd monitoring && docker compose down

monitoring-logs: ## Tail monitoring stack logs
	cd monitoring && docker compose logs -f

monitoring-status: ## Health check all monitoring services
	@echo "=== Monitoring Stack Status ==="
	@echo -n "TimescaleDB: " && (docker exec breakpoint-timescaledb pg_isready -U vector -d monitoring 2>/dev/null && echo "OK") || echo "DOWN"
	@echo -n "Ingest:      " && (curl -sf http://localhost:8087/health | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])" 2>/dev/null) || echo "DOWN"
	@echo -n "Vector:      " && (curl -sf http://localhost:8686/health | python3 -c "import sys,json; d=json.load(sys.stdin); print('OK' if d.get('ok') else 'DOWN')" 2>/dev/null) || echo "DOWN"
	@echo -n "Grafana:     " && (curl -sf http://localhost:3333/api/health | python3 -c "import sys,json; print(json.load(sys.stdin).get('database','DOWN'))" 2>/dev/null) || echo "DOWN"

monitoring-restart: ## Restart monitoring stack
	cd monitoring && docker compose restart

monitoring-test: ## Run monitoring stack smoke test
	bash monitoring/scripts/smoke-test.sh

# ── Forgejo (Local Git Forge) ────────────────────────────────

forgejo-up: ## Start Forgejo local git server
	cd ops/forgejo-local && docker compose up -d
	@echo "Forgejo running at http://borg.local:3300"

forgejo-down: ## Stop Forgejo
	cd ops/forgejo-local && docker compose down

forgejo-mirror: ## Mirror a local repo to Forgejo (make forgejo-mirror REPO=selah)
	@test -n "$(REPO)" || (echo "Usage: make forgejo-mirror REPO=<target-name>" && exit 1)
	@REPO_PATH=$$(python3 -c "import yaml; ts=yaml.safe_load(open('config/targets.yaml')); t=[x for x in ts.get('targets',[]) if x['name']=='$(REPO)']; print(t[0]['path'] if t else '')" 2>/dev/null) && \
	test -n "$$REPO_PATH" || (echo "Target '$(REPO)' not found in targets.yaml" && exit 1) && \
	cd "$$REPO_PATH" && \
	(git remote get-url forgejo 2>/dev/null || git remote add forgejo http://borg.local:3300/merm/$(REPO).git) && \
	git push forgejo --all && \
	echo "Pushed $$REPO_PATH to Forgejo"

# ── Overnight Loop ───────────────────────────────────────────────────────────

overnight: ## Start overnight autonomous loop
	$(require_unattended)
	@echo "Starting overnight loop... Stop with: make overnight-stop"
	bash scripts/overnight.sh $(if $(INTERVAL),--interval "$(INTERVAL)",) $(if $(TARGETS),--targets "$(TARGETS)",) 2>&1 | tee -a results/overnight.log

overnight-dry: ## Dry-run overnight (audit + decide only, no changes)
	$(require_unattended)
	bash scripts/overnight.sh --dry-run $(if $(INTERVAL),--interval "$(INTERVAL)",) $(if $(TARGETS),--targets "$(TARGETS)",) 2>&1 | tee -a results/overnight.log

overnight-stop: ## Stop overnight loop gracefully
	$(require_unattended)
	@touch results/.overnight-stop && echo "Stop signal sent. Loop will exit after current phase."

overnight-status: ## Show overnight status and history
	$(require_unattended)
	@echo "=== Latest Plan ==="
	@python3 -c "import json,os; p='results/overnight-plan.json'; d=json.load(open(p)) if os.path.exists(p) else {}; print(f'Plan: {len(d.get(\"fixes\",[]))} fixes, {len(d.get(\"features\",[]))} features'); print(d.get('rationale','(no plan)'))" 2>/dev/null || echo "(no plan)"
	@echo ""
	@echo "=== Last 5 Cycles ==="
	@python3 -c "import json,os; p='results/overnight-history.json'; d=json.load(open(p)) if os.path.exists(p) else {'cycles':[]}; [print(f'{c[\"cycle_id\"]}: {c.get(\"fixes_succeeded\",0)} fixes, {c.get(\"features_succeeded\",0)} features, {c.get(\"deploys_succeeded\",0)} deploys') for c in d['cycles'][-5:]]" 2>/dev/null || echo "(no history)"

overnight-rollback: ## Roll back all repos to last overnight snapshot
	$(require_unattended)
	@echo "Rolling back all repos to latest overnight snapshot..."
	@python3 -c "\
	import yaml, subprocess, os; \
	targets = yaml.safe_load(open('config/targets.yaml')).get('targets', []); \
	[( \
	    result := subprocess.run(['git', 'tag', '-l', 'overnight-before-*'], capture_output=True, text=True, cwd=t['path']), \
	    tags := sorted([x for x in result.stdout.strip().split(chr(10)) if x]), \
	    (subprocess.run(['git', 'reset', '--hard', tags[-1]], cwd=t['path']) or print(f'  {t[\"name\"]}: rolled back to {tags[-1]}')) if tags else print(f'  {t[\"name\"]}: no snapshot tag found') \
	) for t in targets if os.path.isdir(t.get('path', ''))]" 2>/dev/null || echo "(rollback failed — check targets.yaml)"

clean: ## Remove all results
	rm -rf results/*/
	rm -f dashboard/data.json dashboard/qa-data.json dashboard/seo-data.json dashboard/ada-data.json dashboard/compliance-data.json dashboard/monetization-data.json dashboard/product-data.json dashboard/cloud-ops-data.json
	@echo "Results cleaned."
