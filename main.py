import sys
from app.tasks import poll_new_calls_task
from app.logger import log


def show_help():
    print("""
QA Module Data Script CLI
=========================

Usage:
  python main.py [command]

Commands:
  run-poll  - Manually poll database and trigger tasks synchronously for debugging.
  worker    - Start a Celery worker process (alternatively run: celery -A app.celery_app worker --loglevel=info).
  beat      - Start the Celery beat scheduler (alternatively run: celery -A app.celery_app beat --loglevel=info).
  help      - Show this help message.
""")


def run_manual_poll():
    log.info("Triggering manual database poll from CLI")
    # Directly invoke the task logic synchronously
    poll_new_calls_task()
    log.info("Manual poll command completed")


def start_worker():
    # Helper to start celery worker directly from python script
    from app.celery_app import celery_app
    log.info("Starting Celery worker...")
    worker = celery_app.Worker(loglevel="info")
    worker.start()


def start_beat():
    # Helper to start celery beat directly from python script
    from celery.apps.beat import Beat
    from app.celery_app import celery_app
    log.info("Starting Celery beat...")
    beat = Beat(app=celery_app, loglevel="info")
    beat.run()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        show_help()
        sys.exit(0)

    cmd = sys.argv[1].lower().strip()

    if cmd == "run-poll":
        run_manual_poll()
    elif cmd == "worker":
        start_worker()
    elif cmd == "beat":
        start_beat()
    elif cmd in ("help", "-h", "--help"):
        show_help()
    else:
        print(f"Unknown command: {cmd}")
        show_help()
        sys.exit(1)
