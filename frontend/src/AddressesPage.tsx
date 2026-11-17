import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { Address, Driver, ImportJob, PendingAddress, Settings } from "./types";
import { ErrorNote, LocationPicker, Modal, PickedLocation } from "./ui";
import { addressLine } from "./util";

const IMPORT_ROLES: Record<string, string> = {
  street: "Street address", unit: "Unit number", city: "City", state: "State", zip: "Zip",
  volunteer: "Usual volunteer (name)", notes: "Notes", extra: "Ignore",
};

function NoteCell({ value, onSave }: { value: string; onSave: (v: string) => void }) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  return (
    <input
      className="cell" style={{ width: "100%", minWidth: 160 }} value={text} placeholder="Add a note" maxLength={300}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => text.trim() !== value && onSave(text.trim())}
      onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
    />
  );
}

export default function AddressesPage({ drivers, settings, driverId, reloadDrivers }: {
  drivers: Driver[];
  settings: Settings;
  driverId: number | null;
  reloadDrivers: () => void;
}) {
  const [rows, setRows] = useState<Address[]>([]);
  const [waiting, setWaiting] = useState<PendingAddress[]>([]);
  const [q, setQ] = useState("");
  const [error, setError] = useState("");
  const [fixing, setFixing] = useState<{ title: string; address?: Address; pending?: PendingAddress } | null>(null);
  const [spot, setSpot] = useState<PickedLocation>({ label: "", lat: null, lon: null });
  const [importing, setImporting] = useState(false);
  const volunteers = drivers.filter((d) => d.kind === "volunteer");
  const byId = new Map(drivers.map((d) => [d.id, d]));
  const filterDriver = driverId ? byId.get(driverId) : undefined;

  const load = useCallback(() => {
    api.addresses(q, driverId ?? undefined).then(setRows).catch((e) => setError((e as Error).message));
    api.pending().then(setWaiting).catch(() => undefined);
  }, [q, driverId]);

  useEffect(() => {
    const t = setTimeout(load, 200);
    return () => clearTimeout(t);
  }, [load]);

  async function act(fn: () => Promise<unknown>) {
    setError("");
    try {
      await fn();
      load();
      reloadDrivers();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="page">
      <div className="row page-head">
        <h1>Addresses{filterDriver ? `: ${filterDriver.name}'s usual stops` : ""}</h1>
        <div className="row">
          {filterDriver && <a className="btn btn-ghost" href="#/addresses">Show all</a>}
          <button className="btn btn-primary" onClick={() => setImporting(true)}>Import a list…</button>
        </div>
      </div>
      <p className="muted">
        Every address you have confirmed on the map. A volunteer's usual stops go to them automatically when they appear on a day's list.
      </p>

      {waiting.length > 0 && !filterDriver && (
        <section>
          <h2>{waiting.length} imported address{waiting.length === 1 ? "" : "es"} still need a map check</h2>
          <p className="muted">
            The lookup was not sure about these. Check each on the map here, or leave them: they are asked about the first
            time they appear on a day's list, and keep their volunteer and notes either way.
          </p>
          <div className="table-wrap">
            <table className="grid">
              <thead><tr><th>Address</th><th>Usual volunteer</th><th>Why</th><th></th></tr></thead>
              <tbody>
                {waiting.map((w) => (
                  <tr key={w.key}>
                    <td>{addressLine(w)}</td>
                    <td>{w.usual_driver_id ? byId.get(w.usual_driver_id)?.name || "" : ""}</td>
                    <td className="muted">{w.reason}</td>
                    <td className="row-actions">
                      <button
                        className="btn btn-small"
                        onClick={() => { setFixing({ title: `Check location: ${addressLine(w)}`, pending: w }); setSpot({ label: addressLine({ ...w, unit: "" }), lat: null, lon: null }); }}
                      >Check on map</button>
                      <button
                        className="btn btn-small btn-ghost"
                        onClick={() => window.confirm(`Drop ${addressLine(w)} from the import?`) && act(() => api.discardPending(w.key))}
                      >Drop</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <div className="row">
        <input className="search" value={q} placeholder="Search street, city, zip or notes" onChange={(e) => setQ(e.target.value)} />
        <span className="muted">{rows.length} address{rows.length === 1 ? "" : "es"}</span>
      </div>
      {!fixing && <ErrorNote message={error} />}
      <div className="table-wrap">
        <table className="grid">
          <thead><tr><th>Street</th><th>Unit</th><th>City</th><th>Zip</th><th>Usual volunteer</th><th>Notes</th><th></th></tr></thead>
          <tbody>
            {rows.map((a) => {
              const owner = a.usual_driver_id ? byId.get(a.usual_driver_id) : undefined;
              const locked = !!owner?.locked;
              return (
                <tr key={a.id}>
                  <td>{a.street}</td><td>{a.unit}</td><td>{a.city}{a.state ? `, ${a.state}` : ""}</td><td>{a.zip}</td>
                  <td>
                    <select
                      value={a.usual_driver_id ?? ""} disabled={locked}
                      title={locked ? `${owner?.name} is locked. Turn the lock off to change this.` : ""}
                      onChange={(e) => act(() => api.setUsual(a.id, e.target.value ? Number(e.target.value) : null))}
                    >
                      <option value="">None</option>
                      {volunteers.map((d) => (
                        <option key={d.id} value={d.id} disabled={d.locked && d.id !== a.usual_driver_id}>
                          {d.name}{d.locked ? " (locked)" : ""}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td><NoteCell value={a.notes} onSave={(v) => act(() => api.setNotes(a.id, v))} /></td>
                  <td className="row-actions">
                    <button
                      className="btn btn-small"
                      onClick={() => { setFixing({ title: `Fix location: ${addressLine(a)}`, address: a }); setSpot({ label: addressLine(a), lat: a.lat, lon: a.lon }); }}
                    >Fix location</button>
                    <button
                      className="btn btn-small btn-ghost" disabled={locked}
                      onClick={() => window.confirm(`Forget ${addressLine(a)}? It will count as a new address next time.`) && act(() => api.deleteAddress(a.id))}
                    >Forget</button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {fixing && (
        <Modal title={fixing.title} onClose={() => setFixing(null)} wide>
          {fixing.pending && <p className="muted">Press Find to look the address up, then adjust the pin if needed.</p>}
          <LocationPicker tileUrl={settings.tile_url} value={spot} onChange={setSpot} />
          <ErrorNote message={error} />
          <div className="row">
            <button
              className="btn btn-primary" disabled={spot.lat === null}
              onClick={() => act(async () => {
                if (fixing.address) await api.moveAddress(fixing.address.id, spot.lat as number, spot.lon as number);
                if (fixing.pending) await api.confirmPending(fixing.pending.key, spot.lat as number, spot.lon as number);
                setFixing(null);
              })}
            >{fixing.pending ? "Confirm location" : "Save location"}</button>
            <button className="btn btn-ghost" onClick={() => setFixing(null)}>Cancel</button>
          </div>
        </Modal>
      )}

      {importing && <ImportDialog onClose={() => { setImporting(false); load(); reloadDrivers(); }} />}
    </div>
  );
}

/** Load an existing address list in one go, with each address's usual volunteer and notes. */
function ImportDialog({ onClose }: { onClose: () => void }) {
  const [text, setText] = useState("");
  const [preview, setPreview] = useState<{ layout: string[]; sample: string[][]; rows: number } | null>(null);
  const [layout, setLayout] = useState<string[]>([]);
  const [autoSave, setAutoSave] = useState(true);
  const [job, setJob] = useState<ImportJob | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (job?.status !== "running") return;
    const t = setInterval(() => api.importStatus().then(setJob).catch(() => undefined), 800);
    return () => clearInterval(t);
  }, [job?.status]);

  async function read() {
    setError("");
    try {
      const p = await api.importPreview(text);
      setPreview(p);
      setLayout(p.layout);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function start() {
    setError("");
    try {
      setJob(await api.importStart(text, layout, autoSave));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <Modal title="Import an address list" onClose={onClose} wide>
      {!job && (
        <>
          <p className="muted">
            Paste rows from Excel: street address, unit number, city, state, zip. Add a column with the volunteer's name to set usual
            stops, and a column of notes if you have them. No header row. Add your volunteers on the Drivers page first so their names match.
          </p>
          <textarea rows={7} value={text} spellCheck={false} onChange={(e) => { setText(e.target.value); setPreview(null); }} />
          {!preview && (
            <div className="row">
              <button className="btn btn-primary" disabled={!text.trim()} onClick={read}>Read rows</button>
            </div>
          )}
          {preview && (
            <>
              <div className="field-label">{preview.rows} rows. Check that each column is labeled correctly:</div>
              <div className="table-wrap">
                <table className="grid">
                  <thead>
                    <tr>
                      {layout.map((role, i) => (
                        <th key={i}>
                          <select value={role} onChange={(e) => setLayout(layout.map((r, j) => (j === i ? e.target.value : r)))}>
                            {Object.entries(IMPORT_ROLES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                          </select>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {preview.sample.map((cells, r) => (
                      <tr key={r}>{layout.map((_, i) => <td key={i}>{cells[i] || ""}</td>)}</tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <label className="check" style={{ marginTop: 10 }}>
                <input type="checkbox" checked={autoSave} onChange={(e) => setAutoSave(e.target.checked)} />
                Save addresses the lookup is confident about without a map check
              </label>
              <p className="muted">
                {autoSave
                  ? "Addresses the lookup is unsure about are set aside for you to check on the map."
                  : "Every address is set aside for a map check. Their volunteers and notes are kept."}
              </p>
              <div className="row">
                <button className="btn btn-primary" onClick={start}>Import {preview.rows} rows</button>
                <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
              </div>
            </>
          )}
        </>
      )}
      {job && (
        <div>
          {job.status === "running" && (
            <>
              <p>Working: {job.done} of {job.total} rows…</p>
              <div className="progress"><div /></div>
            </>
          )}
          {job.status === "error" && <div className="note note-error">{job.message}</div>}
          {job.status !== "running" && (
            <>
              <p>
                <b>{job.saved}</b> saved · <b>{job.updated}</b> already known and updated · <b>{job.pending}</b> set aside for a map check
              </p>
              {(job.problems || []).length > 0 && (
                <div className="note note-warn">
                  <b>{job.problems?.length} row(s) need a look:</b>
                  <ul>{job.problems?.map((m, i) => <li key={i}>{m}</li>)}</ul>
                </div>
              )}
              <button className="btn btn-primary" onClick={onClose}>Done</button>
            </>
          )}
        </div>
      )}
      <ErrorNote message={error} />
    </Modal>
  );
}
