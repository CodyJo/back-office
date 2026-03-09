.PHONY: setup qa fix watch dashboard clean help
.PHONY: seo ada compliance audit-all full-scan

TARGET ?=

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

setup: ## Initial setup (create configs, check prerequisites)
	bash scripts/setup.sh

# ── QA Department ─────────────────────────────────────────────────────────────

qa: ## Run QA scan on TARGET repo (make qa TARGET=/path/to/repo)
	@test -n "$(TARGET)" || (echo "Usage: make qa TARGET=/path/to/repo" && exit 1)
	bash agents/qa-scan.sh "$(TARGET)"

fix: ## Run fix agent on TARGET repo (make fix TARGET=/path/to/repo)
	@test -n "$(TARGET)" || (echo "Usage: make fix TARGET=/path/to/repo" && exit 1)
	bash agents/fix-bugs.sh "$(TARGET)"

watch: ## Watch for new findings and auto-fix (make watch TARGET=/path/to/repo)
	@test -n "$(TARGET)" || (echo "Usage: make watch TARGET=/path/to/repo" && exit 1)
	bash agents/watch.sh "$(TARGET)" --auto-fix --sync

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

# ── Company-Wide ──────────────────────────────────────────────────────────────

audit-all: ## Run ALL audits on TARGET repo (QA + SEO + ADA + Compliance)
	@test -n "$(TARGET)" || (echo "Usage: make audit-all TARGET=/path/to/repo" && exit 1)
	@echo "╔══════════════════════════════════════════════════════════╗"
	@echo "║  BreakPoint Labs — Full Company Audit                    ║"
	@echo "╚══════════════════════════════════════════════════════════╝"
	@echo ""
	@echo "Running all department audits on: $(TARGET)"
	@echo ""
	bash agents/qa-scan.sh "$(TARGET)" --sync
	bash agents/seo-audit.sh "$(TARGET)" --sync
	bash agents/ada-audit.sh "$(TARGET)" --sync
	bash agents/compliance-audit.sh "$(TARGET)" --sync
	@echo ""
	@echo "All audits complete. Open dashboard/index.html to view results."

full-scan: ## Run all audits + auto-fix (make full-scan TARGET=/path/to/repo)
	@test -n "$(TARGET)" || (echo "Usage: make full-scan TARGET=/path/to/repo" && exit 1)
	$(MAKE) audit-all TARGET="$(TARGET)"
	bash agents/fix-bugs.sh "$(TARGET)" --sync

# ── Dashboard & Infrastructure ────────────────────────────────────────────────

dashboard: ## Deploy all dashboards to S3
	bash scripts/sync-dashboard.sh

clean: ## Remove all results
	rm -rf results/*/
	rm -f dashboard/data.json dashboard/qa-data.json dashboard/seo-data.json dashboard/ada-data.json dashboard/compliance-data.json
	@echo "Results cleaned."
