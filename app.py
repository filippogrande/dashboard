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
import logging

load_dotenv()

# Configure logging: default INFO to reduce noise; enable debug via env
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO), format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)
# Dedicated logger for matching diagnostics; can be enabled with MATCH_DEBUG=1
matching_logger = logging.getLogger('hs.match')
if os.environ.get('MATCH_DEBUG') == '1':
    matching_logger.setLevel(logging.DEBUG)
else:
    matching_logger.setLevel(logging.INFO)
# Reduce chatter from HTTP libraries
logging.getLogger('requests').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)

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
        entry_id = labels.get('monitor_id') or f"{len(monitors)}"
        entry_key = key_url or key_name or ('id:' + entry_id)
        if entry_key not in monitors:
            monitors[entry_key] = {'name': name, 'url': url, 'monitor_id': entry_id}
        if metric == 'monitor_status':
            monitors[entry_key]['status_code'] = int(value)

    # Build a mapping that includes both url:<...> and name:<...> keys
    mapped = {}
    for entry in monitors.values():
        name = entry.get('name')
        url = entry.get('url')
        mid = entry.get('monitor_id')
        # canonicalize
        if url:
            mapped_key = 'url:' + url.rstrip('/')
            mapped[mapped_key] = entry
        if name:
            mapped_key = 'name:' + name.lower()
            mapped[mapped_key] = entry
        # also expose by id
        if mid:
            mapped_key = 'id:' + str(mid)
            mapped[mapped_key] = entry
    return mapped


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
        logger.info('Fetching Uptime Kuma metrics from %s', url)
        if UPTIME_KUMA_API_KEY:
            resp = requests.get(url, auth=('', UPTIME_KUMA_API_KEY), timeout=5)
        else:
            resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        logger.info('Uptime Kuma returned status %s; bytes=%d', resp.status_code, len(resp.text or ''))
        parsed = _parse_prom_metrics(resp.text)
        logger.info('Parsed %d monitors from Kuma metrics', len(parsed))
        _KUMA_METRICS_CACHE['ts'] = now
        _KUMA_METRICS_CACHE['data'] = parsed
        return parsed
    except Exception:
        logger.exception('Error fetching/parsing Uptime Kuma metrics')
        return {}


def find_kuma_monitor_for_service(service, kuma):
    """Return the parsed kuma monitor dict for a service if present."""
    if not kuma:
        return None
    s_url = service.get('url')
    s_name = service.get('name')
    if s_url:
        key = 'url:' + s_url.rstrip('/')
        m = kuma.get(key)
        if m:
            return m
    if s_name:
        key = 'name:' + s_name.lower()
        m = kuma.get(key)
        if m:
            return m
    return None


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


