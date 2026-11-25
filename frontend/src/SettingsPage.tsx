import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { RegionInfo, Settings, SettingsPatch } from "./types";
import { Badge, ErrorNote } from "./ui";
import { useAction } from "./useAction";

const PAID = [
  {
    id: "google",
    name: "Google",
    key: "google_key",
    has: "has_google_key",
    hint: "Google Maps Platform key with the Geocoding API turned on",
  },
  { id: "mapbox", name: "Mapbox", key: "mapbox_key", has: "has_mapbox_key", hint: "Mapbox access token" },
  { id: "geocodio", name: "Geocodio", key: "geocodio_key", has: "has_geocodio_key", hint: "Geocodio API key" },
] as const;

export default function SettingsPage({
  settings,
  region,
  onSettings,
  reloadRegion,
  reloadAll,
}: {
  settings: Settings;
  region: RegionInfo | null;
  onSettings: (s: Settings) => void;
  reloadRegion: () => void;
  reloadAll: () => void;
}) {
  const [catalog, setCatalog] = useState<{ name: string; url: string }[]>([]);
  const [choice, setChoice] = useState("");
  const [customName, setCustomName] = useState("");
  const [customUrl, setCustomUrl] = useState("");
  const [tileUrl, setTileUrl] = useState(settings.tile_url);
  const [minutes, setMinutes] = useState(String(settings.minutes_per_stop));
  const [keys, setKeys] = useState<Record<string, string>>({});
  const { error, run } = useAction();
  const [notice, setNotice] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const [auto, setAuto] = useState<{ enabled: boolean; keep: number; files: { name: string; bytes: number }[] } | null>(
    null,
  );
  const loadAuto = () =>
    api
      .backupFiles()
      .then(setAuto)
      .catch(() => setAuto(null));
  useEffect(() => {
    loadAuto();
  }, []);

  useEffect(() => {
    api
      .regionCatalog()
      .then(setCatalog)
      .catch(() => setCatalog([]));
  }, []);

  const save = (patch: SettingsPatch) => run(async () => onSettings(await api.saveSettings(patch)));

  function load() {
    const picked = catalog.find((c) => c.url === choice);
    const name = choice === "custom" ? customName : picked?.name || "";
    const url = choice === "custom" ? customUrl : choice;
    if (
      region?.ready &&
      !window.confirm(
        `Switch the map to ${name || "the new region"}? The current map stays in use until the new one is ready.`,
      )
    )
      return;
    run(async () => {
      await api.loadRegion(name, url);
      reloadRegion();
    });
  }

  async function restore(file: File) {
    setNotice("");
    await run(async () => {
      let data;
      try {
        data = JSON.parse(await file.text());
      } catch {
        throw new Error("That file is not a Route Planner backup.");
      }
      const when = typeof data.exported_at === "string" ? ` from ${data.exported_at.replace("T", " ")}` : "";
      if (
        !window.confirm(
          `Load the backup${when}? This replaces every driver, address and setting, and clears the saved day plans.`,
        )
      )
        return;
      const res = await api.restore(data);
      setNotice(`Backup loaded: ${res.drivers} drivers and ${res.addresses} addresses.`);
      reloadAll();
    });
    if (fileInput.current) fileInput.current.value = "";
  }

  const backUpNow = () =>
    run(async () => {
      const saved = await api.backupSave();
      setNotice(`Saved ${saved.name}.`);
      loadAuto();
    });

  const pending = region?.pending;
  const working = pending && pending.status !== "error";
  return (
    <div className="page narrow">
      <h1>Settings</h1>
      <ErrorNote message={error} />
      {notice && <div className="note note-info">{notice}</div>}

      <section>
        <h2>Map region</h2>
        <p>
          Current region:{" "}
          {region?.ready ? (
            <>
              <b>{region.name}</b> <Badge kind="ok">Ready</Badge> <span className="muted">built {region.built_at}</span>
            </>
          ) : (
            <Badge kind="bad">None loaded</Badge>
          )}
        </p>
        {pending && (
          <div className={`note ${pending.status === "error" ? "note-error" : "note-info"}`}>
            <b>{pending.name}:</b>{" "}
            {pending.status === "error" ? `Failed. ${pending.message}` : pending.message || pending.status}
            {working && (
              <div className="progress">
                <div />
              </div>
            )}
          </div>
        )}
        <p className="muted">
          Pick the area your drivers cover. The app downloads the road data and prepares it, which takes a few minutes
          for a state and longer for bigger areas. Routes keep working on the current map until the new one is ready.
          Addresses outside the region cannot be routed.
        </p>
        <div className="row">
          <select value={choice} onChange={(e) => setChoice(e.target.value)}>
            <option value="">Choose a region…</option>
            {catalog.map((c) => (
              <option key={c.url} value={c.url}>
                {c.name}
              </option>
            ))}
            <option value="custom">Other: paste a link to a map file</option>
          </select>
          <button
            className="btn btn-primary"
            disabled={!!working || !choice || (choice === "custom" && !customUrl.trim())}
            onClick={load}
          >
            Load region
          </button>
        </div>
        {choice === "custom" && (
          <div className="form">
            <label>
              Name
              <input
                value={customName}
                onChange={(e) => setCustomName(e.target.value)}
                placeholder="Greater Springfield"
              />
            </label>
            <label>
              Link to an OpenStreetMap extract (.osm.pbf)
              <input
                value={customUrl}
                onChange={(e) => setCustomUrl(e.target.value)}
                placeholder="https://download.geofabrik.de/…-latest.osm.pbf"
              />
            </label>
          </div>
        )}
      </section>

      <section>
        <h2>Planning</h2>
        <div className="row">
          <span className="field-label">Distances in</span>
          <label className="check">
            <input type="radio" checked={settings.units === "mi"} onChange={() => save({ units: "mi" })} /> Miles
          </label>
          <label className="check">
            <input type="radio" checked={settings.units === "km"} onChange={() => save({ units: "km" })} /> Kilometers
          </label>
        </div>
        <div className="field-label">Sharing stops among staff drivers</div>
        <label className="check">
          <input
            type="radio"
            checked={settings.staff_balance === "stops"}
            onChange={() => save({ staff_balance: "stops" })}
          />
          Roughly the same number of stops each
        </label>
        <br />
        <label className="check">
          <input
            type="radio"
            checked={settings.staff_balance === "time"}
            onChange={() => save({ staff_balance: "time" })}
          />
          Roughly the same driving time each
        </label>
        <br />
        <label className="check">
          <input
            type="radio"
            checked={settings.staff_balance === "off"}
            onChange={() => save({ staff_balance: "off" })}
          />
          No sharing: lowest total only <span className="muted">(one driver usually gets nearly everything)</span>
        </label>

        <div className="field-label" style={{ marginTop: 14 }}>
          Estimated arrival times
        </div>
        <div className="row">
          <label className="check">
            Minutes allowed at each stop
            <input
              type="number"
              min={0}
              max={120}
              style={{ width: 80 }}
              value={minutes}
              onChange={(e) => setMinutes(e.target.value)}
              onBlur={() =>
                minutes !== "" &&
                Number(minutes) !== settings.minutes_per_stop &&
                save({ minutes_per_stop: Number(minutes) })
              }
            />
          </label>
          <label className="check">
            Usual start time
            <input
              type="time"
              value={settings.default_start_time}
              onChange={(e) => e.target.value && save({ default_start_time: e.target.value })}
            />
          </label>
        </div>
        <p className="muted">
          Arrival times are estimates: driving time plus the minutes at each stop before it. The start time can be
          changed for any single day. A volunteer's maximum route time still counts driving only.
        </p>
      </section>

      <section>
        <h2>Address lookup</h2>
        <p className="muted">
          Used only when a new address is checked. The free services need no key. A paid service is usually better with
          apartments, new buildings and rural addresses. If the chosen service finds nothing, the free ones are tried.
        </p>
        <label className="check">
          <input type="radio" checked={settings.geocoder === "census"} onChange={() => save({ geocoder: "census" })} />
          US Census geocoder <span className="muted">(free)</span>
        </label>
        <br />
        <label className="check">
          <input
            type="radio"
            checked={settings.geocoder === "nominatim"}
            onChange={() => save({ geocoder: "nominatim" })}
          />
          OpenStreetMap Nominatim <span className="muted">(free)</span>
        </label>
        {PAID.map((p) => {
          const has = settings[p.has];
          return (
            <div key={p.id} className="key-row">
              <label className="check">
                <input
                  type="radio"
                  checked={settings.geocoder === p.id}
                  disabled={!has}
                  onChange={() => save({ geocoder: p.id })}
                />
                {p.name} {has ? <Badge kind="ok">Key saved</Badge> : <span className="muted">(needs an API key)</span>}
              </label>
              <input
                type="password"
                autoComplete="off"
                placeholder={has ? "Paste a new key to replace it" : p.hint}
                value={keys[p.id] || ""}
                onChange={(e) => setKeys({ ...keys, [p.id]: e.target.value })}
              />
              <button
                className="btn btn-small"
                disabled={!(keys[p.id] || "").trim()}
                onClick={async () => {
                  await save({ [p.key]: keys[p.id].trim() });
                  setKeys({ ...keys, [p.id]: "" });
                }}
              >
                Save key
              </button>
              {has && (
                <button
                  className="btn btn-small btn-ghost"
                  onClick={() => save({ [p.key]: "", ...(settings.geocoder === p.id ? { geocoder: "census" } : {}) })}
                >
                  Remove
                </button>
              )}
            </div>
          );
        })}
        <p className="muted">
          A saved key is kept on the server and is never shown again. Anyone who can open this app can use it.
        </p>
      </section>

      <section>
        <h2>Backup</h2>
        <p className="muted">
          A backup file holds your drivers, every confirmed address with its usual volunteer and notes, and these
          settings (including any API keys). It does not hold the map or past day plans.
        </p>
        {auto?.enabled ? (
          <div className="note note-info">
            <b>Automatic backups are on.</b> A file is saved every day to the <code>backups</code> folder next to the
            app's files on this computer, and the last {auto.keep} days are kept.{" "}
            {auto.files.length ? (
              <>
                Latest: <b>{auto.files[0].name}</b> ({auto.files.length} file{auto.files.length === 1 ? "" : "s"}).
              </>
            ) : (
              "No file has been written yet."
            )}{" "}
            <button className="btn btn-small" onClick={backUpNow}>
              Back up now
            </button>
          </div>
        ) : (
          <div className="note note-warn">Automatic backups are off: no backup folder is connected to the app.</div>
        )}
        <div className="row">
          <a className="btn btn-primary" href={api.backupUrl}>
            Download backup
          </a>
          <button className="btn" onClick={() => fileInput.current?.click()}>
            Load a backup file…
          </button>
          <input
            ref={fileInput}
            type="file"
            accept="application/json,.json"
            style={{ display: "none" }}
            onChange={(e) => e.target.files?.[0] && restore(e.target.files[0])}
          />
        </div>
      </section>

      <section>
        <h2>Map background</h2>
        <div className="form">
          <label>
            Tile address
            <input value={tileUrl} onChange={(e) => setTileUrl(e.target.value)} />
          </label>
        </div>
        <button
          className="btn"
          disabled={tileUrl === settings.tile_url || !tileUrl.trim()}
          onClick={() => save({ tile_url: tileUrl })}
        >
          Save
        </button>
        <p className="muted">
          The default is OpenStreetMap's public tiles, which are fine for light internal use. If you have a key for a
          tile provider, paste its tile address here with the key in it.
        </p>
      </section>
    </div>
  );
}
