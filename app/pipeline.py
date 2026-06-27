import os
from datetime import datetime, timezone
import traceback
from app.config import RECORDING_BASE_URL, QA_TOPIC, QA_SOURCE
from app.logger import log
from app.transcription import get_call_transcription
from app.qa_client import upload_conversation
from app.db import mark_session_processed


def get_iso_utc_timestamp() -> str:
    """
    Generates an ISO formatted UTC timestamp (e.g. YYYY-MM-DDTHH:MM:SS.000Z).
    """
    try:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", ".000Z")
    except Exception:
        log.error("Failed to generate UTC timestamp", extra={"traceback": traceback.format_exc()})
        return None


def resolve_recording_path(monitor_file_path: str, monitor_filename: str) -> str:
    """
    Combines monitor file path and filename and returns clean unix-style absolute path.
    """
    if not monitor_file_path or not monitor_filename:
        raise ValueError("Missing monitor_file_path or monitor_filename")

    full_path = os.path.join(monitor_file_path, monitor_filename)
    return full_path.replace('\\', '/')


def process_single_call_record(row: dict) -> bool:
    """
    Full pipeline orchestration for a single database or API call record:
    1. Resolve recording reference (web URL or local file path).
    2. Request and poll transcriptions.
    3. Generate the QA Module API upload payload.
    4. Upload payload to QA server.
    5. Mark session as completed in tracker.
    """
    session_id = row.get("session_id")
    agent_id = row.get("agentId")
    agent_name = row.get("agentName")
    cust_ph_no = row.get("cust_ph_no")
    cust_name = row.get("cust_name")
    file_url = row.get("file_url")
    
    customer_ref = cust_name or cust_ph_no or ""

    log.info("Processing call record", extra={"session_id": session_id})

    try:
        call_trans = []
        recording_url = ""

        # Case 1: External URL input
        if file_url:
            recording_url = file_url
            log.info("Processing external URL record", extra={"session_id": session_id, "file_url": file_url})
            call_trans = get_call_transcription(file_url=file_url)

        # Case 2: Local File Path input
        else:
            file_path = resolve_recording_path(
                row.get("monitor_file_path"),
                row.get("monitor_filename")
            )
            recording_url = RECORDING_BASE_URL + file_path.replace("/var/www/html", "")
            log.info("Processing local file path record", extra={
                "session_id": session_id,
                "monitor_filename": row.get("monitor_filename"),
                "file_path": file_path
            })
            call_trans = get_call_transcription(file_path=file_path)

        if not call_trans:
            log.warning("Empty transcription returned, proceeding with empty dialog payload", extra={"session_id": session_id})

        # 3. Form payload
        payload = {
            "externalId": f"CALL-{session_id}",
            "agentId": str(agent_id) if agent_id is not None else None,
            "agentName": agent_name or "Unknown",
            "customerRef": str(customer_ref),
            "content": {
                "messages": call_trans,
                "recordingUrl": recording_url
            },
            "metadata": {
                "topic": QA_TOPIC,
                "source": QA_SOURCE
            },
            "receivedAt": get_iso_utc_timestamp()
        }

        # 4. Upload to QA module
        success = upload_conversation(payload)

        if success:
            mark_session_processed(session_id, "COMPLETED")
            return True
        else:
            mark_session_processed(session_id, "FAILED", "QA Upload API rejected payload")
            return False

    except Exception as e:
        error_msg = f"Pipeline execution failed: {str(e)}"
        log.error("Pipeline failure for call record", extra={
            "session_id": session_id,
            "error": str(e),
            "traceback": traceback.format_exc()
        })
        mark_session_processed(session_id, "FAILED", error_msg)
        return False
