# Security and privacy

Route Planner is built for one dispatcher on a computer or network you control. This page says what that means in practice.

## No login

Anyone who can open the app can see and change everything in it: drivers, addresses, notes and settings. They can also use any API key you saved, although a saved key is never shown again.

So the question that matters is **who can open it**.

| How you run it | Who can open it |
|---|---|
| On your computer, with `start-local` | **This computer only.** Other computers on your network are refused. |
| With Docker, as shipped | Any computer on your network that can reach this one on port 8080. |
| With Docker and `WEB_BIND=127.0.0.1` in `.env` | This computer only. |

Never make the app reachable from the internet, for example by forwarding a port on your router to it.

If you run it on your own computer and want a colleague's computer to open it too, start it with `--host 0.0.0.0` (see [Running locally](../install/local.md#launch-options)), and only on a network you trust.

## Data sent to other services

Routes are worked out on your computer. These are the only things sent elsewhere:

| What | Goes to | When |
|---|---|---|
| A new address | The address lookup you chose: the US Census Bureau or OpenStreetMap Nominatim by default, or Google, Mapbox or Geocodio if you set one up | Only when a new address is checked or imported. Known addresses are never sent again. |
| Which part of the map you are looking at | The map background provider, OpenStreetMap by default | Whenever a map is on screen |
| A request for map data | Geofabrik, or the link you gave | When you load a region |
| The stops on a route, as map coordinates | Google Maps, on the driver's phone | Only when a driver scans a QR code or opens its link. The codes themselves are made on your computer. |

Names of drivers, notes, and your list as a whole are not sent anywhere.

## Stored data

The database holds your drivers, addresses, notes, day plans and settings. API keys are stored in it as they are, without encryption, and are included in [backup files](backup.md).

Treat the `local-data` folder (or the Docker volumes) and any backup file as you would the spreadsheet the addresses came from.

## Known vulnerabilities in dependencies

The app is built on other people's software: Python and JavaScript packages, and for Docker, a web server and a database. Known security problems in those are published as CVEs and advisories.

**Checked on 2026-11-25:**

- **Python packages** (the app itself, the routing engine, the optimizer, the database driver): no known vulnerabilities.
- **JavaScript packages that run in your browser:** no known vulnerabilities.
- **JavaScript build tools:** the version of the build tool then in use had known problems in its development server, which is not used when the app is run for real. It has been upgraded to a version with none.
- **Docker web server:** the image used a branch of nginx that no longer receives security fixes. It has been moved to the current stable branch. Running the app directly on your computer does not use nginx at all.

The Docker images' operating system packages were not scanned.

### Re-checking

New problems are found all the time, so a clean result today says nothing about next year. To check again, from the project folder:

```
pip install pip-audit
pip-audit -r backend/requirements.txt

cd frontend
npm audit
```

Both print "no known vulnerabilities" or a list of what was found and which version fixes it. Staying up to date is the fix: update the versions in `backend/requirements.txt` and `frontend/package.json`, run the tests, and start the app again.
