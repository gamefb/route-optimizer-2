# Moving between the two

You can move from the Docker version to running the app directly on your computer, or the other way. Drivers, addresses, usual stops, notes and settings move in a backup file. The map and past day plans do not.

## From Docker to your computer

1. In the Docker version, open **Settings**, find **Backup** and press **Download backup**. Keep the file.
2. Stop the Docker version, or start the other one on a different port. Both use port 8080 unless told otherwise.
3. Start the app on your computer: see [Run it on your computer](local.md).
4. Open **Settings**, find **Backup**, press **Load a backup file…** and choose the file.
5. Under **Map region**, load your region again. The map is prepared afresh.

Your first day plan after the move starts empty. Addresses you had already confirmed are still known, so pasted rows match as before.

## From your computer to Docker

The steps are the same in the other direction: download a backup from the app on your computer, start the Docker version, load the backup there, then load the map region.

!!! warning "Loading a backup replaces what is there"
    Loading a backup replaces every driver, address and setting in the app you load it into, and clears its saved day plans. See [Backup and restore](../reference/backup.md).
