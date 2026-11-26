# Backup and restore

A backup is one file that holds what would be painful to enter again:

- drivers and their settings
- every confirmed address, with its location, usual volunteer and note
- addresses set aside by an import
- settings, **including any API keys you saved**

It does **not** hold the map (load the region again) or past day plans.

## Automatic backups

The app writes a backup file by itself: shortly after it starts and then every few hours, one file per day, named for the date. It keeps the last 30 days and removes older files.

| How you run the app | Where the files go |
|---|---|
| On your computer, with `start-local` | `local-data\backups` in the project folder |
| With Docker | The `backups` folder next to `docker-compose.yml`, or the folder set as `BACKUP_FOLDER` in `.env` |

Under **Settings → Backup** you can see the latest file and press **Back up now** to write one immediately.

These files sit on the same disk as the app. Copy the folder to another disk or a cloud drive from time to time.

## Manual backups

**Settings → Backup → Download backup** saves a backup file through your browser.

## Restoring

**Settings → Backup → Load a backup file…**, then choose a backup file, either one you downloaded or one from the automatic folder.

!!! warning
    Loading a backup **replaces** every driver, address and setting with what is in the file, and **clears the saved day plans**. You are asked to confirm first.

If the file cannot be loaded, nothing is changed.

After a restore, load the map region again if the app is a fresh install.
