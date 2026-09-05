import os
import shutil
import subprocess
import logging
import time

from kuma import find_kuma_monitor_for_service

logger = logging.getLogger(__name__)


def docker_cli_available():
    try:
        return shutil.which('docker') is not None
    except Exception:
        return False


def detect_project_name(compose_path):
    """Detect docker compose project name from compose file parent directory."""
    try:
        name = compose_path.parent.name
        if name and name not in ('.', '/'):
            return name
    except Exception:
        pass
    return None


def _run(cmd, timeout=180):
    """Run a command and return (returncode, stdout+stderr)."""
    logger.info('Running: %s', ' '.join(cmd))
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = (p.stdout or '') + (p.stderr or '')
        return p.returncode, out
    except subprocess.TimeoutExpired:
        return -1, f'Command timed out after {timeout}s'
    except FileNotFoundError as e:
        return -2, str(e)
    except Exception as e:
        return -3, str(e)


def verify_containers_running(compose_path, project_name=None):
    """Check that containers from this compose project are actually running."""
    base = ['docker', 'compose']
    if project_name:
        base = base + ['-p', project_name]
    cmd = base + ['-f', str(compose_path), 'ps', '--format', '{{.Name}} {{.Status}}']
    rc, out = _run(cmd, timeout=15)
    if rc != 0:
        return False, out
    
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    if not lines:
        return False, 'No containers found'
    
    running = []
    not_running = []
    for line in lines:
        parts = line.split(None, 1)
        name = parts[0] if parts else ''
        status = parts[1] if len(parts) > 1 else ''
        if any(s in status.lower() for s in ('up', 'running', 'healthy')):
            running.append(name)
        else:
            not_running.append((name, status))
    
    if not_running:
        details = ', '.join(f'{n}: {s}' for n, s in not_running)
        return False, f'Some containers not running: {details}'
    
    return True, f'{len(running)} container(s) running'


def verify_containers_down(compose_path, project_name=None):
    """Check that containers from this compose project are stopped/removed."""
    base = ['docker', 'compose']
    if project_name:
        base = base + ['-p', project_name]
    cmd = base + ['-f', str(compose_path), 'ps', '--format', '{{.Name}}']
    rc, out = _run(cmd, timeout=15)
    
    # If compose ps fails, check via docker ps with label filter
    if rc != 0:
        cmd2 = ['docker', 'ps', '-a', '--filter', f'compose-project={project_name or compose_path.parent.name}', '--format', '{{.Names}}']
        rc2, out2 = _run(cmd2, timeout=15)
        if rc2 == 0 and not out2.strip():
            return True, 'No containers found (verified via docker ps)'
        return False, f'Containers still exist: {out2.strip()}'
    
    running = [l.strip() for l in out.splitlines() if l.strip()]
    if running:
        return False, f'Containers still exist: {running}'
    
    return True, 'All containers stopped/removed'


