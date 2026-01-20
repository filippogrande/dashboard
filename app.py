import os
import json
import shutil
import subprocess
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from flask import Flask, render_template, jsonify, request, send_from_directory, abort
from dotenv import load_dotenv
import requests

import re
import time

load_dotenv()

APP_ROOT = Path(__file__).parent
# If SERVICE_ROOT is set (mounted host folder), use it as source of services.json, images and compose files
SERVICE_ROOT = os.environ.get('SERVICE_ROOT')
if SERVICE_ROOT:
    SERVICE_ROOT = Path(SERVICE_ROOT)
    CONFIG_FILE = SERVICE_ROOT / 'services.json'
    COMPOSE_DIR = SERVICE_ROOT
    # try to initialize the SERVICE_ROOT if missing: create dir, services.json and images
    try:
        SERVICE_ROOT.mkdir(parents=True, exist_ok=True)
        target_json = SERVICE_ROOT / 'services.json'
        if not target_json.exists():
            example = APP_ROOT / 'config' / 'services.example.json'
            if example.exists():
                shutil.copy2(str(example), str(target_json))
        images_dir = SERVICE_ROOT / 'images'
        images_dir.mkdir(parents=True, exist_ok=True)
        # copy bundled placeholder images if not present
        bundled = APP_ROOT / 'static' / 'images'
        if bundled.exists():
            for f in bundled.iterdir():
                dest = images_dir / f.name
                if not dest.exists():
                    shutil.copy2(str(f), str(dest))
    except Exception as e:
        print('Warning: could not initialize SERVICE_ROOT:', e)
else:
    CONFIG_DIR = APP_ROOT / 'config'
    CONFIG_FILE = CONFIG_DIR / 'services.json'
    COMPOSE_DIR = Path(os.environ.get('COMPOSE_DIR', str(APP_ROOT / 'compose')))

app = Flask(__name__, static_folder='static', template_folder='templates')

# Simple in-memory job runner
JOB_LOCK = threading.Lock()
JOBS = {}  # job_id -> {id, action, name, status, result, started_at, finished_at}
EXECUTOR = ThreadPoolExecutor(max_workers=4)


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

    def _run():
        with JOB_LOCK:
            JOBS[job_id]['status'] = 'running'
            JOBS[job_id]['started_at'] = __import__('time').time()
        ok, out = run_compose(compose_path, 'up' if action == 'start' else 'down')
        with JOB_LOCK:
            JOBS[job_id]['status'] = 'done' if ok else 'failed'
            JOBS[job_id]['result'] = out
            JOBS[job_id]['finished_at'] = __import__('time').time()

    EXECUTOR.submit(_run)
    return job_id


def load_services():
    if CONFIG_FILE and CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    # fallback to example if missing
    fallback = APP_ROOT / 'config' / 'services.example.json'
    if fallback.exists():
        return json.loads(fallback.read_text())
    return []


# Uptime Kuma config (optional)
UPTIME_KUMA_URL = os.environ.get('UPTIME_KUMA_URL')
UPTIME_KUMA_API_KEY = os.environ.get('UPTIME_KUMA_API_KEY')

# Cache for Kuma metrics (seconds)
_KUMA_METRICS_CACHE = { 'ts': 0, 'data': {} }
KUMA_CACHE_TTL = int(os.environ.get('KUMA_CACHE_TTL', '15'))


