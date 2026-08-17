import requests
import redis
import json
from decimal import Decimal
from app.config import (
    QA_API_BASE_URL,
    QA_TENANT_SLUG,
    QA_EMAIL,
    QA_PASSWORD,
    CELERY_BROKER_URL,
    QA_SKIP_2FA
)
from app.logger import log
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Create a robust session with retries
http_session = requests.Session()
retries = Retry(total=3, backoff_factor=1, status_forcelist=[ 500, 502, 503, 504 ])
http_session.mount('http://', HTTPAdapter(max_retries=retries))
http_session.mount('https://', HTTPAdapter(max_retries=retries))

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


def get_access_token(tenant_config: dict = None) -> str:
    """
    Authenticates with the QA server. Uses Redis cache if token exists,
    otherwise requests a new token and caches it.
    """
    api_base_url = (tenant_config.get("QA_API_BASE_URL") if tenant_config else None) or QA_API_BASE_URL
    tenant_slug = (tenant_config.get("QA_TENANT_SLUG") if tenant_config else None) or QA_TENANT_SLUG
    email = (tenant_config.get("QA_EMAIL") if tenant_config else None) or QA_EMAIL
    password = (tenant_config.get("QA_PASSWORD") if tenant_config else None) or QA_PASSWORD
    skip_2fa = (tenant_config.get("QA_SKIP_2FA") if tenant_config else None) or QA_SKIP_2FA

    cache_key = f"qa_access_token:{tenant_slug}:{email}"

    # Try retrieving from Redis cache first
    if r_client:
        try:
            cached_token = r_client.get(cache_key)
            if cached_token:
                return cached_token.decode("utf-8")
        except Exception as e:
            log.warning(f"Error reading token from Redis cache: {str(e)}")

    # Request new token
    login_url = f"{api_base_url.rstrip('/')}/auth/login"
    headers = {
        "Content-Type": "application/json",
        "x-tenant-slug": tenant_slug
    }
    payload = {
        "email": email,
        "password": password,
        "skip2fa": skip_2fa
    }

    try:
        log.info("Requesting new access token from QA Server", extra={"url": login_url, "tenant_slug": tenant_slug})
        res = http_session.post(login_url, json=payload, headers=headers, timeout=15)
        
        if res.status_code != 200:
            raise Exception(f"Login failed ({res.status_code}): {res.text}")

        log.info("QA Module API Login Successful", extra={"tenant_slug": tenant_slug})

        response_data = res.json()
        try:
            token = response_data["data"]["accessToken"]
        except KeyError as ke:
            log.error(f"Login response structure mismatch. Response body: {res.text}")
            raise Exception(f"Failed to find expected key in response: {ke}")

        # Cache the token in Redis for 12 hours (43200 seconds)
        if r_client:
            try:
                r_client.setex(cache_key, 43200, token)
                log.info("Access token cached in Redis", extra={"tenant_slug": tenant_slug})
            except Exception as e:
                log.warning(f"Failed to save token to Redis cache: {str(e)}")

        return token

    except Exception as e:
        log.error(f"Authentication with QA Module failed for {tenant_slug}: {str(e)}")
        raise e


def invalidate_token(tenant_config: dict = None):
    tenant_slug = (tenant_config.get("QA_TENANT_SLUG") if tenant_config else None) or QA_TENANT_SLUG
    email = (tenant_config.get("QA_EMAIL") if tenant_config else None) or QA_EMAIL
    cache_key = f"qa_access_token:{tenant_slug}:{email}"
    if r_client:
        try:
            r_client.delete(cache_key)
        except Exception:
            pass

def upload_conversation(conversation_payload: dict, tenant_config: dict = None) -> bool:
    """
    Sanitizes and uploads a conversation payload to the QA Module server.
    """
    try:
        token = get_access_token(tenant_config)
        api_base_url = (tenant_config.get("QA_API_BASE_URL") if tenant_config else None) or QA_API_BASE_URL
        upload_url = f"{api_base_url.rstrip('/')}/conversations/upload"
        
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
        log.info(f"Final QA API Payload: {json.dumps(final_payload)}")
        
        res = http_session.post(upload_url, headers=headers, json=final_payload, timeout=15)
        
        if res.status_code in (200, 201):
            log.info(f"Conversation uploaded successfully [externalId: {clean_payload.get('externalId')}]")
            return True
        else:
            log.error(f"Failed to upload conversation [externalId: {clean_payload.get('externalId')}] | Status: {res.status_code} | Response: {res.text}")
            if res.status_code == 401:
                log.info("Token expired, invalidating cache so next retry fetches a fresh token")
                invalidate_token(tenant_config)
            return False

    except Exception as e:
        log.error(f"Error occurred during conversation upload: {str(e)}")
        return False
