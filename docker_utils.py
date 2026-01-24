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
    # Try to use the compose project name derived from the compose file parent folder
    try:
        project_name = compose_path.parent.name
    except Exception:
        project_name = None
    base = ['docker', 'compose']
    if project_name:
        base = base + ['-p', project_name]
    if action == 'up':
        cmd = base + ['-f', str(compose_path), 'up', '-d']
    else:
        cmd = base + ['-f', str(compose_path), 'down']
    def _run(cmd_to_run):
        logger.info('Running compose command: %s', ' '.join(cmd_to_run))
        p = subprocess.run(cmd_to_run, capture_output=True, text=True, timeout=180)
        out = (p.stdout or '') + (p.stderr or '')
        logger.info('Compose command finished: returncode=%s', p.returncode)
        logger.debug('Compose stdout: %s', p.stdout)
        logger.debug('Compose stderr: %s', p.stderr)
        return p.returncode, out

    # Try primary form
    try:
        rc, out = _run(cmd)
        if rc == 0:
            return True, out
    except FileNotFoundError as e:
        logger.warning('docker CLI not found: %s', e)
        # fall through to try docker-compose if available
        rc = None
        out = str(e)
    except Exception as e:
        logger.exception('Error running compose command: %s', e)
        rc = None
        out = str(e)

    # If primary failed, try alternative forms to be resilient against different docker binaries
    # 1) long option `--file`
    alt_cmds = []
    if action == 'up':
        alt_cmds.append(['docker', 'compose', '--file', str(compose_path), 'up', '-d'])
    else:
        alt_cmds.append(['docker', 'compose', '--file', str(compose_path), 'down'])
    # 2) legacy docker-compose
    if action == 'up':
        alt_cmds.append(['docker-compose', '-f', str(compose_path), 'up', '-d'])
    else:
        alt_cmds.append(['docker-compose', '-f', str(compose_path), 'down'])

    for alt in alt_cmds:
        try:
            rc2, out2 = _run(alt)
            if rc2 == 0:
                logger.info('Compose succeeded with fallback: %s', ' '.join(alt))
                return True, out2
            # if stderr mentions unknown shorthand flag for -f, keep trying
            if 'unknown shorthand flag' in (out2 or '').lower() or 'unknown flag' in (out2 or '').lower():
                logger.warning('Compose fallback reported shorthand/unknown flag: %s', out2.splitlines()[:3])
            else:
                logger.info('Compose fallback returned non-zero: %s', rc2)
        except FileNotFoundError:
            logger.debug('Fallback command not found: %s', alt[0])
        except Exception:
            logger.exception('Error running fallback compose command: %s', alt)

    # If we got here, subprocess attempts failed. For `down` try Docker SDK fallback
    if action == 'down':
        try:
            import docker
            logger.info('Attempting docker SDK fallback for compose down')
            # parse compose file to get service names
            try:
                try:
                    import yaml
                except Exception:
                    yaml = None
                if yaml:
                    with open(compose_path, 'r') as fh:
                        doc = yaml.safe_load(fh)
                        services = set(doc.get('services', {}).keys() if isinstance(doc, dict) else [])
                else:
                    services = set()
            except Exception:
                services = set()
            client = docker.from_env()
            stopped = []
            removed = []
            for c in client.containers.list(all=True):
                labels = c.labels or {}
                svc = labels.get('com.docker.compose.service')
                if svc and (not services or svc in services):
                    try:
                        if c.status == 'running':
                            c.stop(timeout=10)
                        c.remove(v=True, force=True)
                        removed.append(c.name)
                    except Exception:
                        logger.exception('Error stopping/removing container %s', c.name)
            msg = f'docker SDK fallback removed containers: {removed}'
            return True, msg
        except Exception as e:
            logger.debug('Docker SDK fallback not available or failed: %s', e)

    # All attempts failed
    msg = 'All compose invocation attempts failed. Last output: ' + (out or '')
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
