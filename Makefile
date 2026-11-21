IMAGE ?= shopping-sessions:latest
PLATFORM ?= linux/amd64
WORK ?= work
PY ?= $(WORK)/venv/bin/python
BIN ?= target/quick/shopping-sessions
ANSWER ?= .local/dev-answer
export POLARS_MAX_THREADS ?= 2
export NCPU ?= 8
.PHONY: build native venv generator dev fixtures-native fixtures oracle-fixtures oracle-dev check-dev
build:
	docker buildx build --platform $(PLATFORM) --load -t $(IMAGE) .
native:
	cargo build --locked --profile quick
venv:
	uv venv --allow-existing --python 3.12 $(WORK)/venv
	uv pip install --python $(PY) -r requirements-dev.txt
generator:
	tools/generator/build.sh
dev: generator
	$(WORK)/generator/bin/generate --seed 1 --events 1000000 --clicks 250000 --threads 2 --output $(WORK)/dev
fixtures-native: native
	@for mode in simple fast; do for suite in fixtures fixtures-extra; do SS_MODE=$$mode $(PY) scripts/run_fixtures.py testdata/$$suite -- $(BIN) || exit 1; done; done
fixtures: build
	@for suite in fixtures fixtures-extra; do IMAGE=$(IMAGE) $(PY) scripts/run_fixtures.py testdata/$$suite -- scripts/docker_run.sh || exit 1; done
oracle-fixtures:
	@for suite in fixtures fixtures-extra; do $(PY) scripts/run_fixtures.py testdata/$$suite -- $(PY) oracle/oracle.py || exit 1; done
oracle-dev: dev
	@out=$$(mktemp -d "$(WORK)/oracle-dev.XXXXXX") && $(PY) oracle/oracle.py $(WORK)/dev $$out && $(PY) scripts/compare.py $(ANSWER) $$out
check-dev: build dev
	@out=$$(mktemp -d "$(WORK)/check-dev.XXXXXX") && IMAGE=$(IMAGE) scripts/docker_run.sh $(WORK)/dev $$out && $(PY) scripts/compare.py $(ANSWER) $$out
.PHONY: readers-check scaffold-smoke
readers-check: native
	$(PY) tools/check_outputs.py $(BIN)
scaffold-smoke: readers-check build
	IMAGE=$(IMAGE) $(PY) tools/check_outputs.py tools/container_run.sh
	cargo test --locked --test output_contract

.PHONY: diff leaf-corpus mutation-check diag bench
MODES ?= simple,fast
LEVELS ?= T2
diag:
	cargo build --profile quick --locked --features diag
	cp target/quick/shopping-sessions $(WORK)/shopping-diag
leaf-corpus: diag
	$(PY) tools/leaf_corpus.py $(WORK)/shopping-diag
mutation-check:
	cargo build --profile quick --locked --no-default-features --features mutate
	cp target/quick/shopping-sessions $(WORK)/shopping-mutate
	$(PY) tools/symptoms.py --bin $(WORK)/shopping-mutate --output $(WORK)/mutations.json
diff: native generator
	$(PY) tools/differential.py --bin $(BIN) --levels $(LEVELS) --modes $(MODES) --output $(WORK)/diff.json
bench:
	$(PY) tools/bench.py native --runs 3 -- $(CMD)

.PHONY: fuzz miri
fuzz:
	tools/fuzz.sh
miri:
	cargo +nightly miri test --locked --test miri_small

.PHONY: registry-oracle registry-full generator-check metamorph rows-oracle sample-oracle scan-bench
DATA ?= testdata/fixtures/A11/input
DIAG_BIN ?= $(WORK)/shopping-diag
registry-oracle:
	$(PY) tools/check_registry.py --scope oracle
registry-full:
	$(PY) tools/check_registry.py --scope full
generator-check: generator
	$(PY) tools/generator/check.py
metamorph: diag
	$(PY) tools/metamorph.py $(DATA) --bin $(DIAG_BIN)
rows-oracle sample-oracle: diag
	cargo build --profile quick --locked
	@for m in simple fast; do $(PY) tools/diagnose.py $(DATA) --diag $(DIAG_BIN) --release $(BIN) --mode $$m --kind $(if $(filter rows-oracle,$@),rows,sample) || exit 1; done
scan-bench: diag
	$(PY) tools/scan_bench.py $(DATA) --bin $(DIAG_BIN) --receipt $(WORK)/scan.json

.PHONY: presubmit qualify-simple qualify-fast
TAG ?=
MODE ?= fast
SCOPE ?= bounded
presubmit:
	$(PY) tools/qualification.py $(if $(TAG),--tag "$(TAG)") --mode "$(MODE)" --scope "$(SCOPE)" $(if $(IMAGE_RECEIPT),--image-receipt "$(IMAGE_RECEIPT)") $(if $(LARGE_RECEIPTS),--large-receipts $(LARGE_RECEIPTS)) $(if $(DIAGNOSTIC_RECEIPTS),--diagnostic-receipts $(DIAGNOSTIC_RECEIPTS))
qualify-simple: registry-full oracle-fixtures
	$(MAKE) presubmit MODE=simple
qualify-fast: registry-full oracle-fixtures leaf-corpus mutation-check
	$(MAKE) presubmit MODE=fast