def get_status(service, kuma=None):
    """Determine local status of a service.

    Priority:
      1. docker compose ps (if available)
      2. Uptime Kuma match (if available)
      3. simple HTTP probe to the service `url` (if present)
      4. fallback to 'unknown'
    """
    compose_path = compose_path_for(service)
    if not compose_path.exists():
        return 'missing'
    try:
        p = subprocess.run(['docker', 'compose', '-f', str(compose_path), 'ps'], capture_output=True, text=True, timeout=30)
        out = (p.stdout or '') + (p.stderr or '')
        if 'Up' in out:
            return 'running'
        if p.returncode != 0:
            return 'stopped'
        return 'stopped'
    except FileNotFoundError:
        logger.warning('docker CLI not found; falling back to Kuma/HTTP probe for %s', service.get('name'))
        # try match with Kuma if provided
        try:
            mon = find_kuma_monitor_for_service(service, kuma)
            if mon and isinstance(mon, dict):
                sc = mon.get('status_code')
                if sc is not None:
                    return 'running' if sc == 1 else 'stopped'
        except Exception:
            logger.debug('Kuma fallback failed for %s', service.get('name'))
        # last-resort: HTTP probe to service URL
        url = service.get('url')
        if url:
            try:
                # allow insecure to cope with local self-signed certs
                resp = requests.get(url, timeout=3, allow_redirects=True, verify=False)
                if resp.status_code and resp.status_code < 400:
                    return 'running'
                return 'stopped'
            except Exception:
                return 'unknown'
    except Exception:
        logger.exception('Error running docker compose ps for %s', service.get('name'))
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
    logger.info('Loaded %d services; kuma monitors=%d', len(services), len(kuma))
    for s in services:
        s['status'] = get_status(s, kuma)
        logger.info('Service %s status=%s', s.get('name'), s['status'])
        # default kuma_status/color derived from local status so UI shows meaningful badge
        if s['status'] == 'running':
            s['kuma_status'] = 'up'
            s['kuma_color'] = 'green'
        elif s['status'] == 'stopped':
            s['kuma_status'] = 'down'
            s['kuma_color'] = 'red'
        elif s['status'] == 'missing':
            s['kuma_status'] = 'unknown'
            s['kuma_color'] = 'gray'
        else:
            s['kuma_status'] = 'unknown'
            s['kuma_color'] = 'gray'
        # enrich with uptime kuma info when possible
        try:
            s_url = s.get('url')
            s_name = s.get('name')
            matching_logger.debug('Matching service name=%s url=%s against kuma keys', s_name, s_url)
            # try match by url first, then by name
            monitor = None
            monitor_key = None
            if s_url:
                key = 'url:' + s_url.rstrip('/')
                monitor = kuma.get(key)
                monitor_key = key
                matching_logger.debug('Tried key %s -> %s', key, 'found' if monitor else 'not found')
            if not monitor and s_name:
                key = 'name:' + s_name.lower()
                monitor = kuma.get(key)
                monitor_key = key
                matching_logger.debug('Tried key %s -> %s', key, 'found' if monitor else 'not found')
            if monitor and isinstance(monitor, dict):
                # record matched monitor to avoid duplicates later
                m_name = (monitor.get('name') or '').lower()
                m_url = (monitor.get('url') or '').rstrip('/')
                matched_monitors.add((m_name, m_url))
                # we only care about the status code from Kuma metrics
                status_code = monitor.get('status_code')
                if status_code is not None:
                    label = {1: 'UP', 0: 'DOWN', 2: 'PENDING', 3: 'MAINTENANCE'}.get(status_code, 'UNKNOWN')
                    s['uptime'] = {'code': status_code, 'label': label}
                    # normalize for frontend badges
                    s['kuma_status'] = label.lower()
                    s['kuma_color'] = {'UP': 'green', 'DOWN': 'red', 'PENDING': 'yellow', 'MAINTENANCE': 'yellow'}.get(label, 'gray')
                    logger.info('Service %s matched monitor %s -> status %s', s_name, monitor.get('name'), label)
                else:
                    s['uptime'] = None
                    s['kuma_status'] = 'unknown'
                    s['kuma_color'] = 'gray'
                    logger.warning('Service %s matched a monitor but monitor has no status_code: %s', s_name, monitor)
            else:
                s['uptime'] = None
                logger.info('No Kuma monitor matched for service %s (tried url and name)', s_name)
        except Exception:
            s['uptime'] = None
            logger.exception('Error enriching service %s with Kuma info', s.get('name'))
    # Append Kuma-only monitors (those not matched to any service)
    # Build a set of unique monitors from kuma mapping
    seen = set()
    for entry in kuma.values():
        if not isinstance(entry, dict):
            continue
        name_raw = entry.get('name')
        name = (name_raw or '').lower()
        url_raw = entry.get('url')
        url = (url_raw or '')
        # skip monitors with no useful identity
        if not name and not url:
            continue
        # exclude internal/placeholder Kuma monitors like 'kuma-' entries
        if name.startswith('kuma-'):
            continue
        # normalize url for comparison
        url = url.rstrip('/')
        key = (name, url)
        if key in matched_monitors or key in seen:
            seen.add(key)
            continue
        seen.add(key)
        # create lightweight kuma-only card
        status_code = entry.get('status_code')
        uptime = None
        kuma_status = 'unknown'
        kuma_color = 'gray'
        if status_code is not None:
            label = {1: 'UP', 0: 'DOWN', 2: 'PENDING', 3: 'MAINTENANCE'}.get(status_code, 'UNKNOWN')
            uptime = {'code': status_code, 'label': label}
            kuma_status = label.lower()
            kuma_color = {'UP': 'green', 'DOWN': 'red', 'PENDING': 'yellow', 'MAINTENANCE': 'yellow'}.get(label, 'gray')
        kuma_item = {
            'name': entry.get('name') or f'kuma-{entry.get("monitor_id","")}',
            'icon': None,
            'url': entry.get('url'),
            'status': 'unknown',
            'uptime': uptime,
            'kuma_only': True,
            'kuma_status': kuma_status,
            'kuma_color': kuma_color,
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
