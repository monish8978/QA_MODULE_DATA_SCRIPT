import requests
import redis
import json
from decimal import Decimal
from app.config import (
    QA_API_BASE_URL,
    QA_TENANT_SLUG,
    QA_EMAIL,
    QA_PASSWORD,
    CELERY_BROKER_URL
)
from app.logger import log

# Redis connection for caching token
try:
    # Extract host, port, db from celery url if possible, otherwise connect simply
    r_client = redis.Redis.from_url(CELERY_BROKER_URL)
except Exception:
    r_client = None
    log.warning("Could not establish connection to Redis for token caching. Falling back to direct API auth.")


def sanitize_payload(obj):
    """
    Recursively converts Decimal fields to strings to prevent JSON serialization errors.
    """
    if isinstance(obj, Decimal):
        return str(obj)
    elif isinstance(obj, dict):
        return {k: sanitize_payload(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_payload(i) for i in obj]
    return obj


def get_access_token() -> str:
    """
    Authenticates with the QA server. Uses Redis cache if token exists,
    otherwise requests a new token and caches it.
    """
    cache_key = f"qa_access_token:{QA_TENANT_SLUG}:{QA_EMAIL}"

    # Try retrieving from Redis cache first
    if r_client:
        try:
            cached_token = r_client.get(cache_key)
            if cached_token:
                return cached_token.decode("utf-8")
        except Exception as e:
            log.warning(f"Error reading token from Redis cache: {str(e)}")

    # Request new token
    login_url = f"{QA_API_BASE_URL.rstrip('/')}/auth/login"
    headers = {
        "Content-Type": "application/json",
        "x-tenant-slug": QA_TENANT_SLUG
    }
    payload = {
        "email": QA_EMAIL,
        "password": QA_PASSWORD
    }

    try:
        log.info("Requesting new access token from QA Server", extra={"url": login_url})
        res = requests.post(login_url, json=payload, headers=headers, timeout=15)
        
        if res.status_code != 200:
            raise Exception(f"Login failed ({res.status_code}): {res.text}")

        log.info("QA Module API Login Successful")

        response_data = res.json()
        token = response_data["data"]["accessToken"]

        # Cache the token in Redis for 12 hours (43200 seconds)
        if r_client:
            try:
                r_client.setex(cache_key, 43200, token)
                log.info("Access token cached in Redis")
            except Exception as e:
                log.warning(f"Failed to save token to Redis cache: {str(e)}")

        return token

    except Exception as e:
        log.error(f"Authentication with QA Module failed: {str(e)}")
        raise e


def invalidate_token():
    cache_key = f"qa_access_token:{QA_TENANT_SLUG}:{QA_EMAIL}"
    if r_client:
        try:
            r_client.delete(cache_key)
        except Exception:
            pass

def upload_conversation(conversation_payload: dict) -> bool:
    """
    Sanitizes and uploads a conversation payload to the QA Module server.
    """
    try:
        token = get_access_token()
        upload_url = f"{QA_API_BASE_URL.rstrip('/')}/conversations/upload"
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        clean_payload = sanitize_payload(conversation_payload)

        final_payload = {
            "channel": "CALL",
            "conversations": [clean_payload]
        }

        log.info(f"Uploading conversation payload [externalId: {clean_payload.get('externalId')}]")
        # log.info(f"Final QA API Payload: {json.dumps(final_payload)}")
        
        res = requests.post(upload_url, headers=headers, json=final_payload, timeout=15)
        
        if res.status_code in (200, 201):
            log.info(f"Conversation uploaded successfully [externalId: {clean_payload.get('externalId')}]")
            return True
        else:
            log.error(f"Failed to upload conversation [externalId: {clean_payload.get('externalId')}] | Status: {res.status_code} | Response: {res.text}")
            if res.status_code == 401:
                log.info("Token expired, invalidating cache so next retry fetches a fresh token")
                invalidate_token()
            return False

    except Exception as e:
        log.error(f"Error occurred during conversation upload: {str(e)}")
        return False
