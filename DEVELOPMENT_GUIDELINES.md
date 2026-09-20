# DEVELOPMENT_GUIDELINES — Dashboard

> Versione: 1.0 — 2026-09-20

Paletti di sviluppo per il repo **filippogrande/dashboard**. Pensa a questo file come al contratto: le regole qui sotto vanno rispettate in ogni PR.

## Indice

- [Struttura del progetto](#struttura-del-progetto)
- [Linguaggio e stile](#linguaggio-e-stile)
- [Dimensione dei file](#dimensione-dei-file)
- [Tailwind self-host](#tailwind-self-host)
- [Dipendenze e Dependabot](#dipendenze-e-dependabot)
- [Segreti](#segreti)
- [Dove vivono le task](#dove-vivono-le-task)

## Struttura del progetto

```
app.py               # entrypoint Flask (routes API + index)
services.py          # caricamento services.json + risoluzione path compose
jobs.py              # job start/stop asincroni (ThreadPoolExecutor + SQLite)
docker_utils.py      # run_compose, get_status, verifica post-azione
kuma.py              # integrazione Uptime Kuma (metrics)
gunicorn_config.py   # config gunicorn (workers/threads)
requirements.txt     # dipendenze Python
Dockerfile           # build immagine
input.css            # entry per Tailwind CLI
static/              # asset serviti staticamente
  main.js            # frontend (vanilla JS)
  styles.css         # ritocchi custom oltre Tailwind
  tailwind.css       # CSS compilato (generato, NON editare a mano)
  images/            # icone
config/              # services.example.json
templates/           # index.html
.github/workflows/   # CI/CD
```

## Linguaggio e stile

- Backend: Python (Flask), moduli divisi per responsabilità.
- Frontend: **JS vanilla**, niente build-step, niente ES6 import/export (tutto su DOM).
- Le route API iniziano con `/api/`. Le operazioni Docker sono asincrone (job) e mai bloccanti nel thread HTTP.

## Dimensione dei file

- Nessun file supera le **1000 righe**. Meglio tanti moduli piccoli e coesi che pochi file grossi.
- Se un file cresce sopra ~900 righe, spezzalo per **coesione semantica** (non a numero di righe).
- Ogni funzione/route resta sotto ~50 righe.

## Tailwind self-host

Molto importante: **NON usare `cdn.tailwindcss.com`.** Il CDN è un compilatore JS runtime che ha causato il bug dell'UI senza CSS su Safari.

- Le classi Tailwind sono compilate in `static/tailwind.css` con la CLI.
- In `index.html` il CSS è caricato con `<link href="/static/tailwind.css?v=N">`.
- **Quando aggiungi classi Tailwind nuove**, rigenera il CSS:
  ```bash
  npx tailwindcss -i input.css -o static/tailwind.css --minify
  ```
- Non editare `static/tailwind.css` a mano: è output generato.
- Bumpa sempre `?v=N` su CSS/JS quando cambi un asset (cache-busting anti-Safari).

## Dipendenze e Dependabot

- `requirements.txt` copre: pip. `Dockerfile` copre: docker. `docker-compose.yml` copre: docker-compose. `github-actions` copre il workflow (se presente).
- **Ogni manifest ha la sua voce in `.github/dependabot.yml`**, aggiornata nella STESSA PR che tocca il manifest.
- Le dipendenze Python sono **vincolate** con `>=` minimo (es. `Flask>=3.1.3`): senza specifier Dependabot e gli alert di sicurezza non vedono nulla.
- Quando mergi una PR Dependabot su `requirements.txt`, verifica l'ordine di merge: due bump che toccano lo stesso file possono creare conflitti (es. #11 e #14). Merge in sequenza o in un'unica PR.

## Segreti

- `.env` e `.env.local` non si committano (vedi `.env.example` per i nomi delle variabili).
- `SERVICE_ROOT`, `UPTIME_KUMA_URL`, `UPTIME_KUMA_API_KEY` arrivano da env del container, mai hardcoded nel codice.
- Il file `services.json` reale (con URL/porte interne) non va committato: esiste solo nel volume montato.
- Il docker socket è montato read-only (`:ro`), e il container NON deve mai chiamare `docker rm`/`compose down` indiscriminatamente.

## Dove vivono le task

- Le task del progetto Dashboard vivono in **Vikunja** (progetto Dashboard).
- Chiude una task solo quando il fix è mergiato e verificato, non quando è aperta la PR.
