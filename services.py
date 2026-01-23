import os
import json
import shutil
from pathlib import Path

APP_ROOT = Path(__file__).parent
SERVICE_ROOT = os.environ.get('SERVICE_ROOT')
if SERVICE_ROOT:
    SERVICE_ROOT = Path(SERVICE_ROOT)
    CONFIG_FILE = SERVICE_ROOT / 'services.json'
    COMPOSE_DIR = SERVICE_ROOT
else:
    CONFIG_DIR = APP_ROOT / 'config'
    CONFIG_FILE = CONFIG_DIR / 'services.json'
    COMPOSE_DIR = Path(os.environ.get('COMPOSE_DIR', str(APP_ROOT / 'compose')))


def load_services():
    if CONFIG_FILE and CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    # fallback to example if missing
    fallback = APP_ROOT / 'config' / 'services.example.json'
    if fallback.exists():
        return json.loads(fallback.read_text())
    return []


def compose_path_for(service):
    path = Path(service.get('compose', ''))
    if path.is_absolute():
        return path
    candidate = (COMPOSE_DIR / path).resolve()
    return candidate
