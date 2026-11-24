import logging
import math
import os
import tempfile
import threading
import time
from datetime import datetime, timezone

import fcntl
from databricks.sdk import WorkspaceClient
from flask import request

from config.settings import DATABRICKS_HOST, DATABRICKS_TOKEN

logger = logging.getLogger(__name__)

IDLE_MINUTES = int(os.environ.get("DS_IDLE_STOP_MINUTES", "30"))
APP_NAME = os.environ.get("DATABRICKS_APP_NAME") or "shashi-data-sentinel-barrows"
CHECK_SECONDS = 30
WARN_MINUTES = 1 if IDLE_MINUTES <= 5 else 5
ACTIVITY_FILE = "/tmp/ds_last_activity"
LOCK_FILE = "/tmp/ds_idle_watchdog.lock"

_lock_file_handle = None
_thread_started = False
_thread_guard = threading.Lock()


def _utc_epoch() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def touch_activity() -> None:
    epoch = str(_utc_epoch())
    dir_name = os.path.dirname(ACTIVITY_FILE) or "/tmp"
    fd, tmp_path = tempfile.mkstemp(prefix=".ds_last_activity.", dir=dir_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(epoch)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, ACTIVITY_FILE)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except Exception:
            pass


def last_activity() -> int:
    try:
        with open(ACTIVITY_FILE, "r", encoding="utf-8") as f:
            return int(float((f.read() or "").strip()))
    except Exception:
        return _utc_epoch()


def minutes_until_stop():
    if IDLE_MINUTES == 0:
        return None
    idle_seconds = max(0, _utc_epoch() - last_activity())
    idle_minutes = idle_seconds / 60.0
    remaining = IDLE_MINUTES - idle_minutes
    return max(0, int(math.ceil(remaining)))


def _is_interval_only_dash_update() -> bool:
    if request.method != "POST":
        return False
    if (request.path or "") != "/_dash-update-component":
        return False

    payload = request.get_json(silent=True) or {}
    changed_prop_ids = payload.get("changedPropIds") or []
    inputs = payload.get("inputs") or []

    for prop_id in changed_prop_ids:
        if isinstance(prop_id, str) and prop_id.endswith(".n_intervals"):
            return True
    for item in inputs:
        if isinstance(item, dict) and item.get("property") == "n_intervals":
            return True
    return False


def register_activity_hook(server) -> None:
    @server.before_request
    def _record_activity():
        try:
            path = (request.path or "").lower()
            if (
                path.startswith("/assets/")
                or path.startswith("/_dash-component-suites/")
                or path.startswith("/_dash-layout")
                or path.startswith("/_dash-dependencies")
                or path.startswith("/_favicon")
                or path.startswith("/favicon")
                or path == "/health"
            ):
                return
            if _is_interval_only_dash_update():
                return
            touch_activity()
        except Exception:
            pass


def has_active_agent1_runs() -> bool:
    job_ids = [
        os.environ.get("DS_AGENT1_BASELINE_JOB_ID", "").strip(),
        os.environ.get("DS_AGENT1_VALIDATION_JOB_ID", "").strip(),
    ]
    job_ids = [j for j in job_ids if j]
    if not job_ids:
        return False

    try:
        w = WorkspaceClient(host=DATABRICKS_HOST, token=DATABRICKS_TOKEN, auth_type="pat")
        for job_id in job_ids:
            runs = w.jobs.list_runs(job_id=int(job_id), active_only=True)
            if any(True for _ in runs):
                return True
        return False
    except Exception as e:
        logger.error("Idle watchdog active-run check failed: %s", e)
        return True


def _watchdog_loop() -> None:
    w = WorkspaceClient(host=DATABRICKS_HOST, token=DATABRICKS_TOKEN, auth_type="pat")
    while True:
        try:
            now_epoch = _utc_epoch()
            idle_seconds = max(0, now_epoch - last_activity())
            idle_minutes = int(idle_seconds // 60)

            if IDLE_MINUTES > 0 and idle_seconds >= IDLE_MINUTES * 60:
                if has_active_agent1_runs():
                    logger.info(
                        "Idle %s min but Agent 1 run active - not stopping",
                        idle_minutes,
                    )
                else:
                    logger.info("Idle %s min - stopping app %s", idle_minutes, APP_NAME)
                    w.apps.stop(name=APP_NAME)
                    break
        except Exception as e:
            logger.error("Idle watchdog iteration error: %s", e)

        time.sleep(CHECK_SECONDS)


def start_watchdog() -> None:
    global _lock_file_handle, _thread_started

    if IDLE_MINUTES == 0:
        logger.info("Idle watchdog disabled")
        return

    with _thread_guard:
        if _thread_started:
            return

        touch_activity()

        lock_fh = open(LOCK_FILE, "a+", encoding="utf-8")
        try:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            try:
                lock_fh.close()
            except Exception:
                pass
            return

        _lock_file_handle = lock_fh

        t = threading.Thread(target=_watchdog_loop, daemon=True, name="ds-idle-watchdog")
        t.start()
        _thread_started = True
        logger.info("Idle watchdog started: %s min", IDLE_MINUTES)
