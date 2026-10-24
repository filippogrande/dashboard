# REFERENCE — la mappa del codice

<!-- Tipo: REFERENCE. Rispecchia la struttura del codice, come una mappa. -->
<!-- Ogni riga: un file reale + un simbolo reale. Nessun numero di riga. -->
<!-- Si aggiorna NELLA STESSA PR che sposta qualcosa. -->

## Come si legge

Una riga per cosa che ti puo' essere chiesto di cambiare.
**Richiesta -> file -> entry point.** Se per trovare il file ti serve altro,
la riga e' sbagliata.

## Entry point

| Vuoi... | File | Entry point |
|---|---|---|
| Capire dove inizia tutto | `app.py` | `app = Flask(...)`, `if __name__ == '__main__'` |
| Cambiare la porta d'ascolto | `app.py` | `if __name__ == '__main__'`; `gunicorn_config.py` -> `bind` |
| Cambiare workers/threads di gunicorn | `gunicorn_config.py` | `workers`, `threads`, `worker_class` |
| Cambiare il livello di log | `app.py` | `LOG_LEVEL`, `matching_logger` |

## Route Flask

| Vuoi... | File | Entry point |
|---|---|---|
| Vedere la lista dei servizi con stato | `app.py` | `api_services()` |
| Avviare un servizio | `app.py` | `api_start()` |
| Fermare un servizio | `app.py` | `api_stop()` |
| Avviare tutti i servizi | `app.py` | `api_start_all()` |
| Fermare tutti i servizi | `app.py` | `api_stop_all()` |
| Leggere l'esito di un job | `app.py` | `api_job()` |
| Servire la pagina iniziale | `app.py` | `index()` |
| Servire le icone | `app.py` | `user_image()` |
| Cambiare le header CORS | `app.py` | `add_cors()` |
| Aggiungere una route API | `app.py` | `api_services()` (per la forma) |

## Configurazione e servizi

| Vuoi... | File | Entry point |
|---|---|---|
| Leggere `services.json` | `services.py` | `load_services()` |
| Risolvere il path di un compose | `services.py` | `compose_path_for()` |
| Cambiare dove vivono `services.json` e i compose | `app.py` | `SERVICE_ROOT`, `COMPOSE_DIR`, `CONFIG_FILE` |
| Cambiare la configurazione di default dei servizi | `config/services.example.json` | (file dati) |
| Cambiare le variabili d'ambiente | `.env.example` | (file dati) |

## Job start/stop

| Vuoi... | File | Entry point |
|---|---|---|
| Creare un job asincrono | `jobs.py` | `submit_job()` |
| Leggere un job dal DB | `jobs.py` | `db_get_job()` |
| Inizializzare lo schema del DB | `jobs.py` | `db_init()` |
| Salvare o aggiornare un job | `jobs.py` | `db_save_job()`, `db_update_job()` |
| Cambiare la dimensione del pool di job | `jobs.py` | `EXECUTOR` |
| Cambiare dove vive il DB dei job | `jobs.py` | `DB_FILE` |

## Operazioni Docker

| Vuoi... | File | Entry point |
|---|---|---|
| Sapere se la CLI docker c'e' | `docker_utils.py` | `docker_cli_available()` |
| Eseguire `docker compose up/down` | `docker_utils.py` | `run_compose()` |
| Decidere lo stato di un servizio | `docker_utils.py` | `get_status()` |
| Verificare che i container siano su | `docker_utils.py` | `verify_containers_running()` |
| Verificare che i container siano giu' | `docker_utils.py` | `verify_containers_down()` |
| Dedurre il nome del progetto compose | `docker_utils.py` | `detect_project_name()` |
| Cambiare il timeout dei comandi docker | `docker_utils.py` | `_run()` |

## Integrazione Uptime Kuma

| Vuoi... | File | Entry point |
|---|---|---|
| Leggere le metriche da Kuma | `kuma.py` | `fetch_kuma_metrics()` |
| Associare un monitor a un servizio | `kuma.py` | `find_kuma_monitor_for_service()` |
| Cambiare come si parsera le metriche Prometheus | `kuma.py` | `_parse_prom_metrics()` |
| Cambiare la cache delle metriche | `kuma.py` | `KUMA_CACHE_TTL`, `_KUMA_METRICS_CACHE` |
| Cambiare URL o chiave di Kuma | `kuma.py` | `UPTIME_KUMA_URL`, `UPTIME_KUMA_API_KEY` |

## Frontend

| Vuoi... | File | Entry point |
|---|---|---|
| Cambiare la pagina | `templates/index.html` | (template) |
| Cambiare il comportamento della UI | `static/main.js` | `render()`, `runJobAndPoll()`, `refresh()` |
| Cambiare le emoji di riserva delle icone | `static/main.js` | `iconMap` |
| Cambiare i ritocchi custom oltre Tailwind | `static/styles.css` | (file dati) |
| Cambiare le classi Tailwind disponibili | `tailwind.config.js` | `content` |
| Rigenerare il CSS Tailwind | `input.css` | (entry per la CLI) |

## Deploy e container

| Vuoi... | Dove |
|---|---|
| Cambiare i volumi e il socket docker | `docker-compose.yml` -> `services.dashboard.volumes` |
| Cambiare le env del container | `docker-compose.yml` -> `services.dashboard.environment` |
| Cambiare l'immagine base o il CMD | `Dockerfile` |
| Cambiare le dipendenze Python | `requirements.txt` |
| Gestire le dipendenze (Dependabot) | `.github/dependabot.yml` |
| Cambiare la CI di publish | `.github/workflows/docker-publish.yml` |

## Limiti noti (dove la mappa e' sottile)

- `app.py` -> `api_services()` e' lunga (oltre 100 righe): unisce caricamento
  servizi, match con Kuma e generazione delle card. Se cresce, separa il match.
- `docker_utils.py` -> `run_compose()` e' lunga (oltre 100 righe) per i tre livelli
  di fallback (compose, no-project, label). Se cresce, estrai i fallback.
- Nessun file supera il limite di 1000 righe dello repo; i piu' grandi sono
  `app.py` e `docker_utils.py`, entrambi sotto le 300 righe.
- `jobs.db` vive in `/app` (`jobs.py` -> `DB_FILE`) e non e' in un volume: la
  cronologia dei job si perde a ogni ricreazione del container.
- `static/images/` non esiste nel repo: `app.py` -> `user_image()` e il ramo
  `bundled` restano senza icone di riserva, quindi la UI usa le emoji di
  `static/main.js` -> `iconMap`.
- `__pycache__/app.cpython-313.pyc` e `.DS_Store` sono committati (bytecode di
  Python 3.13, mentre `Dockerfile` usa 3.14). `.gitignore` li copre ora; i file
  restano nello storico.
- `app.py` importa a vuoto `json`, `subprocess`, `uuid`, `threading`, `re`,
  `urllib.parse`, `time`, `requests`: sono morti, non si toccano in una PR di soli doc.
