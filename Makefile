.PHONY: setup qa fix watch dashboard clean help jobs test test-coverage scaffold-workflows cli regression
.PHONY: seo ada compliance monetization product cloud-ops audit-all audit-all-parallel audit-live full-scan quick-sync
.PHONY: grafana grafana-stop grafana-logs
.PHONY: local-targets local-refresh local-audit local-audit-all self-audit-local
.PHONY: overnight overnight-dry overnight-stop overnight-status overnight-rollback

TARGET ?=

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
	bash agents/fix-bugs.sh "$(TARGET)"

watch: ## Watch for new findings and auto-fix (make watch TARGET=/path/to/repo)
	@test -n "$(TARGET)" || (echo "Usage: make watch TARGET=/path/to/repo" && exit 1)
	bash agents/watch.sh "$(TARGET)" --auto-fix --sync --rescan $(if $(INTERVAL),--interval "$(INTERVAL)",)

scan-and-fix: ## Run full cycle: scan then fix (make scan-and-fix TARGET=/path/to/repo)
	@test -n "$(TARGET)" || (echo "Usage: make scan-and-fix TARGET=/path/to/repo" && exit 1)
	bash agents/qa-scan.sh "$(TARGET)" --sync
	bash agents/fix-bugs.sh "$(TARGET)" --sync

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
	@echo "Progress: http://localhost:8070/jobs.html"
	@echo ""
	bash scripts/job-status.sh init "$(TARGET)" "qa seo ada compliance monetization product cloud-ops"
	bash agents/qa-scan.sh "$(TARGET)" --sync
	bash agents/seo-audit.sh "$(TARGET)" --sync
	bash agents/ada-audit.sh "$(TARGET)" --sync
	bash agents/compliance-audit.sh "$(TARGET)" --sync
	bash agents/monetization-audit.sh "$(TARGET)" --sync
	bash agents/product-audit.sh "$(TARGET)" --sync
	bash agents/cloud-ops-audit.sh "$(TARGET)" --sync
	bash scripts/job-status.sh finalize
	bash scripts/sync-dashboard.sh 2>/dev/null || true
	@echo ""
	@echo "All audits complete. Dashboard deployed."

audit-all-parallel: ## Run ALL audits in parallel (2 waves of 3)
	@test -n "$(TARGET)" || (echo "Usage: make audit-all-parallel TARGET=/path/to/repo" && exit 1)
	@echo "╔══════════════════════════════════════════════════════════╗"
	@echo "║  Cody Jo Method — Full Company Audit (Parallel)         ║"
	@echo "╚══════════════════════════════════════════════════════════╝"
	@echo ""
	@echo "Running all department audits in parallel on: $(TARGET)"
	@echo "Progress: http://localhost:8070/jobs.html"
	@echo ""
	bash scripts/job-status.sh init "$(TARGET)" "qa seo ada compliance monetization product cloud-ops"
	bash agents/qa-scan.sh "$(TARGET)" --sync & \
	bash agents/seo-audit.sh "$(TARGET)" --sync & \
	bash agents/ada-audit.sh "$(TARGET)" --sync & \
	bash agents/cloud-ops-audit.sh "$(TARGET)" --sync & \
	wait
	bash agents/compliance-audit.sh "$(TARGET)" --sync & \
	bash agents/monetization-audit.sh "$(TARGET)" --sync & \
	bash agents/product-audit.sh "$(TARGET)" --sync & \
	wait
	bash scripts/job-status.sh finalize
	bash scripts/sync-dashboard.sh 2>/dev/null || true
	@echo ""
	@echo "All audits complete. Dashboard deployed."

full-scan: ## Run all audits + auto-fix (make full-scan TARGET=/path/to/repo)
	@test -n "$(TARGET)" || (echo "Usage: make full-scan TARGET=/path/to/repo" && exit 1)
	$(MAKE) audit-all TARGET="$(TARGET)"
	bash agents/fix-bugs.sh "$(TARGET)" --sync

