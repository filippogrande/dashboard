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


def fetch_kuma_monitors():
    """Try to fetch monitors from Uptime Kuma. Returns mapping by name and by url."""
    if not UPTIME_KUMA_URL:
        return {}
    try:
        base = UPTIME_KUMA_URL.rstrip('/')
        endpoints = [
            base + '/api/getMonitors',
            base + '/api/monitors',
            base + '/api/get-monitors',
        ]
        headers = {}
        if UPTIME_KUMA_API_KEY:
            headers['Authorization'] = f'Bearer {UPTIME_KUMA_API_KEY}'
        for url in endpoints:
            try:
                resp = requests.get(url, headers=headers, timeout=5)
            except Exception:
                continue
            if resp.status_code != 200:
                continue
            j = resp.json()
            # Try to extract monitors list flexibly
            if isinstance(j, dict):
                if 'monitors' in j and isinstance(j['monitors'], list):
                    monitors = j['monitors']
                elif 'data' in j and isinstance(j['data'], list):
                    monitors = j['data']
                else:
                    # maybe the response itself is the list
                    monitors = [v for v in j.get('monitors', [])] if 'monitors' in j else None
            elif isinstance(j, list):
                monitors = j
            else:
                monitors = None
            if not monitors:
                # try direct list parse
                try:
                    monitors = resp.json()
                except Exception:
                    monitors = None
            if not monitors:
                continue
            mapping = {}
            for m in monitors:
                # try to extract name and url fields
                name = m.get('name') if isinstance(m, dict) else None
                mon_url = None
                if isinstance(m, dict):
                    mon_url = m.get('url') or m.get('address') or m.get('hostname')
                entry = m if isinstance(m, dict) else {'raw': m}
                if name:
                    mapping.setdefault('name:' + name.lower(), entry)
                if mon_url:
                    mapping.setdefault('url:' + mon_url.rstrip('/'), entry)
            return mapping
    except Exception:
        return {}
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
    # try to fetch uptime kuma monitors (optional)
    kuma = fetch_kuma_monitors()
    for s in services:
        s['status'] = get_status(s)
        # enrich with uptime kuma info when possible
        try:
            s_url = s.get('url')
            s_name = s.get('name')
            monitor = None
            if s_url:
                monitor = kuma.get('url:' + s_url.rstrip('/'))
            if not monitor and s_name:
                monitor = kuma.get('name:' + s_name.lower())
            if monitor:
                # attach a lightweight monitor summary
                s['uptime_monitor'] = {
                    'name': monitor.get('name'),
                    'url': monitor.get('url') or monitor.get('address') or monitor.get('hostname'),
                    'raw': monitor,
                }
                # try to infer a status field
                s['uptime'] = monitor.get('status') or monitor.get('state') or monitor.get('httpStatus')
            else:
                s['uptime'] = None
        except Exception:
            s['uptime'] = None
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
