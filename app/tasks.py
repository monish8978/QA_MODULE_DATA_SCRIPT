import os
import hashlib
import requests
from datetime import datetime, timedelta
import traceback
from decimal import Decimal
from app.celery_app import celery_app
from collections import OrderedDict

class LRUCache:
    def __init__(self, capacity: int):
        self.cache = OrderedDict()
        self.capacity = capacity

    def contains(self, key):
        if key not in self.cache:
            return False
        self.cache.move_to_end(key)
        return True

    def add(self, key):
        self.cache[key] = True
        self.cache.move_to_end(key)
        if len(self.cache) > self.capacity:
            self.cache.popitem(last=False)
from app.logger import log
from app.config import (
    PROCESS_MODE,
    SCAN_DIRECTORY_PATH,
    SOURCE_API_URL,
    SOURCE_API_METHOD,
    SOURCE_API_HEADERS,
    SOURCE_API_BODY
)
from app.db import (
    get_connection_CMPMGR,
    init_tracker_db,
    is_session_processed,
    mark_session_processed,
    get_metadata_from_db_by_filename
)
from app.pipeline import process_single_call_record, parse_metadata_from_filename


def serialize_db_row(row: dict) -> dict:
    """
    Converts non-JSON-serializable fields (like datetime and Decimal) in database rows
    into strings so they can be securely passed through Celery tasks.
    """
    serialized = {}
    for k, v in row.items():
        if isinstance(v, datetime):
            serialized[k] = v.isoformat()
        elif isinstance(v, Decimal):
            serialized[k] = str(v)
        else:
            serialized[k] = v
    return serialized


@celery_app.task(name="app.tasks.poll_new_calls_task")
def poll_new_calls_task():
    """
    Main periodic task triggered by Celery Beat scheduler.
    Routes execution to the correct scanner according to PROCESS_MODE ('db', 'dir', 'api').
    """
    log.info(f"Triggered poll task. Mode: {PROCESS_MODE}")

    # Ensure MySQL tracking database table is initialized
    init_tracker_db()

    try:
        if PROCESS_MODE == "db":
            poll_database_source()
        elif PROCESS_MODE == "dir":
            poll_directory_source()
        elif PROCESS_MODE == "api":
            poll_api_source()
        else:
            log.error(f"Unsupported PROCESS_MODE configured: '{PROCESS_MODE}'")
    except Exception as e:
        log.error("Fatal error during poll execution", extra={
            "mode": PROCESS_MODE,
            "error": str(e),
            "traceback": traceback.format_exc()
        })


# ───────── 1. DATABASE SCANNER (db mode) ─────────

def poll_database_source():
    """
    Queries MySQL Campaign Manager tables for the current and previous month.
    """
    conn = None
    try:
        conn = get_connection_CMPMGR()
        now = datetime.now()
        current_table = now.strftime("%Y_%m")
        
        # Calculate previous month table
        first_day_current_month = now.replace(day=1)
        last_day_prev_month = first_day_current_month - timedelta(days=1)
        prev_table = last_day_prev_month.strftime("%Y_%m")

        tables_to_scan = [prev_table, current_table]
        queued_count = 0

        with conn.cursor() as cursor:
            for table_name in tables_to_scan:
                query = f"""
                    SELECT
                        agent_id as agentId,
                        agent_name as agentName,
                        cust_ph_no,
                        monitor_file_path,
                        monitor_filename,
                        session_id,
                        cust_name,
                        call_start_date_time
                    FROM `{table_name}`
                    WHERE session_id != ''
                    ORDER BY call_start_date_time DESC
                    LIMIT 50
                """
                
                try:
                    log.info(f"Querying MySQL table: {table_name}")
                    cursor.execute(query)
                    rows = cursor.fetchall()
                except Exception as e:
                    log.warning(f"Could not read table {table_name}.", extra={"error": str(e)})
                    continue

                for row in rows:
                    session_id = row.get("session_id")
                    if not session_id:
                        continue

                    if not is_session_processed(session_id):
                        log.info("Found new call in DB to process", extra={
                            "session_id": session_id,
                            "monitor_filename": row.get("monitor_filename")
                        })
                        mark_session_processed(session_id, "QUEUED")
                        
                        serialized_row = serialize_db_row(row)
                        process_call_record_task.delay(serialized_row)
                        queued_count += 1

        log.info("Database polling completed", extra={"queued_count": queued_count})
    except Exception as e:
        log.error("Error in database polling", extra={"error": str(e), "traceback": traceback.format_exc()})


# ───────── 2. DIRECTORY SCANNER (dir mode) ─────────

_DIR_SCAN_CACHE = LRUCache(10000)

