import { useState } from "react";
import { api } from "./api";
import type { Driver, Settings } from "./types";
import { Badge, ErrorNote, LocationPicker, Modal } from "./ui";
import { useAction } from "./useAction";

const COLORS = ["#2563eb", "#dc2626", "#059669", "#d97706", "#7c3aed", "#0891b2", "#db2777", "#4d7c0f", "#b45309", "#475569"];

type Draft = Omit<Driver, "id" | "usual_stops"> & { id?: number; zipText: string; sameEnd: boolean };

function blank(count: number): Draft {
  return {
    name: "", kind: "staff", color: COLORS[count % COLORS.length],
    start_label: "", start_lat: null, start_lon: null, end_label: "", end_lat: null, end_lon: null,
    avoid_highways: false, start_time: "", max_stops: null, max_route_minutes: null,
    zip_codes: [], locked: false, zipText: "", sameEnd: true,
  };
}

function toDraft(d: Driver): Draft {
  const sameEnd = d.start_lat === d.end_lat && d.start_lon === d.end_lon;
  return { ...d, zipText: d.zip_codes.join(", "), sameEnd };
}

export default function DriversPage({ drivers, settings, reload }: { drivers: Driver[]; settings: Settings; reload: () => void }) {
  const [draft, setDraft] = useState<Draft | null>(null);
  const { busy, error, setError, run } = useAction();

  function save() {
    if (!draft) return;
    const body = {
      ...draft,
      zip_codes: draft.zipText.split(/[\s,;]+/).filter(Boolean),
      end_label: draft.sameEnd ? draft.start_label : draft.end_label,
      end_lat: draft.sameEnd ? draft.start_lat : draft.end_lat,
      end_lon: draft.sameEnd ? draft.start_lon : draft.end_lon,
    };
    run(async () => {
      if (draft.id) await api.updateDriver(draft.id, body);
      else await api.createDriver(body);
      setDraft(null);
      reload();
    });
  }

  function remove(d: Driver) {
    const extra = d.usual_stops ? ` Their ${d.usual_stops} usual stop(s) will no longer have a usual driver.` : "";
    if (!window.confirm(`Remove ${d.name}?${extra}`)) return;
    run(async () => {
      await api.deleteDriver(d.id);
      reload();
    });
  }

  const volunteer = draft?.kind === "volunteer";
  return (
    <div className="page">
      <div className="row page-head">
        <h1>Drivers</h1>
        <button className="btn btn-primary" onClick={() => { setError(""); setDraft(blank(drivers.length)); }}>Add driver</button>
      </div>
      {!draft && <ErrorNote message={error} />}
      {drivers.length === 0 && <p className="muted">No drivers yet. Add your staff and volunteer drivers here.</p>}
      <div className="table-wrap">
        <table className="grid">
          <thead>
            <tr><th>Driver</th><th>Type</th><th>Start</th><th>Limits</th><th>Usual stops</th><th>Options</th><th></th></tr>
          </thead>
          <tbody>
            {drivers.map((d) => (
              <tr key={d.id}>
                <td><span className="dot" style={{ background: d.color }} /> <b>{d.name}</b></td>
                <td><Badge kind={d.kind === "volunteer" ? "vol" : "staff"}>{d.kind === "volunteer" ? "Volunteer" : "Staff"}</Badge></td>
                <td>{d.start_lat === null ? <Badge kind="bad">Not set</Badge> : d.start_label || "Set on map"}</td>
                <td>
                  {d.kind === "staff" ? <span className="muted">None</span> : (
                    [
                      d.max_stops ? `${d.max_stops} stops` : "",
                      d.max_route_minutes ? `${d.max_route_minutes} min driving` : "",
                      d.zip_codes.length ? `zips ${d.zip_codes.join(", ")}` : "",
                    ].filter(Boolean).join(" · ") || <span className="muted">None set</span>
                  )}
                </td>
                <td>{d.kind === "volunteer" ? <a href={`#/addresses/${d.id}`}>{d.usual_stops}</a> : <span className="muted">n/a</span>}</td>
                <td>
                  {d.locked && <Badge kind="lock">🔒 Locked</Badge>}
                  {d.avoid_highways && <Badge kind="plain">Avoids highways</Badge>}
                  {d.start_time && <Badge kind="plain">Starts {d.start_time}</Badge>}
                </td>
                <td className="row-actions">
                  <button className="btn btn-small" onClick={() => { setError(""); setDraft(toDraft(d)); }}>Edit</button>
                  <button
                    className="btn btn-small" title="Start a new driver with the same settings"
                    onClick={() => { setError(""); setDraft({ ...toDraft(d), id: undefined, name: `Copy of ${d.name}`, color: COLORS[drivers.length % COLORS.length], locked: false }); }}
                  >Duplicate</button>
                  <button className="btn btn-small btn-ghost" onClick={() => remove(d)}>Remove</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {draft && (
        <Modal title={draft.id ? `Edit ${draft.name}` : "Add driver"} onClose={() => setDraft(null)} wide>
          <div className="form">
            <label>Name
              <input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} autoFocus />
            </label>
            <div className="row">
              <label className="check">
                <input type="radio" checked={draft.kind === "staff"} onChange={() => setDraft({ ...draft, kind: "staff" })} />
                Staff <span className="muted">(no limits, no usual stops)</span>
              </label>
              <label className="check">
                <input type="radio" checked={draft.kind === "volunteer"} onChange={() => setDraft({ ...draft, kind: "volunteer" })} />
                Volunteer <span className="muted">(usual stops, optional limits)</span>
              </label>
            </div>
            <div className="row">
              <span className="field-label">Map color</span>
              {COLORS.map((c) => (
                <button
                  key={c} type="button" className={`swatch${draft.color === c ? " swatch-on" : ""}`}
                  style={{ background: c }} onClick={() => setDraft({ ...draft, color: c })} aria-label={`Color ${c}`}
                />
              ))}
            </div>
            <div className="row">
              <label className="check">
                <input type="checkbox" checked={draft.avoid_highways} onChange={(e) => setDraft({ ...draft, avoid_highways: e.target.checked })} />
                Avoid highways
              </label>
              <label className="check">Own start time <span className="muted">(optional)</span>
                <input type="time" value={draft.start_time} onChange={(e) => setDraft({ ...draft, start_time: e.target.value })} />
              </label>
              {draft.start_time && (
                <button type="button" className="btn-link" onClick={() => setDraft({ ...draft, start_time: "" })}>Use the day's start time</button>
              )}
            </div>

            {volunteer && (
              <fieldset>
                <legend>Volunteer limits (leave blank for no limit)</legend>
                <div className="row">
                  <label>Maximum stops
                    <input
                      type="number" min={1} value={draft.max_stops ?? ""}
                      onChange={(e) => setDraft({ ...draft, max_stops: e.target.value ? Number(e.target.value) : null })}
                    />
                  </label>
                  <label>Maximum route time (minutes of driving)
                    <input
                      type="number" min={1} value={draft.max_route_minutes ?? ""}
                      onChange={(e) => setDraft({ ...draft, max_route_minutes: e.target.value ? Number(e.target.value) : null })}
                    />
                  </label>
                </div>
                <label>Assigned zip codes (separate with commas)
                  <input value={draft.zipText} placeholder="62701, 62702" onChange={(e) => setDraft({ ...draft, zipText: e.target.value })} />
                </label>
                <label className="check">
                  <input type="checkbox" checked={draft.locked} onChange={(e) => setDraft({ ...draft, locked: e.target.checked })} />
                  Lock addresses <span className="muted">(nothing can be added to or removed from their usual stops)</span>
                </label>
              </fieldset>
            )}

            <div className="field-label">Start location</div>
            <LocationPicker
              tileUrl={settings.tile_url}
              value={{ label: draft.start_label, lat: draft.start_lat, lon: draft.start_lon }}
              onChange={(v) => setDraft({ ...draft, start_label: v.label, start_lat: v.lat, start_lon: v.lon })}
            />
            <label className="check">
              <input type="checkbox" checked={draft.sameEnd} onChange={(e) => setDraft({ ...draft, sameEnd: e.target.checked })} />
              Ends the day at the same place
            </label>
            {!draft.sameEnd && (
              <>
                <div className="field-label">End location</div>
                <LocationPicker
                  tileUrl={settings.tile_url}
                  value={{ label: draft.end_label, lat: draft.end_lat, lon: draft.end_lon }}
                  onChange={(v) => setDraft({ ...draft, end_label: v.label, end_lat: v.lat, end_lon: v.lon })}
                />
              </>
            )}
            <ErrorNote message={error} />
            <div className="row">
              <button className="btn btn-primary" disabled={busy || !draft.name.trim()} onClick={save}>Save driver</button>
              <button className="btn btn-ghost" onClick={() => setDraft(null)}>Cancel</button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
