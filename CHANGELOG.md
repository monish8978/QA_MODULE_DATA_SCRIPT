# Changelog

All notable changes to this project will be documented in this file.

## [1.1.0] - 2026-06-27

### Added
- **Gevent Concurrency**: Added `gevent` dependency and configured the Celery worker to use `--pool=gevent` with high concurrency. This solves the thread-blocking issue during synchronous API polling.
- **Database Connection Pooling**: Implemented `threading.local()` based MySQL connection pooling in `app/db.py` to drastically reduce DB connection overhead.
- **Configurable Transcription Strategy**: Added `TRANSCRIPTION_SUBMISSION_METHOD` configuration flag in `.env` (`url` or `upload`) to support both lightweight JSON URL submissions and direct local file multipart uploads.
- **Transcription API Authentication**: Added support for `X-API-Key` headers via the `TRANSCRIPTION_API_KEY` environment variable.
- **Auto-Retries**: Configured `urllib3.util.retry.Retry` with a robust `requests.Session` in both `transcription.py` and `qa_client.py` to auto-recover from transient 502, 503, and 504 backend errors.

### Changed
- **Memory Optimization**: Swapped the unbounded `set()` in the directory scanner (`app/tasks.py`) with a specialized `LRUCache` limit of 10,000 files to prevent long-term memory leaks.
- **Configuration Clarity**: Renamed the generic `SERVER_DOMAIN` environment variable to `RECORDING_BASE_URL` across the application to clarify its role in constructing QA Module media links.

### Fixed
- **Token Invalidation Bug**: Fixed an issue where an expired QA token (HTTP 401) would permanently fail pipelines by actively invalidating the Redis token cache on 401 errors, forcing a fresh token fetch on the next Celery retry.
- **Syntax Error in Polling**: Fixed missing try-except blocks when tearing down database polling routines.
