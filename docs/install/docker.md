# Run it with Docker

Use this if you already run Docker, or if you want other computers on your network to open the app from one always-on machine. For one person on one computer, [running it directly](local.md) is simpler.

## Start it

You need Docker with Docker Compose.

```
docker compose up -d --build
```

On Windows you can double-click `start.bat` instead, which runs the same command.

Then open **http://localhost:8080**, or the computer's name on your network with port 8080.

Carry on with [First-time setup](first-time.md).

## Settings in `.env`

Copy `.env.example` to `.env` and edit it before starting. Every line is optional.

| Setting | What it does |
|---|---|
| `WEB_PORT` | The port the app is served on. Default 8080. |
| `WEB_BIND` | Who can open the app. Leave it out to let other computers on your network in. Set it to `127.0.0.1` to allow this computer only. |
| `DB_PASSWORD` | The database password. It is only used between the app's own containers. |
| `BACKUP_FOLDER` | Where the daily backup files are written on your disk. Default: a `backups` folder next to `docker-compose.yml`. |
| `BACKUP_KEEP` | How many daily backup files to keep. Default 30. |
| `TZ` | The app's time zone, which decides when "today" starts. Default US Eastern (`America/New_York`). |
| `DEFAULT_REGION_NAME`, `DEFAULT_REGION_URL` | A map to load automatically on the first start. You can also do this in Settings. |
| `GOOGLE_MAPS_API_KEY`, `MAPBOX_ACCESS_TOKEN`, `GEOCODIO_API_KEY` | Keys for a paid address lookup. You can also paste these in Settings. |

## What is inside

| Service | What it does |
|---|---|
| `web` | The screens and these help pages, served by nginx. |
| `api` | The app itself: data, planning, the routing engine and the optimizer. |
| `db` | A Postgres database. |

Two Docker volumes hold what matters: `pgdata` (drivers, addresses, plans) and `mapdata` (the prepared map). The daily backup files go to the `backups` folder on your own disk.

The routing engine is tested on ordinary Intel and AMD processors. On an ARM machine, such as a recent Mac, Docker runs it under emulation, which is slower.

## Updating

Replace the project files and run `docker compose up -d --build` again, or double-click `start.bat`. Your data is kept, and the database is brought up to date when the app starts.
