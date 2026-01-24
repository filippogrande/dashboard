import sqlite3
import time
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor
import logging

from docker_utils import run_compose

logger = logging.getLogger(__name__)

APP_ROOT = __import__('pathlib').Path(__file__).parent
DB_FILE = APP_ROOT / 'jobs.db'
JOB_LOCK = threading.Lock()
JOBS = {}
EXECUTOR = ThreadPoolExecutor(max_workers=4)


def _db_connect():
    conn = sqlite3.connect(str(DB_FILE), timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def db_init():
    conn = _db_connect()
    c = conn.cursor()
    c.execute('''
    CREATE TABLE IF NOT EXISTS jobs (
      id TEXT PRIMARY KEY,
      action TEXT,
      name TEXT,
      status TEXT,
      result TEXT,
      started_at REAL,
      finished_at REAL
    )
    ''')
    conn.commit()
    conn.close()


def db_save_job(job):
    conn = _db_connect()
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO jobs (id, action, name, status, result, started_at, finished_at) VALUES (?,?,?,?,?,?,?)',
              (job['id'], job.get('action'), job.get('name'), job.get('status'), job.get('result'), job.get('started_at'), job.get('finished_at')))
    conn.commit()
    conn.close()


def db_update_job(job_id, **fields):
    if not fields:
        return
    conn = _db_connect()
    c = conn.cursor()
    parts = []
    vals = []
    for k, v in fields.items():
        parts.append(f"{k}=?")
        vals.append(v)
    vals.append(job_id)
    sql = f"UPDATE jobs SET {', '.join(parts)} WHERE id=?"
    c.execute(sql, vals)
    conn.commit()
    conn.close()


def db_get_job(job_id):
    conn = _db_connect()
    c = conn.cursor()
    c.execute('SELECT * FROM jobs WHERE id=?', (job_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return dict(row)


# initialize DB
try:
    db_init()
except Exception:
    logger.exception('Could not initialize jobs DB')


def submit_job(action, svc_name, compose_path):
    job_id = uuid.uuid4().hex
    job = {
        'id': job_id,
        'action': action,
        'name': svc_name,
        'status': 'pending',
        'result': None,
        'started_at': None,
        'finished_at': None,
    }
    with JOB_LOCK:
        JOBS[job_id] = job
    try:
        db_save_job(job)
    except Exception:
        logger.exception('Failed to save job to DB')

    def _run():
        start_ts = time.time()
        with JOB_LOCK:
            if job_id in JOBS:
                JOBS[job_id]['status'] = 'running'
                JOBS[job_id]['started_at'] = start_ts
        try:
            db_update_job(job_id, status='running', started_at=start_ts)
        except Exception:
            logger.exception('Failed to update job start in DB')

        ok, out = run_compose(compose_path, 'up' if action == 'start' else 'down', svc_name)
        finish_ts = time.time()
        final_status = 'done' if ok else 'failed'
        with JOB_LOCK:
            if job_id in JOBS:
                JOBS[job_id]['status'] = final_status
                JOBS[job_id]['result'] = out
                JOBS[job_id]['finished_at'] = finish_ts
        try:
            db_update_job(job_id, status=final_status, result=out, finished_at=finish_ts)
        except Exception:
            logger.exception('Failed to update job result in DB')

    EXECUTOR.submit(_run)
    return job_id
