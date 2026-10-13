# SQLite adapter validation

Validated locally on 14 October 2026 on the `sqlite-adapter` branch, using
Docker Desktop, Python 3.11 in the API image, MongoDB 7, and SQLite's built-in
Python driver. The verification stack used the separate Compose project
`object-counter-verification`.

## Test results

| Database selected | Full pytest suite | Failures / errors | Duration |
| --- | --- | --- | --- |
| MongoDB | 49 passed | 0 / 0 | 4.47 seconds |
| SQLite | 49 passed | 0 / 0 | 4.14 seconds |

The suites cover domain behavior, the HTTP API, real YOLO inference, shared
storage contracts, adapter selection, monitoring reads, failure logging,
concurrent increments, SQLite persistence and transaction rollback, and
explicit database resets. MongoDB tests use unique `counter_test_*` databases;
SQLite tests use temporary files. Each suite reported one upstream
Starlette/AnyIO deprecation warning.

Executed commands:

```bash
docker compose -p object-counter-verification --profile mongodb run --rm --no-deps \
  -e DATABASE_BACKEND=mongodb -e MODEL_PATH=tmp/models/yolov8n.pt \
  api python -m pytest tests -q --junitxml=/app/results/validation/mongodb-tests.xml

docker compose -p object-counter-verification --profile sqlite run --rm --no-deps \
  -e DATABASE_BACKEND=sqlite -e MODEL_PATH=tmp/models/yolov8n.pt \
  api python -m pytest tests -q --junitxml=/app/results/validation/sqlite-tests.xml
```

SQLite's full suite ran with the MongoDB service stopped. The test model was
the small COCO-pretrained `yolov8n.pt`, matching the existing CI approach;
validation checks API/storage behavior rather than parking-model accuracy.
The model registry was unchanged.

## Live container checks

The startup helper and `make start` were exercised with both database choices.
Both stacks reached HTTP/storage health successfully. SQLite mode ran only the
API container, with its database on a persistent Docker volume. MongoDB mode
ran the API and MongoDB containers.

For each backend, real HTTP requests using `resources/images/carlot.jpeg`
verified:

- Two counting requests accumulated the detected class totals correctly.
- A list-mode request logged history without changing cumulative counts.
- An invalid image returned HTTP 500 and stored the failure details.
- Success records retained annotated-image paths and nested count snapshots.
- Both operational dashboards generated successfully from that backend.

SQLite retained its counts and all four request-history records after an API
container restart. Switching MongoDB → SQLite → MongoDB → SQLite retained
each database's separate counts/history across service stops and API container
recreation. Both generated HTML files were inspected for the verification
session and stored class totals.

Both Compose profiles passed `docker compose config --quiet`; source parsing,
shell syntax, and `git diff --check` passed. CI now defines the same full-suite
matrix and starts its MongoDB service only for the MongoDB job. The updated
GitHub Actions workflow has not run remotely yet.

Local XML results and runtime snapshots are under `results/validation/`
(gitignored). The verification containers were stopped after the checks;
their volumes were retained. The older standalone `test-mongo` container and
its data were left untouched. Existing data is not migrated between databases
or from that legacy container into the new Compose stack.
