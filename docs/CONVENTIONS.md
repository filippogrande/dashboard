# CONVENTIONS — regole del repo

<!-- Tipo: HOW-TO. Le regole da rispettare prima di aprire una PR. -->

## Indice

- [Struttura del progetto](#struttura-del-progetto)
- [Linguaggio e stile](#linguaggio-e-stile)
- [Dimensione dei file](#dimensione-dei-file)
- [Documentazione](#documentazione)
- [Tailwind self-host](#tailwind-self-host)
- [Dipendenze e Dependabot](#dipendenze-e-dependabot)
- [Segreti](#segreti)
- [Dove vivono le task](#dove-vivono-le-task)

## Struttura del progetto

```
app.py               # entrypoint Flask (route API + index)
services.py          # caricamento services.json + risoluzione path compose
jobs.py              # job start/stop asincroni (ThreadPoolExecutor + SQLite)
docker_utils.py      # run_compose, get_status, verifica post-azione
kuma.py              # integrazione Uptime Kuma (metriche Prometheus)
gunicorn_config.py   # config gunicorn (workers/threads)
requirements.txt     # dipendenze Python
Dockerfile           # build immagine
input.css            # entry per Tailwind CLI
static/              # asset serviti staticamente
  main.js            # frontend (vanilla JS)
  styles.css         # ritocchi custom oltre Tailwind
  tailwind.css       # CSS compilato (generato, NON editare a mano)
config/              # services.example.json
templates/           # index.html
docs/                # documentazione (mappa, architettura, regole, operazioni)
.github/             # dependabot.yml + workflows/docker-publish.yml
```

In root restano solo: `README.md`, `AGENTS.md`, `requirements.txt`, `.gitignore`,
`.gitattributes`, `Dockerfile`, `docker-compose.yml`, `.env.example`, i manifest
JS (`tailwind.config.js`, `input.css`) e le cartelle.

## Linguaggio e stile

- Backend: Python (Flask), moduli divisi per responsabilita'.
- Frontend: **JS vanilla**, niente build-step, niente ES6 import/export (tutto su DOM).
- Le route API iniziano con `/api/`. Le operazioni Docker sono asincrone (job) e mai
  bloccanti nel thread HTTP.
- Commit in conventional commit (`docs:`, `fix:`, `feat:`, `deps:`).

## Dimensione dei file

- Nessun file supera le **1000 righe**. Meglio tanti moduli piccoli e coesi che pochi
  file grossi.
- Se un file cresce sopra ~900 righe, spezzalo per **coesione semantica** (non a
  numero di righe).
- Ogni funzione/route resta sotto ~50 righe.
- Se un file viola questa regola, la PR lo segnala in "Limiti noti" di
  `docs/REFERENCE.md`: non si rifattorizza nel Grigno della documentazione.

## Documentazione

- I doc stanno in `docs/`, un doc per tipo: **reference** (fatti), **explanation**
  (come/perche'), **how-to** (passi per un obiettivo), **tutorial** (raro).
- `docs/REFERENCE.md` e' la mappa: una riga per richiesta, verso un file reale e un
  simbolo reale. **Mai numeri di riga**: le righe si muovono, i simboli no.
- I doc — incluse le voci dell'indice in `AGENTS.md` — si aggiornano **nella stessa PR**
  che li invalida. Un doc che mente e' peggio di nessuna doc.
- Un solo doc per concetto: se due doc dicono la stessa cosa, si consolidano.
- Solo documentazione: una PR che riorganizza i doc non tocca codice.

## Tailwind self-host

Molto importante: **NON usare `cdn.tailwindcss.com`.** Il CDN e' un compilatore JS
runtime che ha causato il bug dell'UI senza CSS su Safari.

- Le classi Tailwind sono compilate in `static/tailwind.css` con la CLI.
- In `index.html` il CSS e' caricato con `<link href="/static/tailwind.css?v=N">`.
- **Quando aggiungi classi Tailwind nuove**, rigenera il CSS:
  ```bash
  npx tailwindcss -i input.css -o static/tailwind.css --minify
  ```
- Non editare `static/tailwind.css` a mano: e' output generato.
- Bumpa sempre `?v=N` su CSS/JS quando cambi un asset (cache-busting anti-Safari).

## Dipendenze e Dependabot

- `requirements.txt` copre: pip. `Dockerfile` copre: docker. `docker-compose.yml`
  copre: docker-compose. `github-actions` copre il workflow.
- **Ogni manifest ha la sua voce in `.github/dependabot.yml`**, aggiornata nella STESSA
  PR che tocca il manifest.
- Le dipendenze Python sono **vincolate** con `>=` minimo (es. `Flask>=3.1.3`): senza
  specifier Dependabot e gli alert di sicurezza non vedono nulla.
- Quando mergi una PR Dependabot su `requirements.txt`, verifica l'ordine di merge:
  due bump che toccano lo stesso file possono creare conflitti. Merge in sequenza o in
  un'unica PR.

## Segreti

- `.env` e `.env.local` non si committano (vedi `.env.example` per i nomi delle variabili).
- `SERVICE_ROOT`, `UPTIME_KUMA_URL`, `UPTIME_KUMA_API_KEY` arrivano da env del
  container, mai hardcoded nel codice.
- Il file `services.json` reale (con URL/porte interne) non va committato: esiste solo
  nel volume montato.
- Il docker socket e' montato read-only (`:ro`), e il container NON deve mai chiamare
  `docker rm`/`compose down` indiscriminatamente. Il fallback per label in
  `docker_utils.py` -> `run_compose()` e' voluto e resta dentro quel file.
- I token Docker Hub vivono nei secret del repo (`DOCKERHUB_USERNAME`,
  `DOCKERHUB_TOKEN`), non nei doc.

## Dove vivono le task

- Le task del progetto Dashboard vivono in **Vikunja** (progetto Dashboard).
- Chiude una task solo quando il fix e' mergiato e verificato, non quando e' aperta la PR.
