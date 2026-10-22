# Frontend and Roboflow validation

Validated locally on 2026-10-22 on `frontend-feature`, based on merged `main` commit `b31684f` (SQLite PR #1). No files under `model_management/`, training defaults, promotion rules, or model weights were changed.

## Delivered behavior

- Same-origin, responsive dark-purple frontend at `/`, served by the existing FastAPI process; `make start` runs the app and API together.
- Local YOLO or Roboflow workflow/hosted detection model; the Roboflow form defaults to hosted model `parking-detection-ewm7h/3`. Workflow defaults use `model-version2/parking-detection-v3-logic`, image input `image`, output `predictions`.
- Eight included samples, JPEG/PNG uploads, up to 20 images in a sequential queue, per-image failures, stop after the current image, inspect prior results, and download annotations.
- Interactive SVG boxes with dimmed surroundings and prominent class/confidence labels on hover, keyboard focus, or tap. Per-image counts, mean confidence, request latency, and batch summaries.
- Persistent counters by session/class with load/new controls and separate initial local/cloud session IDs. Counts mean detections across submissions; repeated images count again.
- Local/cloud request records use the same storage and dashboards, with provider labels on session cards. Dashboard links regenerate the existing reports.
- Original `/object-detection` list/count response shapes retained; richer `/api/detect` used by the frontend. Dependency-free `scripts/predict_image.py` submits one or multiple paths.

## Executed checks

| Check | Result |
|---|---|
| `make start` on existing cached image with SQLite | Healthy API and frontend on `127.0.0.1:5000`; runtime files mounted from current checkout |
| `make test_frontend` (Playwright, isolated simulated API) | **26 passed**: 13 behavior scenarios at 1440×900 desktop and 390×844 phone; no Roboflow calls or database writes |
| `make test` after final tests | **88 passed**, one upstream Starlette/AnyIO deprecation warning |
| Full MongoDB suite on final sources | **88 passed**, same deprecation warning; test databases isolated and removed |
| Real local YOLO via frontend | `carlot.jpeg`: 8 detections, 7 car / 1 free; box focus, confidence, latency and download URL verified |
| Real hosted model `parking-detection-ewm7h/3` through the app API | `carlot.jpeg`: **9 detections**, 8 car / 1 free, HTTP 200; accumulation disabled |
| Real Roboflow workflow via isolated browser batch | `carlot.jpeg` + `carpark2.jpeg`: 8 + 52 = **60 detections**, persisted totals 29 car / 31 free; connected status and focused box verified |
| Real Roboflow workflow via path-based Python client | `carlot.jpeg` + `carpark.jpeg`: 8 + 58 = **66 detections**, persisted totals 53 car / 13 free |
| `/dashboards/monitoring_dashboard.html` and `/dashboards/session_dashboard.html` | HTTP 200, generated from live history; cloud session, provider and embedded annotated JPEG present |
| Restart and browser reload | Previously counted session restored with its persisted totals |
| Layout | Automated browser checks at 1440×900 and 390×844, plus manual browser inspection at 1280, 541 and 675 px; no horizontal overflow observed |
| Source diff and secrets | `git diff --check` clean; supplied key only in ignored private `.env` |

Upload checks cover valid sample decoding, oversize bodies/files, dimensions/pixels, malformed content, unsupported formats, animated PNG rejection, EXIF orientation/metadata stripping, filename/session traversal, invalid thresholds, and cross-origin posts. Roboflow adapter checks cover header-only credentials, fixed origins, redirect refusal, coordinate conversion/rescaling, nested outputs, empty detections, invalid schemas, and safe upstream errors. Provider failures leave counts unchanged.

## Limits and boundaries

- The supplied parking workflow and hosted model `parking-detection-ewm7h/3` were both verified live with the configured server key. Other accounts/deployments still require their own valid identifiers and access.
- The app is a local workspace without user authentication. Session IDs do not authorize access. Keep the loopback binding unless adding authenticated HTTPS access and deployment quotas.
- Valid images are canonicalized to JPEG before inference. No arbitrary server image paths, remote image URLs, or custom inference hosts are accepted. Workflow boxes must reference the original image or a uniformly resized image with dimensions; unreported crops/rotations need explicit normalization in the workflow.
- Results and monitoring history are retained; no automatic retention policy is implemented. Browser queue/result state is transient; persisted session counters survive reloads/restarts.
- Existing cached runtime dependencies were reused. A fresh dependency-image rebuild was started, then canceled once source mounts provided the current app; no successful fresh image rebuild is claimed.

Browser proof: `tmp/frontend/roboflow-focus.png` (local ignored artifact).

## Repeatable frontend checks

`package.json` and `pnpm-lock.yaml` pin the test-only Playwright dependency. Install Node.js 24/pnpm 11.25.0, then run `pnpm install --frozen-lockfile`, `pnpm exec playwright install chromium`, and `make test_frontend`. The app's `make start` still does not need Node or a frontend build.

The suite exercises the actual HTML/CSS/JavaScript in Chromium with simulated API responses on an isolated loopback static server. Coverage includes hosted-model defaults, workflow switching and outgoing form values, real file selection/decoding, a 20-image queue limit, malformed/oversize rejection, sequential batches, partial failures, stop/resume, box hover/tap/keyboard inspection, metrics/downloads, persistent session selection across reloads, separate provider sessions, preview-only counting, API-key exclusion from browser storage, escaped class labels, popup dashboard links and offline handling. Backend behavior remains covered separately by the Python tests and recorded live inference checks.

GitHub Actions now has a frontend job alongside the database matrix and uploads the Playwright HTML report. Its execution in GitHub is pending the user's commit/push; local results are verified.
