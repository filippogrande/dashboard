# Homeserver Dashboard (repo `dashboard`)

<!-- Radice della mappa: leggi QUESTO file per primo, sempre. -->
<!-- Tutto cio' che non serve ad OGNI task e' a un link di distanza. -->

Dashboard Flask per avviare/fermare i servizi docker-compose del home-lab e
mostrarne lo stato, con integrazione opzionale Uptime Kuma.

- Stack: Python 3.14, Flask, gunicorn, JS vanilla + Tailwind self-host
- Deploy: immagine `filippogrande/dashboard:latest` (buildata da GitHub Actions), compose locale
- Mappa del codice: `docs/REFERENCE.md`

## Comandi

| Azione | Comando |
|---|---|
| Avvio locale | `flask --app app.py run --host=0.0.0.0` |
| Avvio con compose | `docker compose up --build` |
| Build immagine | `docker build -t dashboard .` |
| Rigenera il CSS Tailwind | `npx tailwindcss -i input.css -o static/tailwind.css --minify` |

## Indice — richiesta -> dove

| Vuoi... | Apri |
|---|---|
| Trovare una funzione, una route, un file | `docs/REFERENCE.md` |
| Capire come funziona o perche' una scelta | `docs/ARCHITECTURE.md` |
| Conoscere le regole prima di scrivere codice | `docs/CONVENTIONS.md` |
| Avviare, deployare, configurare i servizi | `docs/OPERATIONS.md` |

## Documenti

| Doc | Tipo | A cosa serve |
|---|---|---|
| `docs/REFERENCE.md` | reference | la mappa: richiesta -> file -> entry point |
| `docs/ARCHITECTURE.md` | explanation | ciclo start/stop, stato dei container, ruolo di Kuma |
| `docs/CONVENTIONS.md` | how-to | regole di codice e di repo |
| `docs/OPERATIONS.md` | how-to | avvio, deploy, configurazione servizi |

## Regole

- Branch + PR, mai push su `main`.
- I doc — incluse le voci di questo indice — si aggiornano NELLA STESSA PR che li invalida.
- Limiti: 1000 righe/file, 50 righe/funzione, niente fallback silenziosi, niente file usa-e-getta.
- Mappa onesta: una riga che indica un path sbagliato si corregge subito, non si annota.
- `static/tailwind.css` e' generato: non si edita a mano, si rigenera con la CLI.
