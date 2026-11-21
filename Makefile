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
scaffold-smoke: readers-check
	cargo test --locked --test output_contract
