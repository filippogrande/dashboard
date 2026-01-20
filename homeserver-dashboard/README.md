Homeserver Dashboard

Semplice dashboard per avviare/fermare servizi docker-compose.

Prerequisiti

- Python 3.10+
- Docker & Docker Compose (comando `docker compose` disponibile)

Installazione

```bash
cd homeserver-dashboard
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Configurazione

- Copia `config/services.example.json` → `config/services.json` e modifica i servizi.
- Imposta la cartella dei docker-compose (default `./compose`) con la variabile d'ambiente `COMPOSE_DIR` se serve.

Campo `url` nei servizi

- Ogni servizio può aggiungere il campo `url` (es. `"url": "http://localhost:8123"`).
- Cliccando sul riquadro del servizio si aprirà l'`url` in una nuova scheda, mantenendo aperta la dashboard.

Icone come immagini

- Metti le icone nella cartella `static/images/` (es. `static/images/home.svg`).
- Nel `config/services.json` imposta `"icon": "home.svg"` (nome file). Se l'immagine non è trovata, verrà usata un'icona di fallback.

Esecuzione

```bash
export FLASK_APP=app.py
export FLASK_ENV=development
export COMPOSE_DIR=./compose
flask run --host=0.0.0.0
```

Note

- L'app deve poter eseguire comandi Docker (l'utente che la esegue deve avere permessi Docker).
- Lo stato viene determinato con `docker compose -f <file> ps` (se "Up" è considerato running).

Esecuzione tramite Docker

- Prepara una cartella sul tuo host che conterrà: `services.json`, una sottocartella `images/` con le icone, e i `docker-compose.yml` (possono essere in sottocartelle). Esempio struttura:

```
/path/to/services-folder/
	services.json
	images/
		home.svg
	home-assistant/
		docker-compose.yml
	transmission/
		docker-compose.yml
```

- Avvia con `docker run` montando la cartella come `SERVICE_ROOT`:

```bash
docker build -t homeserver-dashboard .
docker run -it --rm -p 5000:5000 -e SERVICE_ROOT=/srv/services -v /path/to/services-folder:/srv/services homeserver-dashboard
```

- Oppure usa `docker-compose.yml` già incluso: monta la tua cartella in `./data` o modifica `volumes` nel file. Poi:

```bash
docker compose up --build
```

L'app cercherà `services.json` in `SERVICE_ROOT` e servirà le icone da `/images/<file>` collegandosi ai docker-compose relativi a quella cartella.

Integrazione Uptime Kuma (opzionale)

- Se hai un'istanza di Uptime Kuma puoi farla interrogare dalla dashboard per mostrare lo stato dei monitor.
- Imposta le variabili d'ambiente quando avvii il container o l'app locale:

```
export UPTIME_KUMA_URL="http://host:3001"
# opzionale
export UPTIME_KUMA_API_KEY="<api-key>"
```

- La dashboard proverà a chiamare l'endpoint `/api/getMonitors` (o varianti) su `UPTIME_KUMA_URL`. Se trova monitor che corrispondono al `url` o al `name` del servizio li mostrerà nella risposta API (`uptime_monitor` e `uptime`).
- Nota: l'API di Uptime Kuma può richiedere autenticazione/chiave a seconda della versione; la dashboard tenterà di usare un header `Authorization: Bearer <key>` se `UPTIME_KUMA_API_KEY` è impostata.
