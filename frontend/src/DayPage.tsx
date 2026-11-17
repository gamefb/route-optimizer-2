import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import ReviewTable from "./ReviewTable";
import Routes from "./Routes";
import type { Driver, Plan, RegionInfo, Settings, Stop } from "./types";
import { Badge, ErrorNote, Fold } from "./ui";
import { clock, longDate, shiftDay, today } from "./util";
import ValidateDialog from "./ValidateDialog";

const ROLE_NAMES: Record<string, string> = {
  street: "Street address", unit: "Unit number", city: "City", state: "State", zip: "Zip", extra: "Other (keep as is)",
};

interface Props {
  day: string;
  setDay: (d: string) => void;
  settings: Settings;
  drivers: Driver[];
  region: RegionInfo | null;
  reloadDrivers: () => void;
}

export default function DayPage({ day, setDay, settings, drivers, region, reloadDrivers }: Props) {
  const [plan, setPlan] = useState<Plan | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [text, setText] = useState("");
  const [showPaste, setShowPaste] = useState(false);
  const [validating, setValidating] = useState<number | null>(null);
  const [skipped, setSkipped] = useState<number[]>([]);

  useEffect(() => {
    setPlan(null);
    setError("");
    setValidating(null);
    api.planForDay(day).then(setPlan).catch((e) => setError((e as Error).message));
  }, [day]);

  const run = useCallback(async (fn: () => Promise<Plan>): Promise<Plan | null> => {
    setBusy(true);
    setError("");
    try {
      const next = await fn();
      setPlan(next);
      return next;
    } catch (e) {
      setError((e as Error).message);
      return null;
    } finally {
      setBusy(false);
    }
  }, []);

  const dayHead = (
    <div className="day-head">
      <button className="btn" onClick={() => setDay(shiftDay(day, -1))} aria-label="Previous day">‹</button>
      <DayInput day={day} setDay={setDay} />
      <button className="btn" onClick={() => setDay(shiftDay(day, 1))} aria-label="Next day">›</button>
      <button className="btn" disabled={day === today()} onClick={() => setDay(today())}>Today</button>
      <h1>{longDate(day)}</h1>
    </div>
  );
  // The date controls stay on screen while a day loads, so the calendar is never pulled away mid-use.
  if (!plan) return <div className="page">{dayHead}<ErrorNote message={error} />{!error && <div className="muted">Loading…</div>}</div>;

  const p = plan;
  const needs = p.stops.filter((s) => s.match_state !== "matched");
  const newOnes = p.stops.filter((s) => s.match_state === "new");
  const current = validating !== null ? p.stops.find((s) => s.id === validating && s.match_state !== "matched") : undefined;
  const workingIds = new Set(p.working_driver_ids);
  const working = drivers.filter((d) => workingIds.has(d.id));
  const volunteersOff = drivers.filter((d) => d.kind === "volunteer" && !workingIds.has(d.id) && d.usual_stops > 0);

  function nextToValidate(after: Plan, skip: number[]): number | null {
    const next = after.stops.find((s) => s.match_state === "new" && !skip.includes(s.id));
    return next ? next.id : null;
  }

  async function doPaste(mode: "replace" | "append") {
    if (mode === "replace" && p.stops.length && !window.confirm("Replace the rows already entered for this day?")) return;
    const next = await run(() => api.paste(p.id, text, mode));
    if (next) {
      setText("");
      setShowPaste(false);
      setSkipped([]);
    }
  }

  async function toggleWorking(d: Driver) {
    const ids = workingIds.has(d.id) ? p.working_driver_ids.filter((i) => i !== d.id) : [...p.working_driver_ids, d.id];
    await run(() => api.updatePlan(p.id, { working_driver_ids: ids }));
  }

  const mapMissing = region !== null && !region.ready;
  const layout = p.layout.length ? p.layout : ["street", "unit", "city", "state", "zip"];
  const sample = (p as Plan & { sample?: string[] }).sample || [];

  return (
    <div className="page">
      {dayHead}

      {mapMissing && (
        <div className="note note-warn">
          No map region is loaded yet{region?.pending ? ` (${region.pending.message || region.pending.status})` : ""}.
          Routes cannot be built until one is ready. <a href="#/settings">Open Settings</a>
        </div>
      )}
      <ErrorNote message={error} />

      <Fold id="paste" step={1} title="Paste today's addresses" summary={p.stops.length ? `${p.stops.length} rows entered` : ""} done={p.stops.length > 0 && !showPaste}>
        <Fold id="layout" plain startOpen={false} title="Columns in your paste" summary={layout.map((r) => ROLE_NAMES[r] || r).join(" · ")}>
          <div className="layout-bar">
            {layout.map((role, i) => (
              <label key={i} className="layout-col">
                <span className="layout-sample" title={sample[i] || ""}>{sample[i] || `Column ${i + 1}`}</span>
                <select value={role} disabled={busy} onChange={(e) => run(() => api.setLayout(p.id, layout.map((r, j) => (j === i ? e.target.value : r))))}>
                  {Object.entries(ROLE_NAMES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
              </label>
            ))}
            <button className="btn btn-small" disabled={busy} title="Add a column" onClick={() => run(() => api.setLayout(p.id, [...layout, "extra"]))}>+ Column</button>
            {layout.length > 1 && (
              <button className="btn btn-small btn-ghost" disabled={busy} title="Remove the last column" onClick={() => run(() => api.setLayout(p.id, layout.slice(0, -1)))}>− Column</button>
            )}
          </div>
          <div className="hint">Set this before pasting if your sheet is laid out differently. It is remembered for next time.</div>
        </Fold>
        {p.stops.length === 0 || showPaste ? (
          <div>
            <p className="muted">
              Select the rows in Excel, copy, and paste here. One address per row: street address, unit number, city, state, zip. No header row.
            </p>
            <textarea
              rows={8} value={text} onChange={(e) => setText(e.target.value)} spellCheck={false}
              placeholder={"123 Main St\tApt 4\tSpringfield\tIL\t62701\n45 Oak Ave\t\tSpringfield\tIL\t62702"}
            />
            <div className="row">
              <button className="btn btn-primary" disabled={busy || !text.trim()} onClick={() => doPaste("replace")}>
                {p.stops.length ? "Replace the list" : "Read rows"}
              </button>
              {p.stops.length > 0 && (
                <>
                  <button className="btn" disabled={busy || !text.trim()} onClick={() => doPaste("append")}>Add to the list</button>
                  <button className="btn btn-ghost" onClick={() => setShowPaste(false)}>Cancel</button>
                </>
              )}
            </div>
          </div>
        ) : (
          <div className="row">
            <span><b>{p.stops.length}</b> rows entered.</span>
            <button className="btn" onClick={() => setShowPaste(true)}>Paste again</button>
          </div>
        )}
      </Fold>

      {p.stops.length > 0 && (
        <Fold
          id="review" step={2} title="Review the table" done={needs.length === 0}
          summary={needs.length ? `${needs.length} need attention` : `${p.stops.length} matched`}
        >
          <div className="row summary-row">
            <Badge kind="ok">{p.stops.length - needs.length} matched</Badge>
            {needs.length > 0 && <Badge kind="warn">{needs.length} need attention</Badge>}
            {newOnes.length > 0 && (
              <button
                className="btn btn-primary" disabled={busy}
                onClick={() => { setSkipped([]); setValidating(newOnes[0].id); }}
              >Check {newOnes.length} new address{newOnes.length === 1 ? "" : "es"} on the map</button>
            )}
            <span className="spacer" />
            <button
              className="btn btn-ghost" disabled={busy}
              onClick={() => window.confirm("Remove every row for this day?") && run(() => api.clearStops(p.id))}
            >Clear the list</button>
          </div>
          <ReviewTable
            plan={p} drivers={drivers} busy={busy}
            onEdit={(s, fields) => run(() => api.editStop(s.id, fields))}
            onDelete={(s) => run(() => api.deleteStop(s.id))}
            onShift={(s, dir) => run(() => api.shiftStop(s.id, dir))}
            onConfirmMatch={(s, addressId) => run(() => api.confirmMatch(s.id, addressId))}
            onMarkNew={(s) => run(() => api.markNew(s.id))}
            onValidate={(s) => { setSkipped([]); setValidating(s.id); }}
            onAdd={(fields) => run(() => api.addStop(p.id, fields))}
          />
        </Fold>
      )}

      {p.stops.length > 0 && (
        <Fold
          id="drivers" step={3} title="Drivers and options"
          summary={`${working.length} driver${working.length === 1 ? "" : "s"} · ${p.objective === "distance" ? "least miles" : "fastest time"} · leave ${p.start_time}`}
        >
          {drivers.length === 0 && (
            <div className="note note-warn">No drivers yet. <a href="#/drivers">Add drivers</a> first.</div>
          )}
          <p className="muted">Tick the staff and volunteers who should be given stops on this day.</p>
          {(["staff", "volunteer"] as const).map((kind) => {
            const group = drivers.filter((d) => d.kind === kind);
            if (!group.length) return null;
            const ids = group.map((d) => d.id);
            const others = p.working_driver_ids.filter((i) => !ids.includes(i));
            return (
              <div key={kind}>
                <div className="row pick-head">
                  <span className="field-label">{kind === "staff" ? "Staff" : "Volunteers"} ({group.filter((d) => workingIds.has(d.id)).length} of {group.length})</span>
                  <button className="btn-link" disabled={busy} onClick={() => run(() => api.updatePlan(p.id, { working_driver_ids: [...others, ...ids] }))}>All</button>
                  <button className="btn-link" disabled={busy} onClick={() => run(() => api.updatePlan(p.id, { working_driver_ids: others }))}>None</button>
                </div>
          <div className="driver-picks">
            {group.map((d) => {
              const on = workingIds.has(d.id);
              const noBase = d.start_lat === null || d.end_lat === null;
              return (
                <div key={d.id} className={`driver-pick${on ? " driver-pick-on" : ""}`}>
                  <label className="check">
                    <input type="checkbox" checked={on} disabled={busy} onChange={() => toggleWorking(d)} />
                    <span className="dot" style={{ background: d.color }} />
                    <b>{d.name}</b>
                  </label>
                  <Badge kind={d.kind === "volunteer" ? "vol" : "staff"}>{d.kind === "volunteer" ? "Volunteer" : "Staff"}</Badge>
                  {d.locked && <Badge kind="lock">🔒 Locked</Badge>}
                  {noBase && <Badge kind="bad">No start/end location</Badge>}
                  <div className="pick-detail">
                    {d.start_time ? <span>Starts <b>{clock(d.start_time)}</b></span> : <span className="muted">Starts at the day's time</span>}
                    {d.kind === "volunteer" && (
                      <span>
                        {[
                          d.max_stops ? `max ${d.max_stops} stops` : "",
                          d.max_route_minutes ? `max ${d.max_route_minutes} min driving` : "",
                          d.zip_codes.length ? `zips ${d.zip_codes.join(", ")}` : "",
                        ].filter(Boolean).join(" · ") || (d.locked ? "no limits set" : "no limits: shares stops evenly, like staff")}
                        {d.usual_stops > 0 ? ` · ${d.usual_stops} usual stop${d.usual_stops === 1 ? "" : "s"}` : ""}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
              </div>
            );
          })}
          {volunteersOff.length > 0 && (
            <div className="note note-info">
              {volunteersOff.map((d) => d.name).join(", ")} {volunteersOff.length === 1 ? "is" : "are"} off today.
              Their usual stops on today's list are covered by other drivers for the day and stay theirs.
            </div>
          )}
          <div className="row options">
            <span className="field-label">Optimize for</span>
            <label className="check">
              <input type="radio" checked={p.objective === "time"} disabled={busy} onChange={() => run(() => api.updatePlan(p.id, { objective: "time" }))} />
              Fastest time
            </label>
            <label className="check">
              <input type="radio" checked={p.objective === "distance"} disabled={busy} onChange={() => run(() => api.updatePlan(p.id, { objective: "distance" }))} />
              Least miles
            </label>
            <span className="field-label" style={{ marginLeft: 18 }} title="Used for every driver who has no start time of their own">Drivers leave at</span>
            <input
              type="time" value={p.start_time} disabled={busy}
              onChange={(e) => e.target.value && run(() => api.updatePlan(p.id, { start_time: e.target.value }))}
            />
          </div>
          <div className="row">
            <button
              className="btn btn-primary btn-big" disabled={busy || needs.length > 0 || working.length === 0}
              onClick={() => run(() => api.compute(p.id))}
            >{busy ? "Working…" : p.result ? "Rebuild routes" : "Build routes"}</button>
            {needs.length > 0 && <span className="muted">{needs.length} row(s) in the table still need attention.</span>}
            {needs.length === 0 && working.length === 0 && <span className="muted">Tick at least one driver.</span>}
          </div>
        </Fold>
      )}

      {p.result && p.stops.length > 0 && (
        <Fold id="routes" step={4} title="Routes" summary={`${p.result.totals.stops} stops on ${p.result.routes.filter((r) => r.stops > 0).length} routes`}>
          {p.stale && (
            <div className="note note-warn">
              Something changed since these routes were built.{" "}
              <button className="btn btn-small" disabled={busy || needs.length > 0} onClick={() => run(() => api.compute(p.id))}>Rebuild routes</button>
            </div>
          )}
          {p.undo_label && (
            <div className="note note-info">
              You can undo {p.undo_label}.{" "}
              <button
                className="btn btn-small" disabled={busy}
                onClick={async () => { await run(() => api.undo(p.id)); reloadDrivers(); }}
              >Undo</button>
            </div>
          )}
          <Routes
            plan={p} drivers={drivers} settings={settings} busy={busy}
            onReorder={(s: Stop, direction) => run(() => api.reorderStop(s.id, direction))}
            onResetOrder={(driverId) => run(() => api.resetOrder(p.id, driverId))}
            onSetOrder={(driverId, ids) => run(() => api.setOrder(p.id, driverId, ids))}
            onNotes={async (s: Stop, notes) => { if (s.address_id) { await api.setNotes(s.address_id, notes); await run(() => api.planForDay(day)); } }}
            onMove={(s: Stop, driverId) => run(() => api.moveStop(s.id, driverId))}
            onMakeUsual={async (s) => { await run(() => api.makeUsual(s.id)); reloadDrivers(); }}
            onMakeAllUsual={async (driverId) => { await run(() => api.makeAllUsual(p.id, driverId)); reloadDrivers(); }}
          />
        </Fold>
      )}

      {current && (
        <ValidateDialog
          stop={current} tileUrl={settings.tile_url}
          remaining={p.stops.filter((s) => s.match_state === "new").length}
          onClose={() => setValidating(null)}
          onSkip={() => {
            const skip = [...skipped, current.id];
            setSkipped(skip);
            setValidating(nextToValidate(p, skip));
          }}
          onConfirm={async (lat, lon) => {
            const next = await api.confirmLocation(current.id, lat, lon);
            setPlan(next);
            setValidating(nextToValidate(next, skipped));
          }}
          onUseKnown={async (addressId) => {
            const next = await api.confirmMatch(current.id, addressId);
            setPlan(next);
            setValidating(nextToValidate(next, skipped));
          }}
        />
      )}

    </div>
  );
}

/** Date box that waits until a full, sensible date is chosen before switching days. */
function DayInput({ day, setDay }: { day: string; setDay: (d: string) => void }) {
  const [draft, setDraft] = useState(day);
  useEffect(() => setDraft(day), [day]);
  const ok = (v: string) => /^\d{4}-\d{2}-\d{2}$/.test(v) && v >= "2000-01-01" && v <= "2100-12-31";
  useEffect(() => {
    if (draft === day || !ok(draft)) return;
    const t = setTimeout(() => setDay(draft), 700); // lets typing or stepping through dates settle first
    return () => clearTimeout(t);
  }, [draft, day, setDay]);
  return (
    <input
      type="date" value={draft} min="2000-01-01" max="2100-12-31"
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => (ok(draft) ? draft !== day && setDay(draft) : setDraft(day))}
      onKeyDown={(e) => e.key === "Enter" && ok(draft) && draft !== day && setDay(draft)}
    />
  );
}
