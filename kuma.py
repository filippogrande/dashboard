import os
import re
import time
import logging
import urllib.parse
import requests

logger = logging.getLogger(__name__)

UPTIME_KUMA_URL = os.environ.get('UPTIME_KUMA_URL')
UPTIME_KUMA_API_KEY = os.environ.get('UPTIME_KUMA_API_KEY')
_KUMA_METRICS_CACHE = {'ts': 0, 'data': {}}
KUMA_CACHE_TTL = int(os.environ.get('KUMA_CACHE_TTL', '15'))


def _parse_prom_metrics(text):
    metric_re = re.compile(r'^(?P<metric>[a-zA-Z_:0-9]+)\{(?P<labels>[^}]*)\}\s+(?P<value>[-0-9.eE]+)')

    def parse_labels(s):
        d = {}
        for k, v in re.findall(r'(\w+)="([^"\\]*)"', s):
            d[k] = v
        return d

    def _norm_url(u):
        if not u:
            return None
        try:
            p = urllib.parse.urlparse(u)
            if p.netloc:
                return (p.scheme + '://' + p.netloc).rstrip('/')
            return u.split('/')[0].rstrip('/')
        except Exception:
            return u.rstrip('/')

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
        norm_url = _norm_url(url)
        key_url = f"url:{norm_url}" if norm_url else None
        key_name = f"name:{name.lower()}" if name else None
        entry_id = labels.get('monitor_id') or f"{len(monitors)}"
        entry_key = key_url or key_name or ('id:' + entry_id)
        if entry_key not in monitors:
            monitors[entry_key] = {'name': name, 'url': url, 'norm_url': norm_url, 'monitor_id': entry_id}
        if metric == 'monitor_status':
            monitors[entry_key]['status_code'] = int(value)

    mapped = {}
    for entry in monitors.values():
        name = entry.get('name')
        norm = entry.get('norm_url')
        mid = entry.get('monitor_id')
        if norm:
            mapped_key = 'url:' + norm
            mapped[mapped_key] = entry
        if name:
            mapped_key = 'name:' + name.lower()
            mapped[mapped_key] = entry
        if mid:
            mapped_key = 'id:' + str(mid)
            mapped[mapped_key] = entry
    return mapped


def fetch_kuma_metrics():
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
        parsed = _parse_prom_metrics(resp.text)
        _KUMA_METRICS_CACHE['ts'] = now
        _KUMA_METRICS_CACHE['data'] = parsed
        logger.info('Parsed %d monitors from Kuma metrics', len(parsed))
        return parsed
    except Exception:
        logger.exception('Error fetching/parsing Uptime Kuma metrics')
        return {}


def find_kuma_monitor_for_service(service, kuma):
    if not kuma:
        return None
    s_url = service.get('url')
    s_name = service.get('name')
    if s_url:
        try:
            p = urllib.parse.urlparse(s_url)
            if p.netloc:
                key_url = p.scheme + '://' + p.netloc
            else:
                key_url = s_url.split('/')[0]
        except Exception:
            key_url = s_url.rstrip('/')
        key = 'url:' + key_url.rstrip('/')
        m = kuma.get(key)
        if m:
            return m
    if s_name:
        key = 'name:' + s_name.lower()
        m = kuma.get(key)
        if m:
            return m
    return None
