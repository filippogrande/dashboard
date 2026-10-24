# Homeserver Dashboard

Dashboard Flask per avviare/fermare i servizi docker-compose del home-lab e
mostrarne lo stato, con integrazione opzionale Uptime Kuma.

## Avvio rapido

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
flask --app app.py run --host=0.0.0.0
```

Oppure:

```bash
docker compose up --build
```

## Documenti

- [`AGENTS.md`](AGENTS.md) — da leggere per primo: comandi, indice, regole.
- [`docs/REFERENCE.md`](docs/REFERENCE.md) — la mappa: richiesta -> file -> entry point.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — come funziona (ciclo start/stop, stato, Kuma).
- [`docs/CONVENTIONS.md`](docs/CONVENTIONS.md) — le regole prima di aprire una PR.
- [`docs/OPERATIONS.md`](docs/OPERATIONS.md) — avvio, deploy, configurazione servizi.

## Struttura

```
app.py  services.py  jobs.py  docker_utils.py  kuma.py  gunicorn_config.py
config/  templates/  static/  docs/
Dockerfile  docker-compose.yml  requirements.txt  .env.example
```

Per i dettagli (configurazione di un servizio, variabili d'ambiente, deploy,
integrazione Kuma) vedi `docs/OPERATIONS.md`.