def _parse_prom_metrics(text):
    """Parse Prometheus exposition text and extract monitor_status values.
    Returns a dict keyed by 'url:<url>' and 'name:<lower>' mapping to {'status_code': int}.
    """
    metric_re = re.compile(r'^(?P<metric>[a-zA-Z_:0-9]+)\{(?P<labels>[^}]*)\}\s+(?P<value>[-0-9.eE]+)')

    def parse_labels(s):
        d = {}
        for k, v in re.findall(r'(\w+)="([^"\\]*)"', s):
            d[k] = v
        return d

    monitors = {}
    for line in text.splitlines():
        m = metric_re.match(line)
        if not m:
            continue
        metric = m.group('metric')
        labels = parse_labels(m.group('labels'))
        try:
            value = float(m.group('value'))
        except Exception:
            continue
        name = labels.get('monitor_name')
        url = labels.get('monitor_url')
        key_url = f"url:{url.rstrip('/')}" if url else None
        key_name = f"name:{name.lower()}" if name else None
        entry_key = key_url or key_name or ('id:' + labels.get('monitor_id', ''))
        if entry_key not in monitors:
            monitors[entry_key] = {'name': name, 'url': url}
        if metric == 'monitor_status':
            monitors[entry_key]['status_code'] = int(value)
    return monitors


def fetch_kuma_metrics():
    """Fetch and parse /metrics from Uptime Kuma, with simple caching.
    Returns mapping keyed by url:<...> and name:<...> with status_code.
    """
    if not UPTIME_KUMA_URL:
        return {}
    now = time.time()
    if now - _KUMA_METRICS_CACHE['ts'] < KUMA_CACHE_TTL and _KUMA_METRICS_CACHE['data']:
        return _KUMA_METRICS_CACHE['data']
    try:
        url = UPTIME_KUMA_URL.rstrip('/') + '/metrics'
        if UPTIME_KUMA_API_KEY:
            resp = requests.get(url, auth=('', UPTIME_KUMA_API_KEY), timeout=5)
        else:
            resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        parsed = _parse_prom_metrics(resp.text)
        _KUMA_METRICS_CACHE['ts'] = now
        _KUMA_METRICS_CACHE['data'] = parsed
        return parsed
    except Exception:
        return {}


def compose_path_for(service):
    path = Path(service.get('compose', ''))
    if path.is_absolute():
        return path
    # resolve relative to COMPOSE_DIR (which may be SERVICE_ROOT)
    candidate = (COMPOSE_DIR / path).resolve()
    return candidate


@app.route('/images/<path:filename>')
def user_image(filename):
    # serve images from SERVICE_ROOT/images if present, else from bundled static/images
    if SERVICE_ROOT:
        img_dir = SERVICE_ROOT / 'images'
        target = img_dir / filename
        if target.exists() and target.is_file():
            return send_from_directory(str(img_dir), filename)
    # fallback to bundled images
    bundled = APP_ROOT / 'static' / 'images'
    target = bundled / filename
    if target.exists() and target.is_file():
        return send_from_directory(str(bundled), filename)
    abort(404)


def get_status(service):
    compose_path = compose_path_for(service)
    if not compose_path.exists():
        return 'missing'
    try:
        p = subprocess.run(['docker', 'compose', '-f', str(compose_path), 'ps'], capture_output=True, text=True, timeout=30)
        out = p.stdout + p.stderr
        if p.returncode != 0:
            return 'stopped'
        if 'Up' in out:
            return 'running'
        return 'stopped'
    except Exception:
        return 'unknown'


def run_compose(compose_path, action):
    if not compose_path.exists():
        return False, 'compose file not found'
    if action == 'up':
        cmd = ['docker', 'compose', '-f', str(compose_path), 'up', '-d']
    else:
        cmd = ['docker', 'compose', '-f', str(compose_path), 'down']
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        return p.returncode == 0, (p.stdout or '') + (p.stderr or '')
    except Exception as e:
        return False, str(e)


