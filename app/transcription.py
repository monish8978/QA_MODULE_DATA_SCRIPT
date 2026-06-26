import time
import requests
import traceback
from app.config import TRANSCRIPTION_API_URL, TRANSCRIPTION_STATUS_URL
from app.logger import log


def get_call_transcription(file_path: str = None, file_url: str = None, max_retries: int = 30, delay: int = 3) -> list:
    """
    Calls the asynchronous transcription service:
    1. Sends POST to start transcription (accepts file_path or file_url) and receives task_id.
    2. Polls GET status/{task_id} until completion or failure.
    3. Transforms output to expected format with timestamps.
    """
    try:
        log.info("Requesting transcription", extra={"file_path": file_path, "file_url": file_url})

        # Step 1: Request transcription task
        payload = {}
        if file_url:
            payload["file_url"] = file_url
        elif file_path:
            payload["file_path"] = file_path
        else:
            raise ValueError("Either file_path or file_url must be provided")

        headers = {"Content-Type": "application/json"}
        
        response = requests.post(TRANSCRIPTION_API_URL, json=payload, headers=headers, timeout=15)
        
        if response.status_code != 200:
            raise Exception(f"Transcription trigger failed: {response.status_code} - {response.text}")

        data = response.json()
        task_id = data.get("task_id")

        if not task_id:
            # Fallback check: Did it return a direct paired transcription list?
            if isinstance(data, list):
                log.info("Direct transcription list returned instead of task_id (sync mode)")
                return format_raw_transcript(data)
            raise Exception(f"No task_id found in transcription response: {data}")

        log.info("Transcription task scheduled", extra={"task_id": task_id})

        # Step 2: Poll status
        status_url = f"{TRANSCRIPTION_STATUS_URL.rstrip('/')}/{task_id}"
        transcript_data = None

        for attempt in range(max_retries):
            time.sleep(delay)
            log.info("Polling transcription status", extra={"attempt": attempt + 1, "task_id": task_id})

            try:
                status_response = requests.get(status_url, timeout=10)
                if status_response.status_code != 200:
                    continue
                
                status_data = status_response.json()
                status = status_data.get("status")

                if status == "SUCCESS":
                    transcript_data = status_data.get("result", {}).get("transcript", [])
                    break
                elif status == "FAILED":
                    raise Exception(f"Transcription service reported failure for task {task_id}")
            except requests.RequestException as re:
                log.warning("Status poll connection error", extra={"error": str(re)})
                continue

        if transcript_data is None:
            raise Exception(f"Transcription polling timed out for task {task_id}")

        # Step 3: Format the transcript output
        return format_raw_transcript(transcript_data)

    except Exception as e:
        log.error("Transcription pipeline failed", extra={
            "file_path": file_path,
            "file_url": file_url,
            "error": str(e),
            "traceback": traceback.format_exc()
        })
        return []


def format_raw_transcript(transcript_data: list) -> list:
    """
    Formats the raw transcription segments into structured conversation turns
    with sequential timestamps.
    """
    formatted_turns = []
    current_ts = int(time.time())

    for item in transcript_data:
        # Check and map Agent speaker turn
        if item.get("agent"):
            formatted_turns.append({
                "speaker": "agent",
                "text": item["agent"],
                "ts": current_ts
            })
            current_ts += 2

        # Check and map Customer speaker turn
        if item.get("customer"):
            formatted_turns.append({
                "speaker": "customer",
                "text": item["customer"],
                "ts": current_ts
            })
            current_ts += 2

    return formatted_turns
