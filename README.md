# Databricks Shopping Sessions

The Linux/amd64 image reads an event window from `/data` and produces `/output/user_daily` and `/output/campaign_daily` as Parquet. The Rust binary performs global earliest-ingest deduplication, connected-component naming, sessionization and seven-day click attribution. The independent Python oracle uses a graph traversal, a disk-backed SQLite winner table, and explicit click-window selection.

```sh
make build
scripts/docker_run.sh /absolute/input /absolute/fresh-output
make venv generator fixtures-native oracle-fixtures
make check-dev
```

For a native run, use `cargo build --profile quick --locked`, then `target/quick/shopping-sessions INPUT FRESH_OUTPUT`. Two positional arguments override `DATA_DIR` and `OUTPUT_DIR`. The default parallel driver is `fast`. Set `SS_MODE=simple` for the comparison implementation. `NCPU`, `SS_CHUNK_BYTES`, `SS_EVENT_BUCKETS`, and `SS_PERSON_BUCKETS` control the parallel driver. Input must remain immutable until completion. Use a fresh output directory for each run.

Exit status is 0 on success, 2 for configuration, 3 for input, 4 for output, and 5–8 for failed accounting or key checks. Stderr reports the build ID, stage times, outcomes, totals and peak RSS in bytes.

The organizer's archives belong in `.local/`. Generated datasets, the virtual environment and local execution receipts belong in `work/`. The public results were **3.83 s** for `sub-001` and **2.62 s** for `sub-002`. The organizer selected `sub-002` for the final. [Submission log](spec/submissions.md) · [Timing results and raw measurements](spec/timings.md)

To reproduce the small-data measurements, prepare the public input with `make dev` and place the official answer in `.local/dev-answer`. Both commands use seven builds from the two submitted Git tags, eight workers and a fresh output directory. The Docker workload has a hard 512 MiB limit.

```sh
work/venv/bin/python tools/ablation.py native --root work/timing-native --receipt work/timing-native/receipt.json
sh tools/ablation_docker.sh work/timing-docker
make presubmit TAG=sub-002 SCOPE=bounded
```

[Verification coverage](spec/verification.md) · [Organizer's rules](spec/rules.md) · [Specification](SPEC.md)
