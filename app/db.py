import pymysql
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
        log.error("MySQL connection error", extra={"error": str(e), "host": DB_HOST, "database": DB_NAME})
        raise Exception("MySQL Database connection failed")
    except Exception as e:
        log.error("Unexpected DB connection error", extra={"error": str(e)})
        raise Exception("Unexpected MySQL connection error")


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
        log.error("Failed to initialize MySQL tracking table", extra={"error": str(e), "traceback": traceback.format_exc()})


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
        log.error("Failed to check MySQL session status", extra={"session_id": session_id, "error": str(e)})
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
        log.error("Failed to save session state to MySQL tracker", extra={"session_id": session_id, "error": str(e)})