def poll_directory_source():
    """
    Scans a host directory for recording files (specifically .wav).
    Parses metadata (agent, session ID) directly from the filename structures.
    """
    if not SCAN_DIRECTORY_PATH or not os.path.exists(SCAN_DIRECTORY_PATH):
        log.error(f"Scan directory path does not exist: {SCAN_DIRECTORY_PATH}")
        return

    log.info(f"Scanning directory: {SCAN_DIRECTORY_PATH}")
    queued_count = 0

    try:
        files = os.listdir(SCAN_DIRECTORY_PATH)
        audio_files = [f for f in files if f.lower().endswith((".wav", ".mp3")) and os.path.isfile(os.path.join(SCAN_DIRECTORY_PATH, f))]
        
        log.info(f"Directory scan summary - Total files: {len(files)}, Audio files: {len(audio_files)}", extra={
            "raw_files_count": len(files),
            "audio_files_count": len(audio_files)
        })
        
        for filename in audio_files:
            # Skip instantly if we already cached this file in memory as processed
            if _DIR_SCAN_CACHE.contains(filename):
                continue

            # Query DB and parse filename for fallback
            db_meta = get_metadata_from_db_by_filename(filename)
            metadata = parse_metadata_from_filename(filename)
            
            session_id = db_meta.get("session_id") or metadata.get("session_id")
            agent_id = db_meta.get("agent_id") or metadata.get("agent_id")
            agent_name = db_meta.get("agent_name") or metadata.get("agent_name") or "DirScanAgent"
            cust_ph_no = db_meta.get("cust_ph_no") or metadata.get("cust_ph_no") or ""

            # Check local tracker
            processed = is_session_processed(session_id)
            if processed:
                _DIR_SCAN_CACHE.add(filename)
                continue

            log.info("Found new audio file in directory to process", extra={
                "session_id": session_id,
                "audio_filename": filename
            })
            mark_session_processed(session_id, "QUEUED")
            _DIR_SCAN_CACHE.add(filename)

            row = {
                "session_id": session_id,
                "agentId": agent_id,
                "agentName": agent_name,
                "cust_ph_no": cust_ph_no,
                "cust_name": "",
                "monitor_file_path": SCAN_DIRECTORY_PATH,
                "monitor_filename": filename
            }

            process_call_record_task.delay(row)
            queued_count += 1

        log.info("Directory polling completed", extra={"queued_count": queued_count})
    except Exception as e:
        log.error(f"Error occurred while scanning files in directory: {str(e)}\n{traceback.format_exc()}")


# ───────── 3. EXTERNAL API SCANNER (api mode) ─────────

def poll_api_source():
    """
    Polls an external web API for recording references (URLs or local paths).
    """
    if not SOURCE_API_URL:
        log.error("External SOURCE_API_URL is not configured")
        return

    log.info(f"Polling source API: {SOURCE_API_URL} ({SOURCE_API_METHOD})")
    queued_count = 0

    try:
        if SOURCE_API_METHOD == "POST":
            res = requests.post(
                SOURCE_API_URL,
                headers=SOURCE_API_HEADERS,
                json=SOURCE_API_BODY,
                timeout=20
            )
        else:
            res = requests.get(
                SOURCE_API_URL,
                headers=SOURCE_API_HEADERS,
                timeout=20
            )

        if res.status_code != 200:
            log.error(f"Source API returned error: {res.status_code} - {res.text}")
            return

        items = res.json()
        if not isinstance(items, list):
            # API might return a root dictionary containing a list, e.g. {"data": [...]}
            if isinstance(items, dict) and "data" in items:
                items = items["data"]
            else:
                log.error("Source API response is not a list structure", extra={"response": str(items)[:500]})
                return

        for item in items:
            file_url = item.get("file_url") or item.get("recording_url")
            file_path = item.get("file_path") or item.get("monitor_file_path")
            
            if not file_url and not file_path:
                log.warning("Skipping API item containing no file_url or file_path")
                continue

            # Fallback unique session ID: hash of url/path if not returned by API
            session_id = item.get("session_id") or item.get("sessionId")
            if not session_id:
                reference = file_url or file_path
                session_id = hashlib.md5(reference.encode("utf-8")).hexdigest()

            # Check MySQL tracker
            if not is_session_processed(session_id):
                log.info("Found new record from API to process", extra={
                    "session_id": session_id,
                    "audio_filename": item.get("monitor_filename") or os.path.basename(file_path or file_url or "")
                })
                mark_session_processed(session_id, "QUEUED")

                row = {
                    "session_id": session_id,
                    "agentId": item.get("agent_id") or item.get("agentId"),
                    "agentName": item.get("agent_name") or item.get("agentName") or "APIAgent",
                    "cust_ph_no": item.get("customer_phone") or item.get("cust_ph_no") or "",
                    "cust_name": item.get("customer_name") or item.get("cust_name") or "",
                    "file_url": file_url
                }

                if file_path:
                    # In case the API returns file_path instead of file_url
                    row["monitor_file_path"] = os.path.dirname(file_path)
                    row["monitor_filename"] = os.path.basename(file_path)

                process_call_record_task.delay(row)
                queued_count += 1

        log.info("API polling completed", extra={"queued_count": queued_count})
    except Exception as e:
        log.error("Error occurred while fetching call records from API", extra={
            "error": str(e),
            "traceback": traceback.format_exc()
        })


# ───────── CELERY WORKER TASK ─────────

@celery_app.task(name="app.tasks.process_call_record_task", bind=True, max_retries=3, default_retry_delay=60)
def process_call_record_task(self, row: dict):
    """
    Celery worker task that executes the transcription and upload pipeline for a single call.
    """
    session_id = row.get("session_id")
    log.info("Worker processing task started", extra={"session_id": session_id})
    
    # Update MySQL state to PROCESSING
    mark_session_processed(session_id, "PROCESSING")

    try:
        success = process_single_call_record(row)
        if not success:
            raise Exception("Pipeline upload or transcription reported failure")
    except Exception as exc:
        log.warning("Task execution failed. Retrying...", extra={"session_id": session_id, "error": str(exc)})
        mark_session_processed(session_id, "FAILED", f"Error: {str(exc)}")
        raise self.retry(exc=exc)
