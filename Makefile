PYTHON ?= python3
PY_DIRS := scripts tests agent labels evidence policy

.PHONY: check lint test verify hooks demo

# Repo rules, the policy and the secret scan. Runs before every commit once the hooks are installed.
check:
	@$(PYTHON) scripts/validate_repo.py
	@$(PYTHON) policy/policy.py
	@$(PYTHON) scripts/scan_secrets.py --all

# Every Python file must at least compile.
lint:
	@$(PYTHON) -m compileall -q $(PY_DIRS)

# Laptop tests: no model, no Slack, no network.
test:
	@$(PYTHON) -m unittest discover -s tests -p 'test_*.py'

# The gate. CI runs it on every push and pull request; the pre-push hook runs it locally.
verify: check lint test
	@git diff --check

hooks:
	@sh scripts/install-hooks.sh

# The demo farm with today's dates, read by the fake model. See demo/README.md.
demo:
	@$(PYTHON) scripts/demo.py
