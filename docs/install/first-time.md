# Initial setup

Do these three things once, in this order. Each has its own page in the app.

## 1. Loading a map

Open **Settings** and find **Map region**.

1. Choose the state your drivers cover from the list, or choose *Other: paste a link to a map file* and paste a link to any OpenStreetMap `.osm.pbf` extract.
2. Press **Load region**.

The app downloads the road data and prepares it. A single state takes a few minutes. Progress is shown on the Settings page, and the top bar says *Preparing map…* until it is done, then *Map:* and the region's name.

Routes cannot be built until a map is ready, and an address outside the map cannot be routed.

See [Settings](../reference/settings.md#map-region) for more.

## 2. Adding drivers

Open **Drivers** and press **Add driver** for each one.

- Give a name and choose **Staff** or **Volunteer**.
- Set the **start location**: type the address, press **Find**, and adjust the pin on the map if it is not quite right. If the driver ends the day somewhere else, untick *Ends the day at the same place* and set that too.
- For a volunteer you can set limits: a maximum number of stops, a maximum driving time, and the zip codes they cover.

A driver without a start location is left out of the routes.

See [Drivers](../reference/drivers.md) for what each choice means.

## 3. Importing addresses (optional)

If you already keep a list of regular addresses, importing it saves confirming each address on the map one at a time on your first day.

Open **Addresses** and press **Import a list…**. Paste the rows from Excel: street address, unit number, city, state and zip, plus a column with the usual volunteer's name and a column of notes if you have them. Add the volunteers on the Drivers page first so their names match.

See [Addresses and import](../reference/addresses.md#importing-a-list) for the details.

You are now ready for the [daily workflow](../daily/paste.md).
