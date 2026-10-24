# OPERATIONS — avvio, deploy, configurazione

<!-- Tipo: HOW-TO. I passi per un obiettivo. -->

## Avvio in locale (sviluppo)

```bash
cd dashboard
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Variabili d'ambiente (vedi `.env.example`):

```bash
export SERVICE_ROOT=/percorso/alla/cartella/servizi  # dove vivono services.json e i compose
export COMPOSE_DIR=./compose                          # usato solo se SERVICE_ROOT non e' settato
export PORT=5000
```

Avvio:

```bash
flask --app app.py run --host=0.0.0.0 --port=5000
```

> `FLASK_ENV=development` non e' piu' supportato da Flask 3: si usa `flask --debug`
> o il reloader di default in sviluppo.

L'app deve poter eseguire comandi Docker: l'utente che la esegue deve avere i
permessi Docker (gruppo `docker`).

## Avvio con Docker

```bash
docker build -t dashboard .
docker run -it --rm -p 5000:5000 \
  -e SERVICE_ROOT=/srv/services \
  -v /percorso/alla/cartella/servizi:/srv/services \
  dashboard
```

Oppure con il compose incluso (monta `./data` come `SERVICE_ROOT` e il socket Docker):

```bash
docker compose up --build
```

## Deploy

- La CI (`.github/workflows/docker-publish.yml`) parte su ogni push su `main` e
  pubblica `filippogrande/dashboard:latest` piu' il tag per SHA su Docker Hub
  (amd64/arm64).
- Il compose di produzione usa `image: filippogrande/dashboard:latest` con
  `pull_policy: always`: aggiornare = `docker compose pull && docker compose up -d`.
- Per buildare in locale, commentare `image:` e usare `build: .`.

## Struttura della cartella servizi

```
/percorso/alla/cartella/servizi/     # = SERVICE_ROOT
  services.json                      # la lista dei servizi
  images/                            # le icone
    home.svg
  home-assistant/docker-compose.yml
  transmission/docker-compose.yml
```

Se `SERVICE_ROOT` non esiste, all'avvio la dashboard lo crea e ci copia
`config/services.example.json` come `services.json`.

## Configurare un servizio

Modello in `config/services.example.json`:

```json
{
  "name": "Home Assistant",
  "icon": "home.svg",
  "compose": "home-assistant/docker-compose.yml",
  "controls": true,
  "url": "http://localhost:8123"
}
```

- `name`: etichetta mostrata.
- `icon`: nome file in `images/` (se contiene un punto e' un'immagine, altrimenti una
  chiave di `iconMap` in `static/main.js`).
- `compose`: path **relativo a `SERVICE_ROOT`** (o assoluto).
- `controls`: `false` nasconde i bottoni Avvia/Ferma.
- `url`: se presente, il clic sul riquadro apre l'URL in una nuova scheda.

## Integrazione Uptime Kuma

Imposta `UPTIME_KUMA_URL` (es. `http://kuma.local:3001`) e, se la tua versione di Kuma
lo richiede, `UPTIME_KUMA_API_KEY`. La dashboard legge l'endpoint Prometheus
`/metrics` di Kuma e mostra lo stato dei monitor che corrispondono a `url` o `name`
del servizio. Senza `UPTIME_KUMA_URL` tutto il resto funziona.

## Rigenerare il CSS Tailwind

```bash
npx tailwindcss -i input.css -o static/tailwind.css --minify
```

Poi bumpa `?v=N` in `templates/index.html`.

## Debug

- `LOG_LEVEL=DEBUG` alza il livello di log.
- `MATCH_DEBUG=1` accende i log di matching servizio <-> monitor Kuma
  (`matching_logger` in `app.py`).
- `KUMA_CACHE_TTL` cambia la cache delle metriche Kuma (default 15s).