@app.after_request
def add_cors(resp):
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    resp.headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS'
    return resp


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/services')
def api_services():
    services = load_services()
    # try to fetch uptime kuma metrics (optional)
    kuma = fetch_kuma_metrics()
    matched_monitors = set()
    for s in services:
        s['status'] = get_status(s)
        # enrich with uptime kuma info when possible
        try:
            s_url = s.get('url')
            s_name = s.get('name')
            # try match by url first, then by name
            monitor = None
            monitor_key = None
            if s_url:
                key = 'url:' + s_url.rstrip('/')
                monitor = kuma.get(key)
                monitor_key = key
            if not monitor and s_name:
                key = 'name:' + s_name.lower()
                monitor = kuma.get(key)
                monitor_key = key
            if monitor and isinstance(monitor, dict):
                # record matched monitor to avoid duplicates later
                m_name = (monitor.get('name') or '').lower()
                m_url = (monitor.get('url') or '').rstrip('/')
                matched_monitors.add((m_name, m_url))
                # we only care about the status code from Kuma metrics
                status_code = monitor.get('status_code')
                if status_code is not None:
                    s['uptime'] = {'code': status_code, 'label': {1: 'UP', 0: 'DOWN', 2: 'PENDING', 3: 'MAINTENANCE'}.get(status_code, 'UNKNOWN')}
                else:
                    s['uptime'] = None
            else:
                s['uptime'] = None
        except Exception:
            s['uptime'] = None
    # Append Kuma-only monitors (those not matched to any service)
    # Build a set of unique monitors from kuma mapping
    seen = set()
    for entry in kuma.values():
        if not isinstance(entry, dict):
            continue
        name = (entry.get('name') or '').lower()
        url = (entry.get('url') or '').rstrip('/')
        key = (name, url)
        if key in matched_monitors or key in seen:
            seen.add(key)
            continue
        seen.add(key)
        # create lightweight kuma-only card
        status_code = entry.get('status_code')
        uptime = None
        if status_code is not None:
            uptime = {'code': status_code, 'label': {1: 'UP', 0: 'DOWN', 2: 'PENDING', 3: 'MAINTENANCE'}.get(status_code, 'UNKNOWN')}
        kuma_item = {
            'name': entry.get('name') or f'kuma-{entry.get("monitor_id","")}',
            'icon': None,
            'url': entry.get('url'),
            'status': 'unknown',
            'uptime': uptime,
            'kuma_only': True,
        }
        services.append(kuma_item)

    return jsonify(services)


@app.route('/api/start', methods=['POST'])
def api_start():
    data = request.json or {}
    name = data.get('name')
    services = load_services()
    svc = next((s for s in services if s.get('name') == name or s.get('id') == name), None)
    if not svc:
        return jsonify({'ok': False, 'error': 'service not found'}), 404
    path = compose_path_for(svc)
    job_id = submit_job('start', name, path)
    return jsonify({'ok': True, 'job_id': job_id})


@app.route('/api/stop', methods=['POST'])
def api_stop():
    data = request.json or {}
    name = data.get('name')
    services = load_services()
    svc = next((s for s in services if s.get('name') == name or s.get('id') == name), None)
    if not svc:
        return jsonify({'ok': False, 'error': 'service not found'}), 404
    path = compose_path_for(svc)
    job_id = submit_job('stop', name, path)
    return jsonify({'ok': True, 'job_id': job_id})


@app.route('/api/start_all', methods=['POST'])
def api_start_all():
    services = load_services()
    job_ids = []
    for s in services:
        path = compose_path_for(s)
        jid = submit_job('start', s.get('name'), path)
        job_ids.append({'name': s.get('name'), 'job_id': jid})
    return jsonify({'ok': True, 'jobs': job_ids})


@app.route('/api/stop_all', methods=['POST'])
def api_stop_all():
    services = load_services()
    job_ids = []
    for s in services:
        path = compose_path_for(s)
        jid = submit_job('stop', s.get('name'), path)
        job_ids.append({'name': s.get('name'), 'job_id': jid})
    return jsonify({'ok': True, 'jobs': job_ids})


@app.route('/api/job/<job_id>')
def api_job(job_id):
    with JOB_LOCK:
        job = JOBS.get(job_id)
    if not job:
        return jsonify({'ok': False, 'error': 'job not found'}), 404
    return jsonify({'ok': True, 'job': job})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
