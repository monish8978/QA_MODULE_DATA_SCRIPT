import os
import logging
from logging.handlers import TimedRotatingFileHandler
from app.config import LOG_DIR, LOG_FILENAME

# Ensure log directory exists
os.makedirs(LOG_DIR, exist_ok=True)

# Full log file path
LOG_FILE = os.path.join(LOG_DIR, LOG_FILENAME)

# Create main logger
log = logging.getLogger("qa_module_data_script")
log.setLevel(logging.INFO)

# Define log format
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(lineno)d - %(message)s'
)

# File Handler (Rotating daily at midnight, keeping 7 backups)
file_handler = TimedRotatingFileHandler(
    LOG_FILE, when="midnight", interval=1, backupCount=7, encoding="utf-8"
)
file_handler.setFormatter(formatter)
file_handler.setLevel(logging.INFO)

# Console Handler for real-time stdout logs
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
console_handler.setLevel(logging.INFO)

# Attach handlers to the logger (prevent duplicates)
if not log.handlers:
    log.addHandler(file_handler)
    log.addHandler(console_handler)
