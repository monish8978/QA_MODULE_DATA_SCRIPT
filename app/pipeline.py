import os
from datetime import datetime, timezone
import traceback
from app.config import RECORDING_BASE_URL, QA_TOPIC, QA_SOURCE
from app.logger import log
from app.transcription import get_call_transcription
from app.qa_client import upload_conversation
from app.db import mark_session_processed, get_metadata_from_db_by_filename


def parse_metadata_from_filename(filename: str) -> dict:
    """
    Parses agent_id, agent_name, cust_ph_no, and session_id from a monitor_filename.
    Supports both old format: AgentName-AgentID-CustPh-SessionID.wav/mp3
    and new format: agent-AgentID-SessionIDPart1-SessionIDPart2-CampaignName-DateTime-CustPh.wav/mp3
    """
    if not filename:
        return {}
    
    # Strip path and extension
    filename = os.path.basename(filename)
    name_without_ext, _ = os.path.splitext(filename)
    parts = name_without_ext.split('-')
    
    result = {}
    if len(parts) >= 7 and parts[0].lower() == "agent":
        # New format: agent-2121-1784013704-44557-Hridesh-2026_07_14_12_51_46-6399006711
        result["agent_id"] = parts[1]
        result["agent_name"] = parts[1]
        result["session_id"] = f"{parts[2]}.{parts[3]}"
        result["cust_ph_no"] = parts[-1]
    else:
        # Old format: AgentName-AgentID-CustPh-SessionID
        result["agent_name"] = parts[0] if len(parts) > 0 else ""
        result["agent_id"] = parts[1] if len(parts) > 1 else None
        result["cust_ph_no"] = parts[2] if len(parts) > 2 else ""
        result["session_id"] = parts[-1] if len(parts) > 3 else name_without_ext
        
    return result


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
    cust_name = row.get("cust_name")
    file_url = row.get("file_url")
    monitor_filename = row.get("monitor_filename")

    # Resolve metadata:
    # 1. Try querying current_report DB table by filename
    # 2. Try parsing the filename structure
    # 3. Fallback to row values
    db_meta = {}
    parsed_meta = {}
    if monitor_filename:
        db_meta = get_metadata_from_db_by_filename(monitor_filename)
        parsed_meta = parse_metadata_from_filename(monitor_filename)

    agent_id = db_meta.get("agent_id") or parsed_meta.get("agent_id") or row.get("agentId")
    agent_name = db_meta.get("agent_name") or parsed_meta.get("agent_name") or row.get("agentName")
    cust_ph_no = db_meta.get("cust_ph_no") or parsed_meta.get("cust_ph_no") or row.get("cust_ph_no")

    # Fallback for session_id if not present
    if not session_id:
        session_id = db_meta.get("session_id") or parsed_meta.get("session_id")

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
            
            # Check if file exists; if not, check for swapped extension (.mp3 <-> .wav)
            if not os.path.exists(file_path):
                base, ext = os.path.splitext(file_path)
                alt_ext = ".mp3" if ext.lower() == ".wav" else ".wav"
                alt_file_path = base + alt_ext
                if os.path.exists(alt_file_path):
                    log.info("Original file not found. Using alternative extension file", extra={
                        "original_path": file_path,
                        "alternative_path": alt_file_path
                    })
                    file_path = alt_file_path

            recording_url = RECORDING_BASE_URL + file_path.replace("/var/www/html", "")
            log.info("Processing local file path record", extra={
                "session_id": session_id,
                "monitor_filename": os.path.basename(file_path),
                "file_path": file_path
            })
            call_trans = get_call_transcription(file_path=file_path)

        if not call_trans:
            log.warning("Empty transcription returned, proceeding with empty dialog payload", extra={"session_id": session_id})

        # 3. Form payload
        payload = {
            "externalId": str(session_id),
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
