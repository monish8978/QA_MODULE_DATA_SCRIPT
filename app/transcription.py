import os
import time
import requests
import traceback
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from app.config import TRANSCRIPTION_API_URL, TRANSCRIPTION_STATUS_URL, TRANSCRIPTION_API_KEY, TRANSCRIPTION_SUBMISSION_METHOD
from app.logger import log

# Create a robust session with retries
http_session = requests.Session()
retries = Retry(total=3, backoff_factor=1, status_forcelist=[ 500, 502, 503, 504 ])
http_session.mount('http://', HTTPAdapter(max_retries=retries))
http_session.mount('https://', HTTPAdapter(max_retries=retries))


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
        headers = {}
        if TRANSCRIPTION_API_KEY:
            headers["X-API-Key"] = TRANSCRIPTION_API_KEY
            
        if TRANSCRIPTION_SUBMISSION_METHOD == "url":
            headers["Content-Type"] = "application/json"
            payload = {}
            if file_url:
                payload["file_url"] = file_url
            elif file_path:
                payload["file_path"] = file_path
            else:
                raise ValueError("Either file_path or file_url must be provided")
            
            response = http_session.post(TRANSCRIPTION_API_URL, json=payload, headers=headers, timeout=15, verify=False)
            
        else: # default to 'upload' method
            if file_path:
                with open(file_path, 'rb') as f:
                    # Use safe filename to prevent unicode encoding errors in requests
                    files = {'file': ('audio.wav', f, 'audio/wav')}
                    response = http_session.post(TRANSCRIPTION_API_URL, files=files, headers=headers, timeout=30, verify=False)
            elif file_url:
                file_response = http_session.get(file_url, timeout=15, verify=False)
                file_response.raise_for_status()
                files = {'file': (os.path.basename(file_url.split('?')[0]) or 'audio.wav', file_response.content, 'audio/wav')}
                response = http_session.post(TRANSCRIPTION_API_URL, files=files, headers=headers, timeout=30, verify=False)
            else:
                raise ValueError("Either file_path or file_url must be provided")
        
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
                status_response = http_session.get(status_url, headers=headers, timeout=10, verify=False)
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
        log.error(f"Transcription pipeline failed: {str(e)}", extra={
            "file_path": file_path,
            "file_url": file_url,
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
