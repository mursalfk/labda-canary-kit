# lambda-canary-kit/Makefile
# Every target is a thin wrapper around a plain command, so nothing here is magic.
# No `make` (Windows)? The commands are listed in instructions.md.
PY ?= python3
SIZE_BUDGET_MB ?= 0
COLD_START_BUDGET_MS ?= 0
PLATFORM ?= linux/amd64
STACK ?= canary-kit

.PHONY: install test train build-slim build-bloated report gate smoke deploy ship-bad ship-good traffic watch cold-samples simulate-bad simulate-good simulate-quiet evidence destroy

install:
	$(PY) -m pip install -r requirements-dev.txt

test:
	$(PY) -m pytest -q

train:
	$(PY) -m pip install -r requirements-train.txt
	$(PY) train/train_model.py

build-slim:
	docker build --platform $(PLATFORM) -f docker/Dockerfile.slim -t canary-kit:slim .

build-bloated:
	docker build --platform $(PLATFORM) -f docker/Dockerfile.bloated -t canary-kit:bloated .

report: build-bloated build-slim
	$(PY) tools/size_report.py canary-kit:bloated canary-kit:slim

gate: build-slim
	$(PY) tools/size_gate.py canary-kit:slim --budget-mb $(SIZE_BUDGET_MB)

smoke: build-slim
	$(PY) tools/cold_start_smoke.py canary-kit:slim --max-cold-ms $(COLD_START_BUDGET_MS)

# usage: make deploy RELEASE=v2
deploy:
	$(PY) tools/deploy.py --release $(RELEASE) --stack $(STACK)

ship-bad:
	$(PY) tools/release.py bad

ship-good:
	$(PY) tools/release.py good

# usage: make traffic FUNCTION=<FunctionName output>
traffic:
	$(PY) tools/traffic.py --function $(FUNCTION) --seconds 600 --rps 4

watch:
	$(PY) tools/watch_deploy.py --stack $(STACK)

# usage: make cold-samples FUNCTION=<FunctionName output of the comparison stack>
cold-samples:
	$(PY) tools/cold_samples.py --function $(FUNCTION) --samples 10

# Runs every free local step and saves each output to evidence/. Send evidence/ALL-evidence.txt.
evidence:
	$(PY) tools/collect_evidence.py

# Free, local, no AWS. Real handler, simulated router and alarm.
simulate-bad:
	$(PY) tools/local_canary.py --candidate bad

simulate-good:
	$(PY) tools/local_canary.py --candidate good

simulate-quiet:
	$(PY) tools/local_canary.py --candidate bad --requests-per-minute 0

destroy:
	sam delete --stack-name $(STACK) --no-prompts
	-sam delete --stack-name $(STACK)-bloated --no-prompts
	aws ecr delete-repository --repository-name canary-kit --force
