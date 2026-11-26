# Run it on your computer

This is the simplest way to run Route Planner for one person on one computer. It does not need Docker. The app runs in a window on your computer and you use it in your browser.

## What you need

| | |
|---|---|
| **Python** | 64-bit Python 3.12, 3.13 or 3.14. If you are installing it now, choose 3.13 from [python.org](https://www.python.org/downloads/). On Windows, tick "Add python.exe to PATH" in the installer. |
| **Node.js** | Version 22 or newer, from [nodejs.org](https://nodejs.org/). It is only used to build the screens the first time, and again after an update. |
| **Disk and memory** | Preparing the map for one US state needs a few gigabytes of memory and of disk space. Larger areas need more. |
| **Internet** | For the first run (to download the app's packages), to download the map, to look up new addresses, and to show the map background. Routes themselves are worked out on your computer. |

## Start it

1. Put the project folder somewhere permanent, for example `Documents\route-planner`.
2. Start the app:
    - **Windows:** double-click `start-local.bat`.
    - **Linux:** run `./start-local.sh` in a terminal.
3. Wait. The first run takes a few minutes while it installs the app's packages and builds the screens. Later starts take a few seconds.
4. Your browser opens at **http://localhost:8080**. If it does not, open that address yourself.

Leave the window open while you use the app. To stop the app, press `Ctrl+C` in that window or close it.

Then carry on with [First-time setup](first-time.md).

## Where your data is kept

Everything the app keeps is in the `local-data` folder inside the project folder:

| Inside `local-data` | What it is |
|---|---|
| `routeplanner.db` | Drivers, addresses, usual stops, notes, settings and day plans. |
| `map` | The prepared map for your region. |
| `backups` | A [backup file](../reference/backup.md) for each day, written automatically. |

Copy the `backups` folder somewhere safe from time to time. To move the whole app to another computer, copy the project folder including `local-data`.

## Who can open it

Started this way, the app listens on **this computer only**. Other computers on your network cannot open it. That is deliberate: the app has no login. See [Security and privacy](../reference/security.md) if you need to open it up.

## Options

Run the launcher from a terminal to change how it starts:

```
python run_local.py --port 9000        use another port
python run_local.py --no-browser       do not open the browser
python run_local.py --data D:\routes   keep the data somewhere else
python run_local.py --host 0.0.0.0     let other computers on your network open it (there is no login)
```

On Windows, `start-local.bat` passes the same options on, for example `start-local.bat --port 9000`.

## Updating

Replace the project files with the new version, keeping your `local-data` folder, and start it again. The launcher notices what changed and reinstalls or rebuilds only that. The database is brought up to date on start-up and your data is kept.

## Removing it

See [Removing it](uninstall.md).

## What has been tested

This way of running the app is checked automatically on Linux and on Windows each time the code changes: the launcher installs everything, starts the app and confirms that the app, its screens and these help pages answer. The app's own tests, which build a small map and plan routes on it, also run on both.

It has not been tried on a Mac. Use [Docker](docker.md) there.
