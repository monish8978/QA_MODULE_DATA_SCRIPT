import os
import json
from pathlib import Path
from dotenv import load_dotenv

# Base directory path
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables
load_dotenv(dotenv_path=os.path.join(BASE_DIR, ".env"))

# ───────── OPERATIONAL MODE ─────────
# Supported modes: 'db' (MySQL), 'dir' (Directory scanning), 'api' (External API poll)
PROCESS_MODE = os.getenv("PROCESS_MODE", "db").lower().strip()

# ───────── MYSQL DB CONFIGURATION (db mode) ─────────
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "sqladmin")
DB_NAME = os.getenv("DB_NAME", "czentrix_campaign_manager")
DB_PORT = int(os.getenv("DB_PORT", 3306))

# ───────── DIRECTORY SCANNING CONFIGURATION (dir mode) ─────────
SCAN_DIRECTORY_PATH = os.getenv("SCAN_DIRECTORY_PATH", "")

# ───────── EXTERNAL API CONFIGURATION (api mode) ─────────
SOURCE_API_URL = os.getenv("SOURCE_API_URL", "")
SOURCE_API_METHOD = os.getenv("SOURCE_API_METHOD", "GET").upper().strip()

try:
    SOURCE_API_HEADERS = json.loads(os.getenv("SOURCE_API_HEADERS", "{}"))
except Exception:
    SOURCE_API_HEADERS = {}

try:
    SOURCE_API_BODY = json.loads(os.getenv("SOURCE_API_BODY", "{}"))
except Exception:
    SOURCE_API_BODY = {}



# ───────── TRANSCRIPTION API ─────────
TRANSCRIPTION_API_URL = os.getenv("TRANSCRIPTION_API_URL", "https://call_transcript.c-zentrix.com/api/v1/transcribe")
TRANSCRIPTION_STATUS_URL = os.getenv("TRANSCRIPTION_STATUS_URL", "https://call_transcript.c-zentrix.com/api/v1/status")
TRANSCRIPTION_API_KEY = os.getenv("TRANSCRIPTION_API_KEY", "")
TRANSCRIPTION_SUBMISSION_METHOD = os.getenv("TRANSCRIPTION_SUBMISSION_METHOD", "upload").lower().strip()

# ───────── QA MODULE API ─────────
QA_API_BASE_URL = os.getenv("QA_API_BASE_URL", "http://172.16.3.215:8005/api/v1")
QA_TENANT_SLUG = os.getenv("QA_TENANT_SLUG", "c-zentrix-support")
QA_EMAIL = os.getenv("QA_EMAIL", "admin@c-zentrix.com")
QA_PASSWORD = os.getenv("QA_PASSWORD", "Password@123")
QA_SKIP_2FA = os.getenv("QA_SKIP_2FA", "true").lower().strip() == "true"

# ───────── DOMAIN & METADATA ─────────
RECORDING_BASE_URL = os.getenv("RECORDING_BASE_URL", "http://192.168.1.219")
QA_TOPIC = os.getenv("QA_TOPIC", "connectivity")
QA_SOURCE = os.getenv("QA_SOURCE", "app_mqji9bzivusp")

# ───────── CELERY & REDIS ─────────
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/0")

# ───────── OPERATIONS & LOGS ─────────
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", 60))
LOG_DIR = os.getenv("LOG_DIR", "/var/log/czentrix")
LOG_FILENAME = os.getenv("LOG_FILENAME", "qa_call_push.log")
