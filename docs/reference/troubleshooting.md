# Troubleshooting

## Starting the app on your computer

**"This needs 64-bit Python 3.12, 3.13 or 3.14."**
Install Python 3.13 from [python.org](https://www.python.org/downloads/) and start the app again. On Windows, tick "Add python.exe to PATH" in the installer.

**"The interface has not been built yet, and building it needs Node.js."**
Install Node.js 22 or newer from [nodejs.org](https://nodejs.org/) and start the app again.

**"Something is already using port 8080."**
Another copy of the app is running, or the Docker version is, or another program has the port. Close it, or start on another port: `start-local.bat --port 8081`.

**The window closed and the app stopped.**
The app runs in that window. Leave it open while you work, and start it again when you need it.

**The screens look the same after an update.**
Refresh the page with Ctrl+F5 so the browser fetches the new screens.

## The map

**"No map region is loaded yet. Routes cannot be built until one is ready."**
Open **Settings → Map region** and load your region. See [First-time setup](../install/first-time.md#1-load-a-map).

**"A map is already being prepared. Wait for it to finish."**
Only one region can be prepared at a time. Progress is shown on the Settings page.

**"Could not build the road network."**
The computer most likely ran out of memory or disk space. Try a smaller region: a single state, or a custom extract of just your area.

**The map is a blank grey area with pins on it.**
The map background could not be loaded: there is no internet connection, or the tile address in Settings is wrong. Pins and routes are still correct.

**"That location is outside the loaded map region."**
The place is not on your map, so no route can reach it. Check the address or the pin. If the place is real and you deliver there, load a region that covers it.

## The review table

**A row says "Fix this row".**
The reason is shown beside it: a missing street address, a missing or invalid zip code, or an unknown state. Correct the cell and press Enter.

**Every row is marked wrongly, with the city in the street column and so on.**
The columns were read in the wrong order. Open **Columns in your paste** above the paste box and set each dropdown. See [Paste the addresses](../daily/paste.md#if-the-columns-are-in-a-different-order).

**"Nothing was found for this address."**
The lookup could not find it. Correct the spelling in the table, or click the map to place the pin yourself. Another [lookup service](settings.md#address-lookup) may do better with that kind of address.

**"The lookup service could not be reached."**
Check the internet connection and try again. The address can also be placed by clicking the map.

## Building and adjusting routes

**The Build routes button cannot be pressed.**
A row still needs attention, or no driver is ticked. The reason is shown beside the button.

**"No working driver has a start and end location set."**
Set a start location for at least one of today's drivers on the **Drivers** page.

**A driver is missing from the routes.**
A line above the map says a driver "has no start and end location and was left out". Set one on the Drivers page and rebuild.

**"… stop(s) are not on any route."**
No staff driver is working, and the volunteers could not take those stops within their limits. Each stop shows its reason. Tick a staff driver, raise a limit, or move the stops by hand.

**"…'s addresses are locked."**
You tried to add a stop to a locked volunteer, take one of their usual stops away, or change their usual stops. Turn the lock off on the Drivers page first.

**"The route changed. Rebuild the routes, then try again."**
The list or the drivers changed since the routes were built. Press **Rebuild routes**.

**I moved one stop and others moved as well.**
Moving a stop rebuilds the day around it. A message lists what else changed. See [Other stops may move too](../daily/adjust.md#other-stops-may-move-too).

**A route came back in the opposite direction after a rebuild.**
When a loop takes exactly the same time either way round, either may be chosen. To fix the order, arrange the route by hand; it is then kept.

## Importing

**"An import is already running."**
Wait for it to finish. Its progress is shown in the import window.

**Every imported address was set aside for a map check.**
Either no map was loaded during the import, or the box to save confident addresses was unticked. Load a map and import again; addresses already set aside are updated, not duplicated.
