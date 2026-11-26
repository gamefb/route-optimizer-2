# Route Planner

**[Read the guide](https://gamefb.github.io/route-optimizer-2/)** for setup and day-to-day use. In the running app, the same pages open from **Help** in the top bar, and their sources are in [`docs/`](docs/index.md).

An internal web app for planning daily shipping routes across staff and volunteer drivers.

Each day the dispatcher pastes that day's addresses from Excel. The app matches them to addresses it already knows, has the dispatcher confirm any new ones on a map, hands the stops out (volunteers first, up to their limits, then staff), and produces a route per driver. Results export as a CSV or as printable driver sheets.

## Start it

There are two ways. Both end with the app at **http://localhost:8080**.

### On your own computer, without Docker

The simplest choice for one person on one computer. You need 64-bit Python 3.12 to 3.14, and Node.js 22 or newer to build the screens.

- **Windows:** double-click `start-local.bat`
- **Linux:** `./start-local.sh`

The first start takes a few minutes while it installs the app's packages and builds the screens. Leave the window open while you use the app. Everything it keeps (the database, the map, daily backups) is in the `local-data` folder.

Started this way the app can be opened from this computer only. `python run_local.py --help` lists the options.

### With Docker

You need Docker with Docker Compose.

```bash
docker compose up -d --build
```

On Windows, `start.bat` runs the same command. To change the port or database password, copy `.env.example` to `.env` and edit it first.

> **There is no login.** Anyone who can reach the app can use and change it. With Docker, other computers on your network can open it unless you set `WEB_BIND=127.0.0.1` in `.env`. Never expose it to the public internet.

## First-time setup

1. **Settings → Map region.** Pick the state your drivers cover (or paste a link to any OpenStreetMap `.osm.pbf` extract) and press **Load region**. The app downloads the road data and prepares it. A single state takes a few minutes and a few gigabytes of memory; larger areas take longer and need a bigger machine. Routes cannot be built until a region is ready.
2. **Drivers.** Add each driver as staff or volunteer, with a start location and (if different) an end location.
   - **Staff:** no limits and no usual stops.
   - **Volunteers:** optional maximum stops, maximum route time (driving minutes) and assigned zip codes, plus an optional lock.
3. **Addresses → Import a list** (optional). Paste your existing address list from Excel, with a column for the usual volunteer's name and a column of notes if you have them. Addresses the lookup is confident about are saved straight away; the rest are set aside for a quick map check. This saves confirming every address one by one on the first day.

## Daily use

1. **Paste.** Copy the rows in Excel and paste them into the Day plan page. One address per row; columns are street address, unit number, city, state, zip; no header row. The app works out which column is which and shows its guess above the table, where you can correct it. The layout is remembered.
2. **Review.** Each row is marked *Matched*, *Possible match*, *New address* or *Fix this row*. Every cell is editable.
3. **Check new addresses.** Each new address is shown as a pin on a map next to what the lookup found. Confirm it, drag the pin, or click the right spot. A confirmed address is saved and never asked about again.
4. **Drivers and options.** Tick who is working, choose fastest time or least miles, and set the time drivers leave.
5. **Build routes.** Volunteers get their usual stops, then are filled up to their limits with extra stops. Staff share the rest. Each route is put in the best order for the day's choice of time or miles.
6. **Adjust.** Move a stop to another driver for the day (drag it onto their list, or use its *Move* menu), drag a stop to a new place in its route (or nudge it with the arrows), add a note to an address, or make a volunteer's extra stop one of their usual stops. **Undo** reverses the last "make usual".
7. **Export.** Download the CSV (list order, with list order number, driver, stop number, estimated arrival and notes columns), or open the driver sheets (driving order, with each stop's list order number beside it) and print them, save them as PDF, or download each as an image. Each sheet carries QR codes that open the route in Google Maps on a phone.

### How stops are handed out

- A volunteer's **usual stops** go to them whenever they are on the day's list.
- Volunteers are then **filled to the fullest** their limits allow with other stops in their zip codes. These extras are for that day only and are labeled *Added today*, unless you press **Make usual stop**.
- A volunteer with **no limits at all** (and not locked) keeps their usual stops but is otherwise treated like staff: they share the leftover stops evenly instead of being filled first.
- **Staff** take everything else. By default the leftover stops are shared roughly evenly by stop count among the staff drivers working that day. Settings → Planning can switch this to sharing by driving time, or turn it off.
- A **locked** volunteer gets exactly their usual stops: nothing is added and nothing can be moved away.
- When a volunteer is **off for the day**, their stops are covered by others for that day and stay theirs.
- **Avoid highways** is a strong preference, not a ban: a highway is still used where there is no reasonable alternative. For a highway-averse driver under *least miles*, the stop order is chosen for least miles while each leg follows the fastest non-highway road.
- A volunteer's maximum route time means **driving time only**.
- **Estimated arrival times** are the day's start time, plus driving, plus a set number of minutes at each earlier stop (Settings → Planning, 5 by default). They are estimates and do not affect who gets which stop.
- **Notes** belong to the address, so they come back every time that address is on a list, and print on the driver sheet.
- **Moving a stop** to another driver rebuilds the day around it, so other stops can change driver too. When that happens the app lists them.
- Once routes are built, the review table shows each row's **driver and stop number**, and its search finds rows by driver.
- A route **arranged by hand** keeps that order when routes are rebuilt, until you press *Back to automatic order*. Rearranging a route recalculates only that route; who has which stop does not change.
- **Google Maps links** hold at most 10 places each, so a longer route gets several QR codes, each starting where the last one ended.

## What is inside

| Service | What it does |
|---|---|
| `web` | The interface (React) and the help pages, served by nginx. |
| `api` | Python (FastAPI). Holds the data and the planning logic. Runs the Valhalla routing engine and the VROOM optimizer in-process. |
| `db` | Postgres. |

Two Docker volumes hold everything that matters: `pgdata` (drivers, addresses, plans) and `mapdata` (the prepared map).

**Automatic backups.** Every day the app writes a backup file into the `backups` folder next to `docker-compose.yml` on your own disk, keeping the last 30. Copy that folder wherever you keep backups. To put it elsewhere, set `BACKUP_FOLDER` in `.env`.

**Backups by hand.** Settings → Backup downloads one file with your drivers, addresses, usual stops, notes and settings, and can load it back. Loading a backup replaces what is there and clears saved day plans. Download one regularly and keep it somewhere safe; it includes any API keys you saved.

**Updating.** Replace the project files and run `docker compose up -d --build` again (or double-click `start.bat` on Windows). Your data is kept, and the database is upgraded in place.

### Outside services the app calls

| What | Service | Notes |
|---|---|---|
| Address lookup | US Census geocoder (default) or OpenStreetMap Nominatim | Free, no key. Only *new* addresses are looked up, once each. |
| Address lookup (optional, paid) | Google, Mapbox or Geocodio | Paste the key under Settings → Address lookup, or set it in `.env`. The paid lookups have not been tried against the live services yet. |
| Map data | The link you choose in Settings (Geofabrik by default) | Downloaded once per region. |
| Map background | OpenStreetMap tiles, loaded by the browser | Fine for light internal use; the tile address can be changed in Settings. |

Routing and optimization run locally and need no outside service.

## Development

```bash
# API
cd backend
pip install -r requirements-dev.txt
python -m pytest                      # builds a small made-up street grid and runs the whole workflow on it
ruff check . && ruff format .         # lint, then format
uvicorn app.main:app --reload         # uses a local SQLite file unless DATABASE_URL is set

# Interface
cd frontend
npm install
npm run dev                           # http://localhost:5173, forwards /api to localhost:8000
npm run lint && npm run format        # lint, then format

# Help pages (the docs folder)
pip install -r docs/requirements.txt
mkdocs serve                          # http://localhost:8000 with live reload; "mkdocs build --strict" checks every link
```

The guide is also published to GitHub Pages by `.github/workflows/pages.yml`, each time a change to `docs/` or `mkdocs.yml` reaches `main`. That needs **Settings → Pages → Source** set to **GitHub Actions** in the repository, once.

The same checks (lint, formatting, tests, build) run on every pull request; see `.github/workflows/ci.yml`.

**Where things are.**

| Path | What is there |
|---|---|
| `backend/app/api/` | The endpoints, one file per area: `setup` (settings, region, lookup), `drivers`, `addresses`, `day` (the pasted list and review table), `routes` (building and adjusting routes, CSV), `imports`, `backup`. `shared.py` holds what they have in common. |
| `backend/app/planner.py` | Who takes which stop and in what order. `compute()` is the outline; each step is a function below it. |
| `backend/app/optimizer.py`, `routing.py` | The VROOM optimizer and the Valhalla routing engine. |
| `backend/app/matching.py`, `parsing.py` | Reading pasted rows and matching them to known addresses. |
| `backend/app/db.py`, `models.py` | The database tables, and the in-place upgrade run at start-up. |
| `docs/`, `mkdocs.yml` | The help pages, built into the app at `/help/`. |
| `run_local.py` | Runs the app without Docker: sets up Python packages, builds the screens and help pages, and serves everything from one process. |
| `frontend/src/` | One file per page (`DayPage`, `DriversPage`, `AddressesPage`, `SettingsPage`, `PrintPage`), with shared pieces in `ui.tsx`, `useAction.ts`, `routePins.ts` and `util.ts`. |

**Try it offline.** `cd frontend && npm run build`, then `cd backend && python -m tests.demo_server` and open http://localhost:8000. This runs the full app on a made-up 10 by 10 street grid with a fake address lookup. Addresses look like `37 Grid St` (the number picks the spot). The map background will be blank without internet, but pins and routes are drawn.

## Notes and limits

- The routing library is tested on x86-64. `docker-compose.yml` pins the `api` service to `linux/amd64`, which runs under emulation on ARM machines.
- Addresses are assumed to be in the United States (state and 5-digit zip).
- Changing the region does not remove known addresses. Addresses outside the new region cannot be routed until a region covering them is loaded.
