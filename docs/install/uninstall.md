# Removing it

Route Planner does not install itself anywhere else on your computer. It adds no shortcuts, no services and no registry entries. Removing it means stopping it and deleting what it made.

!!! warning "Keep a backup first if you may want the data again"
    Removing the app deletes your drivers, addresses, usual stops, notes and settings. If you might set it up again, open **Settings → Backup**, press **Download backup** and keep the file somewhere outside the project folder. See [Backup and restore](../reference/backup.md).

## If you ran it on your computer

1. Stop the app: press `Ctrl+C` in its window, or close the window.
2. Delete the project folder.

That removes everything, because the app keeps all of it inside that folder:

| Inside the project folder | What it is |
|---|---|
| `local-data` | The database, the map and the daily backup files. |
| `.venv` | The app's own copy of its Python packages. |
| `.local-build` | The built help pages, and notes on what has been built. |
| `frontend/node_modules`, `frontend/dist` | The screens' build tools and the built screens. |

If you started it with `--data` pointing at another folder, delete that folder too.

### Optional: what is left outside the folder

- **Download caches.** Python and Node.js keep copies of downloaded packages so that other programs can reuse them. They are shared, not Route Planner's own, and safe to leave. To clear them anyway, run `python -m pip cache purge` and `npm cache clean --force`.
- **Python and Node.js themselves.** Uninstall them like any other program (on Windows: **Settings → Apps → Installed apps**), but only if nothing else on the computer uses them.

## If you ran it with Docker

1. Open a terminal in the project folder, the one with `docker-compose.yml` in it.
2. Run:

        docker compose down --volumes --rmi all

    This stops and removes the app's containers, deletes its two volumes (`pgdata`, which holds the database, and `mapdata`, which holds the map), and removes the images it built and the Postgres image it downloaded.

3. Delete the `backups` folder, or the folder you set as `BACKUP_FOLDER` in `.env`. Docker does not remove it, because it is an ordinary folder on your disk.
4. Delete the project folder.

Run step 2 from the project folder before deleting it, and without renaming the folder first: Docker names the app's containers and volumes after the folder, and uses that name to find them.

### Optional: Docker's build cache

Docker keeps intermediate build steps so that the next build is faster. To clear them, run `docker builder prune`. This clears the cache for every project on the computer, not only this one. Leave it if you build other things with Docker.

## API keys

If you saved a key for a paid address lookup (Google, Mapbox or Geocodio) and no longer need it, delete or disable it in that provider's account as well. Removing the app deletes the copy it kept, not the key itself.
