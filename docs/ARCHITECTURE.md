# ARCHITECTURE — come funziona

<!-- Tipo: EXPLANATION. Come funziona e perche' una scelta. -->

## In una riga

Un server Flask legge una lista di servizi (`services.json`), per ognuno risolve il
path del suo `docker-compose.yml`, chiede a Docker se il progetto e' su o giu', e
risponde in JSON a una pagina HTML statica che fa da pannello.

## Componenti

| Componente | File | Responsabilita' |
|---|---|---|
| Entry point HTTP | `app.py` | route Flask, config env, CORS |
| Catalogo servizi | `services.py` | legge `services.json`, risolve i path |
| Job asincroni | `jobs.py` | eseguono i compose fuori dal thread HTTP |
| Operazioni Docker | `docker_utils.py` | `compose up/down` + verifica post-azione |
| Uptime Kuma | `kuma.py` | metriche Prometheus dei monitor |
| Config server | `gunicorn_config.py` | workers/threads/timeout |

## Il ciclo di una richiesta

1. `templates/index.html` carica `static/main.js`.
2. `static/main.js` -> `fetchServices()` chiama `GET /api/services`.
3. `app.py` -> `api_services()` chiama `services.py` -> `load_services()`.
4. Per ogni servizio, `services.py` -> `compose_path_for()` risolve il compose.
5. `docker_utils.py` -> `get_status()` chiede a Docker lo stato del progetto.
6. `kuma.py` -> `fetch_kuma_metrics()` aggiunge lo stato dai monitor Kuma.
7. Il JSON arriva al browser e `static/main.js` -> `render()` disegna le card.

## Il ciclo start/stop

1. Il browser fa `POST /api/start` (o `/api/stop`) con `{"name": ...}`.
2. `app.py` -> `api_start()` verifica `docker_cli_available()` e risolve il compose.
3. `jobs.py` -> `submit_job()` crea un job `pending` e lo salva in SQLite, poi lo
   passa a `EXECUTOR` (4 worker): la route risponde subito con `job_id`.
4. Il worker chiama `docker_utils.py` -> `run_compose()`: `docker compose -p <proj> -f <file> up -d`
   (o `down`), poi verifica con `verify_containers_running()` /
   `verify_containers_down()`. Se la verifica fallisce, prova i fallback per label.
5. `static/main.js` -> `pollJob()` interroga `GET /api/job/<id>` finche' lo stato non e'
   `done` o `failed`.

## Come si legge lo stato di un container

`docker_utils.py` -> `get_status()` prova in ordine:

1. `docker compose -p <proj> -f <file> ps`: se l'output contiene `up`/`running`/`healthy`
   -> `running`; se contiene `exited`/`stopped`/`dead` -> `stopped`.
2. Se Docker non risponde: `kuma.py` -> `find_kuma_monitor_for_service()` (stato Kuma).
3. Se non c'e' un monitor: probe HTTP su `service.url` (timeout 3s, `verify=False`).
4. Altrimenti `unknown`.

Il nome del progetto compose non e' letto dal file: `detect_project_name()` lo deduce
dal **nome della cartella padre** del compose. Se la deduzione sbaglia,
`run_compose()` riprova senza `-p`.

## Il ruolo di Uptime Kuma

Kuma non decide nulla: e' una fonte di stato in piu'.

- `kuma.py` -> `fetch_kuma_metrics()` chiama `UPTIME_KUMA_URL + '/metrics'` (endpoint
  Prometheus di Kuma), con Basic auth `('', UPTIME_KUMA_API_KEY)` se la chiave c'e'.
  Il risultato e' cachato `KUMA_CACHE_TTL` secondi (default 15).
- `_parse_prom_metrics()` legge le serie `monitor_status` e costruisce una mappa
  `url:<norm>` / `name:<lower>` / `id:<monitor_id>`.
- `app.py` -> `api_services()` prova il match per `url` e poi per `name`.
- I monitor Kuma senza un servizio associato diventano card `kuma_only` (senza bottoni).
- Se `UPTIME_KUMA_URL` non e' impostata, `fetch_kuma_metrics()` ritorna `{}`: la
  dashboard funziona lo stesso, solo senza i badge Kuma.

## Dove vivono i dati

- `services.json`: nella cartella montata (`SERVICE_ROOT`), mai nel repo.
- Icone: `SERVICE_ROOT/images/`, con fallback a `static/images/` (inesistente, vedi REFERENCE).
- Compose: sotto `SERVICE_ROOT`, in sottocartelle per servizio.
- `jobs.db`: `APP_ROOT` (dentro il container) -> vedi Limiti noti in REFERENCE.

## Frontend

`static/main.js` e' JS vanilla (nessun build, nessun import/export): tutto avviene sul
DOM. `static/tailwind.css` e' output di Tailwind CLI, non si edita a mano. Il tema
scuro e' una classe su `<html>` persistita in `localStorage`.
