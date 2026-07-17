import pymysql
import os
import traceback
import threading
from app.config import DB_HOST, DB_USER, DB_PASSWORD, DB_NAME, DB_PORT
from app.logger import log

_local_data = threading.local()

# ───────── MYSQL DB CONNECTION ─────────

def get_connection_CMPMGR():
    """
    Create and return a MySQL connection to Czentrix Campaign Manager.
    Uses thread-local storage to pool connections.
    """
    conn = getattr(_local_data, "db_connection", None)
    try:
        if conn:
            conn.ping(reconnect=True)
            return conn
    except Exception:
        conn = None

    try:
        conn = pymysql.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            port=DB_PORT,
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True
        )
        _local_data.db_connection = conn
        return conn
    except pymysql.MySQLError as e:
        log.error(f"MySQL connection error: {e}", extra={"error": str(e), "host": DB_HOST, "database": DB_NAME})
        raise Exception(f"MySQL Database connection failed: {e}")
    except Exception as e:
        log.error(f"Unexpected DB connection error: {e}", extra={"error": str(e)})
        raise Exception(f"Unexpected MySQL connection error: {e}")


# ───────── MYSQL STATUS TRACKER ─────────

def init_tracker_db():
    """
    Create the processed_sessions tracking table inside MySQL database if it does not exist.
    """
    conn = None
    try:
        conn = get_connection_CMPMGR()
        with conn.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS processed_sessions (
                    session_id VARCHAR(100) PRIMARY KEY,
                    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    status VARCHAR(50) DEFAULT 'COMPLETED',
                    error_message TEXT
                )
            """)
        log.info("MySQL tracking database table initialized successfully")
    except Exception as e:
        log.error(f"Failed to initialize MySQL tracking table: {e}\n{traceback.format_exc()}", extra={"error": str(e), "traceback": traceback.format_exc()})


def is_session_processed(session_id: str) -> bool:
    """
    Checks if a session is already completed, queued, or in progress.
    Returns True if we should skip processing this session, False otherwise.
    """
    conn = None
    try:
        conn = get_connection_CMPMGR()
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT status FROM processed_sessions WHERE session_id = %s",
                (session_id,)
            )
            row = cursor.fetchone()
            
            if row:
                status = row["status"]
                # Skip if completed, currently queued, or processing
                if status in ("COMPLETED", "QUEUED", "PROCESSING"):
                    return True
            return False
    except Exception as e:
        log.error(f"Failed to check MySQL session status for session_id {session_id}: {e}", extra={"session_id": session_id, "error": str(e)})
        # Fail safe - assume processed to avoid duplicate uploads in case of DB issues
        return True


def mark_session_processed(session_id: str, status: str = "COMPLETED", error_message: str = None):
    """
    Inserts or updates the session's processing status in MySQL tracker table.
    """
    conn = None
    try:
        conn = get_connection_CMPMGR()
        with conn.cursor() as cursor:
            cursor.execute("""
                REPLACE INTO processed_sessions (session_id, status, error_message, processed_at)
                VALUES (%s, %s, %s, NOW())
            """, (session_id, status, error_message))
        log.info("Logged session state in MySQL tracker", extra={"session_id": session_id, "status": status})
    except Exception as e:
        log.error(f"Failed to save session state to MySQL tracker for session_id {session_id}: {e}", extra={"session_id": session_id, "error": str(e)})


def get_metadata_from_db_by_filename(filename: str) -> dict:
    """
    Queries the current_report table to fetch metadata (agent_id, agent_name, cust_ph_no, session_id)
    by matching the monitor_filename.
    """
    if not filename:
        return {}
    
    conn = None
    try:
        conn = get_connection_CMPMGR()
        with conn.cursor() as cursor:
            query = """
                SELECT agent_id, agent_name, cust_ph_no, session_id
                FROM current_report
                WHERE monitor_filename = %s
                LIMIT 1
            """
            
            # Strip path to get bare filename
            filename = os.path.basename(filename)
            
            # Try exact match first
            cursor.execute(query, (filename,))
            row = cursor.fetchone()
            
            # If not found, try replacing extension (.wav <-> .mp3)
            if not row:
                base, ext = os.path.splitext(filename)
                alt_ext = ".mp3" if ext.lower() == ".wav" else ".wav"
                alt_filename = base + alt_ext
                cursor.execute(query, (alt_filename,))
                row = cursor.fetchone()
                
            if row:
                log.info("Found metadata in current_report for filename", extra={"file_name": filename, "row": row})
                return {
                    "agent_id": row.get("agent_id"),
                    "agent_name": row.get("agent_name"),
                    "cust_ph_no": row.get("cust_ph_no"),
                    "session_id": row.get("session_id")
                }
    except Exception as e:
        log.error(f"Failed to fetch metadata from current_report for filename {filename}: {e}", extra={"file_name": filename, "error": str(e)})
        
    return {}
