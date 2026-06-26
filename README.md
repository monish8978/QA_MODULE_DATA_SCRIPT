# QA Module Data Script (Celery + Docker Production Edition)

This repository contains the refactored, production-ready daemon for polling, transcribing, and uploading conversation data to the TVT QA Module. It utilizes **FastAPI/Deepgram** for transcription and background queues powered by **Celery** & **Redis** inside **Docker**.

---

## 1. Features & Enhancements

1. **Multi-Mode Polling Support (`PROCESS_MODE`)**:
   - **`dir` (Directory Mode)**: Scans a local/mounted host directory for `.wav` files and parses metadata directly from the C-Zentrix filename structure. Optimized with an **In-Memory Cache Layer** to skip previously scanned files instantly, preventing database bottlenecks on high-volume directories.
   - **`db` (Database Mode)**: Polls the Campaign Manager database directly. Dynamically resolves table names across month boundaries (e.g., `` `2026_06` `` and `` `2026_05` ``) to ensure calls made exactly at midnight are never dropped.
   - **`api` (API Mode)**: Fetches recordings and metadata via an external HTTP GET API endpoint.
2. **Robust State Tracking (MySQL)**:
   - Uses the `processed_sessions` table in the Campaign Manager MySQL database to track processing status (`QUEUED`, `PROCESSING`, `COMPLETED`, `FAILED`) of each `session_id`.
   - Prevents duplicate task dispatching across polling intervals.
   - Automatically schedules retries for `FAILED` sessions on subsequent polls.
3. **Smart QA Token Management**:
   - Authenticates with the QA Module API and caches the token in Redis.
   - Features **Auto-Invalidation**: If the QA server expires the token early and returns `401 Unauthorized`, the script instantly invalidates the Redis cache and requests a fresh token on the next Celery retry.
4. **Queue Isolation**:
   - Operates on Redis Database Index `2` (`redis://127.0.0.1:6379/2`) to prevent task conflicts and queue corruption with the external Transcription Service (which runs on DB `0`).

---

## 2. Directory Structure

```
QA_MODULE_DATA_SCRIPT/
├── .env                  # Live environment configuration file
├── .env.example          # Environment variable template
├── Dockerfile            # Docker configuration for app
├── docker-compose.yml    # Redis, Celery Worker, and Celery Beat scheduler
├── requirements.txt      # Python dependencies
├── main.py               # CLI entrypoint (Run manual polls or start worker/beat)
├── app/                  # Main Application package
│   ├── __init__.py
│   ├── config.py         # Dynamic configuration loader (.env mapping)
│   ├── db.py             # MySQL Campaign DB & session status tracker
│   ├── logger.py         # Console & rotating file logging setup
│   ├── celery_app.py     # Celery instance and beat scheduler definition
│   ├── tasks.py          # Celery background tasks (Poll and Process)
│   ├── transcription.py  # Asynchronous transcription service client
│   ├── qa_client.py      # QA module login and conversation upload client
│   └── pipeline.py       # Single-call process orchestrator
```

---

## 3. Configuration (`.env`)

Configure the following parameters in `.env`:
* **PROCESS_MODE**: Set to `dir`, `db`, or `api` depending on the desired data source.
* **SCAN_DIRECTORY_PATH**: The folder path to scan if running in `dir` mode.
* **DB_\***: Campaign Manager MySQL connection parameters.
* **TRANSCRIPTION_\***: Endpoint to trigger and poll for Deepgram transcriptions.
* **QA_API_BASE_URL / QA_TENANT_SLUG / QA_EMAIL / QA_PASSWORD**: Credentials to access the QA system.
* **CELERY_BROKER_URL / CELERY_RESULT_BACKEND**: Redis connection credentials (Must use DB `2`).
* **POLL_INTERVAL_SECONDS**: System check interval (default: `60` seconds).

---

## 4. Run Guide

### Option A: Run via Docker (Recommended for Production)

To build and spin up the Celery Worker and Celery Beat scheduler in the background:

```bash
docker-compose up --build -d
```

* **Logs**: Stored directly on the host machine at `/var/log/czentrix/qa_call_push.log`.
* **Database State**: Stored in the Campaign Manager MySQL database (`processed_sessions` table).
* **Hot Reloading**: The `./app` directory is mounted directly into the containers. Any Python code changes you make will be available immediately upon container restart without requiring a full image rebuild.

### Option B: Run Locally (Development)

1. Ensure **Redis** is running locally and available on port `6379`.
2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run services:
   - **Start Worker**: `celery -A app.celery_app worker --loglevel=info`
   - **Start Scheduler**: `celery -A app.celery_app beat --loglevel=info`
4. **Synchronous Manual Poll (Debugging)**:
   ```bash
   python main.py run-poll
   ```
   This will run the polling logic synchronously once and log output to the console.
