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
import urllib.parse
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

from services import load_services, compose_path_for
from kuma import fetch_kuma_metrics, find_kuma_monitor_for_service
from jobs import submit_job, db_get_job
from docker_utils import docker_cli_available, run_compose, get_status


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
        # Add compose path as string (PosixPath is not JSON serializable)
        s['__compose_path'] = str(compose_path_for(s))
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
    if not docker_cli_available():
        return jsonify({'ok': False, 'error': 'docker CLI not found in container; cannot run compose. Mount /var/run/docker.sock and install docker client, or run dashboard on host with docker available.'}), 500
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
    if not docker_cli_available():
        return jsonify({'ok': False, 'error': 'docker CLI not found in container; cannot run compose. Mount /var/run/docker.sock and install docker client, or run dashboard on host with docker available.'}), 500
    path = compose_path_for(svc)
    job_id = submit_job('stop', name, path)
    return jsonify({'ok': True, 'job_id': job_id})


@app.route('/api/start_all', methods=['POST'])
def api_start_all():
    services = load_services()
    if not docker_cli_available():
        return jsonify({'ok': False, 'error': 'docker CLI not found in container; cannot run compose.'}), 500
    job_ids = []
    for s in services:
        path = compose_path_for(s)
        jid = submit_job('start', s.get('name'), path)
        job_ids.append({'name': s.get('name'), 'job_id': jid})
    return jsonify({'ok': True, 'jobs': job_ids})


@app.route('/api/stop_all', methods=['POST'])
def api_stop_all():
    services = load_services()
    if not docker_cli_available():
        return jsonify({'ok': False, 'error': 'docker CLI not found in container; cannot run compose.'}), 500
    job_ids = []
    for s in services:
        path = compose_path_for(s)
        jid = submit_job('stop', s.get('name'), path)
        job_ids.append({'name': s.get('name'), 'job_id': jid})
    return jsonify({'ok': True, 'jobs': job_ids})


@app.route('/api/job/<job_id>')
def api_job(job_id):
    # read job from persistent DB so any worker can serve the request
    try:
        job = db_get_job(job_id)
    except Exception:
        logger.exception('Error reading job %s from DB', job_id)
        job = None
    if not job:
        return jsonify({'ok': False, 'error': 'job not found'}), 404
    return jsonify({'ok': True, 'job': job})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