audit-live: ## Run ALL audits with live dashboard refresh after each (make audit-live TARGET=/path/to/repo)
	@test -n "$(TARGET)" || (echo "Usage: make audit-live TARGET=/path/to/repo" && exit 1)
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

local-audit: ## Run local audit for a configured target (make local-audit TARGET_NAME=bible-app DEPTS=product,qa)
	@test -n "$(TARGET_NAME)" || (echo "Usage: make local-audit TARGET_NAME=<name> [DEPTS=qa,product]" && exit 1)
	python3 -m backoffice audit $(TARGET_NAME) $(if $(DEPTS),--departments "$(DEPTS)",)

local-audit-all: ## Run local audits for all configured targets
	python3 -m backoffice audit-all $(if $(TARGETS),--targets "$(TARGETS)",) $(if $(DEPTS),--departments "$(DEPTS)",)

self-audit-local: ## Run the Back Office self-audit and refresh the local dashboard
	python3 scripts/local_audit_workflow.py run-target --target back-office --departments qa

# ── Dashboard & Infrastructure ────────────────────────────────────────────────

dashboard: ## Deploy all dashboards to S3
	python3 -m backoffice sync

scaffold-workflows: ## Scaffold GitHub Actions into a configured target (make scaffold-workflows TARGET_NAME=bible-app)
	@test -n "$(TARGET_NAME)" || (echo "Usage: make scaffold-workflows TARGET_NAME=<name>" && exit 1)
	python3 scripts/scaffold-github-workflows.py --target "$(TARGET_NAME)"

cli: ## Run the Back Office CLI (make cli CMD="list-targets")
	@test -n "$(CMD)" || (echo "Usage: make cli CMD=\"list-targets\"" && exit 1)
	python3 -m backoffice $(CMD)

jobs: ## Start dashboard server with scan API (make jobs TARGET=/path/to/repo)
	python3 -m backoffice serve --port 8070

grafana: ## Start Grafana monitoring dashboard
	cd monitoring && docker compose up -d
	@echo "Grafana running at http://localhost:3333 (set GRAFANA_ADMIN_PASSWORD env var)"

grafana-stop: ## Stop Grafana
	cd monitoring && docker compose down

grafana-logs: ## Tail Grafana logs
	cd monitoring && docker compose logs -f grafana

# ── Overnight Loop ───────────────────────────────────────────────────────────

overnight: ## Start overnight autonomous loop
	@echo "Starting overnight loop... Stop with: make overnight-stop"
	bash scripts/overnight.sh $(if $(INTERVAL),--interval "$(INTERVAL)",) $(if $(TARGETS),--targets "$(TARGETS)",) 2>&1 | tee -a results/overnight.log

overnight-dry: ## Dry-run overnight (audit + decide only, no changes)
	bash scripts/overnight.sh --dry-run $(if $(INTERVAL),--interval "$(INTERVAL)",) $(if $(TARGETS),--targets "$(TARGETS)",) 2>&1 | tee -a results/overnight.log

overnight-stop: ## Stop overnight loop gracefully
	@touch results/.overnight-stop && echo "Stop signal sent. Loop will exit after current phase."

overnight-status: ## Show overnight status and history
	@echo "=== Latest Plan ==="
	@python3 -c "import json,os; p='results/overnight-plan.json'; d=json.load(open(p)) if os.path.exists(p) else {}; print(f'Plan: {len(d.get(\"fixes\",[]))} fixes, {len(d.get(\"features\",[]))} features'); print(d.get('rationale','(no plan)'))" 2>/dev/null || echo "(no plan)"
	@echo ""
	@echo "=== Last 5 Cycles ==="
	@python3 -c "import json,os; p='results/overnight-history.json'; d=json.load(open(p)) if os.path.exists(p) else {'cycles':[]}; [print(f'{c[\"cycle_id\"]}: {c.get(\"fixes_succeeded\",0)} fixes, {c.get(\"features_succeeded\",0)} features, {c.get(\"deploys_succeeded\",0)} deploys') for c in d['cycles'][-5:]]" 2>/dev/null || echo "(no history)"

overnight-rollback: ## Roll back all repos to last overnight snapshot
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
