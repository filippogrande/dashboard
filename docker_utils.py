import shutil
import subprocess
import logging
import requests
import urllib.parse

from kuma import find_kuma_monitor_for_service

logger = logging.getLogger(__name__)


def docker_cli_available():
    try:
        return shutil.which('docker') is not None
    except Exception:
        return False


def run_compose(compose_path, action):
    if not compose_path.exists():
        return False, 'compose file not found'
    # Use the modern `docker compose` invocation (separate token 'compose')
    if action == 'up':
        cmd = ['docker', 'compose', '-f', str(compose_path), 'up', '-d']
    else:
        cmd = ['docker', 'compose', '-f', str(compose_path), 'down']
    try:
        logger.info('Running compose command: %s', ' '.join(cmd))
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        out = (p.stdout or '') + (p.stderr or '')
        logger.info('Compose command finished: returncode=%s', p.returncode)
        # log full stdout/stderr at debug level
        logger.debug('Compose stdout: %s', p.stdout)
        logger.debug('Compose stderr: %s', p.stderr)
        if p.returncode == 0:
            return True, out
        return False, out
    except FileNotFoundError as e:
        msg = 'docker CLI not found in container; cannot run compose: ' + str(e)
        logger.warning(msg)
        return False, msg
    except Exception as e:
        msg = 'Error running compose command: ' + str(e)
        logger.exception(msg)
        return False, msg


def get_status(service, kuma=None):
    compose_path = None
    try:
        compose_path = service.get('__compose_path')
    except Exception:
        compose_path = None
    # If no compose path, skip docker check
    if compose_path:
        try:
            p = subprocess.run(['docker', 'compose', '-f', str(compose_path), 'ps'], capture_output=True, text=True, timeout=30)
            out = (p.stdout or '') + (p.stderr or '')
            lowered = out.lower()
            if any(tok in lowered for tok in ('up', 'running', 'healthy', 'started')):
                return 'running'
            logger.debug('docker compose ps output did not indicate running for %s: %s', service.get('name'), out[:200])
        except FileNotFoundError:
            logger.warning('docker CLI not found; continuing with Kuma/HTTP probe for %s', service.get('name'))
        except Exception:
            logger.exception('Error running docker compose ps for %s; continuing with Kuma/HTTP probe', service.get('name'))

    # Try Kuma
    try:
        mon = find_kuma_monitor_for_service(service, kuma)
        if mon and isinstance(mon, dict):
            sc = mon.get('status_code')
            if sc is not None:
                return 'running' if sc == 1 else 'stopped'
    except Exception:
        logger.debug('Kuma fallback failed for %s', service.get('name'))

    # HTTP probe
    url = service.get('url')
    if url:
        try:
            resp = requests.get(url, timeout=3, allow_redirects=True, verify=False)
            if resp.status_code and resp.status_code < 400:
                return 'running'
            return 'stopped'
        except Exception:
            return 'unknown'

    return 'unknown'