def run_compose(compose_path, action, svc_name=None):
    """Run docker compose up/down with verification.
    
    Returns (ok: bool, message: str).
    """
    if not compose_path.exists():
        return False, 'compose file not found'
    
    project_name = detect_project_name(compose_path)
    
    # Build command
    cmd = ['docker', 'compose']
    if project_name:
        cmd = cmd + ['-p', project_name]
    cmd = cmd + ['-f', str(compose_path)]
    if action == 'up':
        cmd = cmd + ['up', '-d']
    elif action == 'down':
        cmd = cmd + ['down']
    else:
        return False, f'Unknown action: {action}'
    
    rc, out = _run(cmd)
    
    if rc == 0:
        # Verify post-action
        time.sleep(2)  # brief grace period
        if action == 'up':
            ok, msg = verify_containers_running(compose_path, project_name)
            if not ok:
                return False, f'Compose up succeeded but verification failed: {msg}\nOutput: {out}'
        elif action == 'down':
            ok, msg = verify_containers_down(compose_path, project_name)
            if not ok:
                # Try force remove via labels as fallback
                if svc_name:
                    try:
                        cmd_rm = ['docker', 'ps', '-a', '--filter', f'label=com.docker.compose.service={svc_name}', '--format', '{{.ID}}']
                        rc_rm, out_rm = _run(cmd_rm, timeout=15)
                        ids = [ln.strip() for ln in (out_rm or '').splitlines() if ln.strip()]
                        if ids:
                            for cid in ids:
                                _run(['docker', 'stop', cid], timeout=30)
                                _run(['docker', 'rm', '-f', cid], timeout=30)
                            # Verify again
                            ok2, msg2 = verify_containers_down(compose_path, project_name)
                            if ok2:
                                return True, f'Containers removed via fallback cleanup. Original: {out}'
                            return False, f'Containers still present after cleanup: {msg2}'
                    except Exception as e:
                        logger.debug('Post-down cleanup failed: %s', e)
                return False, f'Compose down succeeded but containers still present: {msg}'
        return True, out
    
    # Compose failed — try with no project name
    if project_name:
        cmd_no_proj = ['docker', 'compose', '-f', str(compose_path)]
        if action == 'up':
            cmd_no_proj = cmd_no_proj + ['up', '-d']
        else:
            cmd_no_proj = cmd_no_proj + ['down']
        rc2, out2 = _run(cmd_no_proj)
        if rc2 == 0:
            time.sleep(2)
            if action == 'up':
                ok, msg = verify_containers_running(compose_path, None)
                if not ok:
                    return False, f'Compose up (no project) succeeded but verification failed: {msg}'
            elif action == 'down':
                ok, msg = verify_containers_down(compose_path, None)
                if not ok and svc_name:
                    # Fallback label cleanup
                    try:
                        cmd_rm = ['docker', 'ps', '-a', '--filter', f'label=com.docker.compose.service={svc_name}', '--format', '{{.ID}}']
                        rc_rm, out_rm = _run(cmd_rm, timeout=15)
                        ids = [ln.strip() for ln in (out_rm or '').splitlines() if ln.strip()]
                        if ids:
                            for cid in ids:
                                _run(['docker', 'stop', cid], timeout=30)
                                _run(['docker', 'rm', '-f', cid], timeout=30)
                            return True, f'Containers removed via fallback cleanup'
                    except Exception:
                        pass
                    return False, f'Containers still present: {msg}'
            return True, out2
    
    # For `down` with no compose success, try label-based fallback
    if action == 'down' and svc_name:
        try:
            cmd_rm = ['docker', 'ps', '-a', '--filter', f'label=com.docker.compose.service={svc_name}', '--format', '{{.ID}}']
            rc_rm, out_rm = _run(cmd_rm, timeout=15)
            ids = [ln.strip() for ln in (out_rm or '').splitlines() if ln.strip()]
            if ids:
                removed = []
                for cid in ids:
                    _run(['docker', 'stop', cid], timeout=30)
                    _run(['docker', 'rm', '-f', cid], timeout=30)
                    removed.append(cid)
                if removed:
                    return True, f'Containers removed via label fallback: {removed}'
        except Exception as e:
            logger.debug('Label fallback failed: %s', e)
    
    return False, f'Compose command failed (rc={rc}): {out}'


def get_status(service, kuma=None):
    """Determine local status of a service."""
    compose_path = None
    try:
        compose_path = service.get('__compose_path')
    except Exception:
        pass
    
    if compose_path:
        project_name = detect_project_name(compose_path)
        base = ['docker', 'compose']
        if project_name:
            base = base + ['-p', project_name]
        cmd = base + ['-f', str(compose_path), 'ps']
        rc, out = _run(cmd, timeout=15)
        if rc == 0:
            lowered = out.lower()
            if any(tok in lowered for tok in ('up', 'running', 'healthy')):
                return 'running'
            if any(tok in lowered for tok in ('exited', 'stopped', 'dead')):
                return 'stopped'
        else:
            logger.debug('docker compose ps failed for %s', service.get('name'))
    
    # Fallback to Kuma
    try:
        mon = find_kuma_monitor_for_service(service, kuma)
        if mon and isinstance(mon, dict):
            sc = mon.get('status_code')
            if sc is not None:
                return 'running' if sc == 1 else 'stopped'
    except Exception:
        pass
    
    # Fallback to HTTP probe
    url = service.get('url')
    if url:
        try:
            import requests
            resp = requests.get(url, timeout=3, allow_redirects=True, verify=False)
            return 'running' if resp.status_code < 400 else 'stopped'
        except Exception:
            return 'unknown'
    
    return 'unknown'
