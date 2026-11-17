import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import MapView, { MapLine, MapMarker } from "./MapView";
import type { Driver, Plan, RouteResult, Settings, Stop } from "./types";
import { Badge } from "./ui";
import { addressLine, clock, decodeShape, formatDistance, formatDuration } from "./util";

interface Props {
  plan: Plan;
  drivers: Driver[];
  settings: Settings;
  busy: boolean;
  onMove: (stop: Stop, driverId: number | null) => void;
  onMakeUsual: (stop: Stop) => void;
  onMakeAllUsual: (driverId: number) => void;
  onReorder: (stop: Stop, direction: number) => void;
  onResetOrder: (driverId: number) => void;
  onSetOrder: (driverId: number, stopIds: number[]) => void;
  onNotes: (stop: Stop, notes: string) => void;
}

function NoteLine({ value, disabled, onSave }: { value: string; disabled: boolean; onSave: (v: string) => void }) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  return (
    <input
      className={`note-input${text ? " note-filled" : ""}`} value={text} disabled={disabled}
      placeholder="Add a note for this address" maxLength={300}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => text.trim() !== value && onSave(text.trim())}
      onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
    />
  );
}

export function usageText(r: RouteResult): string {
  if (!r.limits) return "";
  const parts = [];
  if (r.limits.max_stops) parts.push(`${r.stops} of ${r.limits.max_stops} stops`);
  if (r.limits.max_route_minutes) parts.push(`${formatDuration(r.time_s)} of ${formatDuration(r.limits.max_route_minutes * 60)} driving`);
  if (r.limits.zip_codes.length) parts.push(`zips ${r.limits.zip_codes.join(", ")}`);
  return parts.join(" · ");
}

export default function Routes({ plan, drivers, settings, busy, onMove, onMakeUsual, onMakeAllUsual, onReorder, onResetOrder, onSetOrder, onNotes }: Props) {
  const result = plan.result!;
  const [focus, setFocus] = useState<number | null>(null);
  const [picked, setPicked] = useState<{ id: number; from: "list" | "map"; n: number } | null>(null);
  const mapBox = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<{ driver: number; id: number } | null>(null);

  // Clicking a pin scrolls to its stop in the list; clicking a stop brings the map to its pin.
  useEffect(() => {
    if (!picked) return;
    if (picked.from === "map") document.getElementById(`stop-${picked.id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    else mapBox.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [picked]);
  const [over, setOver] = useState<number | null>(null);

  function drop(r: RouteResult, targetId: number) {
    if (drag && drag.driver === r.driver_id && drag.id !== targetId) {
      const ids = r.stop_ids.filter((i) => i !== drag.id);
      const at = ids.indexOf(targetId);
      const movingDown = r.stop_ids.indexOf(drag.id) < r.stop_ids.indexOf(targetId);
      ids.splice(movingDown ? at + 1 : at, 0, drag.id);
      onSetOrder(r.driver_id, ids);
    }
    setDrag(null);
    setOver(null);
  }
  const names = useMemo(() => new Map(drivers.map((d) => [d.id, d.name])), [drivers]);
  const stopsById = useMemo(() => new Map(plan.stops.map((s) => [s.id, s])), [plan.stops]);
  const working = drivers.filter((d) => plan.working_driver_ids.includes(d.id));

  const { markers, lines } = useMemo(() => {
    const markers: MapMarker[] = [];
    const lines: MapLine[] = [];
    for (const r of result.routes) {
      if (focus !== null && focus !== r.driver_id) continue;
      if (!r.stops) continue;
      for (const shape of r.shapes) lines.push({ points: decodeShape(shape), color: r.color });
      if (!r.shapes.length) {
        const pts = r.stop_ids.map((id) => stopsById.get(id)).filter((s): s is Stop => !!s && s.lat !== null);
        lines.push({ points: [r.start, ...pts.map((s) => [s.lat, s.lon] as [number, number]), r.end], color: r.color });
      }
      markers.push({ lat: r.start[0], lon: r.start[1], color: r.color, shape: "square", text: "S", title: `${r.name}: start` });
      if (r.end[0] !== r.start[0] || r.end[1] !== r.start[1]) {
        markers.push({ lat: r.end[0], lon: r.end[1], color: r.color, shape: "square", text: "E", title: `${r.name}: end` });
      }
      // Several units in one building share a pin labeled with their range.
      const groups = new Map<string, Stop[]>();
      for (const id of r.stop_ids) {
        const s = stopsById.get(id);
        if (!s || s.lat === null || s.lon === null) continue;
        const key = `${s.lat},${s.lon}`;
        groups.set(key, [...(groups.get(key) || []), s]);
      }
      for (const group of groups.values()) {
        const nums = group.map((s) => s.stop_number || 0).sort((a, b) => a - b);
        const text = nums.length > 1 ? `${nums[0]}-${nums[nums.length - 1]}` : String(nums[0]);
        markers.push({
          highlight: !!picked && group.some((s) => s.id === picked.id),
          onClick: () => setPicked({ id: group[0].id, from: "map", n: Date.now() }),
          lat: group[0].lat as number, lon: group[0].lon as number, color: r.color, text,
          title: `${r.name} #${text}: ${group.map((s) => [s.street, s.unit].filter(Boolean).join(" ")).join("; ")}`,
        });
      }
    }
    return { markers, lines };
  }, [result, focus, stopsById, picked]);
  const pickedStop = picked ? stopsById.get(picked.id) : undefined;

  function chip(s: Stop) {
    const who = s.covering_for_id ? names.get(s.covering_for_id) || "a volunteer" : "";
    switch (s.label) {
      case "usual": return <Badge kind="ok">Usual</Badge>;
      case "added": return <Badge kind="info">Added today</Badge>;
      case "covering": return <Badge kind="warn">Covering for {who}</Badge>;
      case "overflow": return <Badge kind="bad">Over {who}'s limit</Badge>;
      case "manual": return <Badge kind="info">Moved here by you</Badge>;
      default: return null;
    }
  }

  return (
    <div>
      <div className="totals">
        <div><b>{result.totals.stops}</b> stops</div>
        <div><b>{formatDuration(result.totals.time_s)}</b> driving</div>
        <div><b>{formatDistance(result.totals.distance_m, settings.units)}</b></div>
        <div className="muted">
          Optimized for {result.objective === "distance" ? "least miles" : "fastest time"} · arrival times allow {result.minutes_per_stop ?? 0} min per stop
        </div>
        <div className="spacer" />
        <a className="btn" href={api.csvUrl(plan.id)}>Download CSV</a>
        <a className="btn" href={`#/print/${plan.day}`} target="_blank" rel="noreferrer">Driver sheets</a>
      </div>

      {result.warnings.map((w, i) => <div key={i} className="note note-warn">{w}</div>)}
      {result.unassigned.length > 0 && (
        <div className="note note-error">
          <b>{result.unassigned.length} stop(s) are not on any route.</b>
          <ul>
            {result.unassigned.map((u) => {
              const s = stopsById.get(u.stop_id);
              return <li key={u.stop_id}>{s ? addressLine(s) : `Stop ${u.stop_id}`}: {u.reason}</li>;
            })}
          </ul>
        </div>
      )}

      <div ref={mapBox}>
        <MapView
          tileUrl={settings.tile_url} height="min(70vh, 640px)" markers={markers} lines={lines}
          fitKey={`${result.computed_at}:${focus}`}
          panTo={picked && picked.from === "list" && pickedStop && pickedStop.lat !== null && pickedStop.lon !== null
            ? { lat: pickedStop.lat, lon: pickedStop.lon, key: `${picked.id}:${picked.n}` } : null}
        />
      </div>
      <div className="hint">
        Click a stop to find it on the map, or a pin to find it in the list.{" "}
        {focus === null ? "Click a driver's name to show only their route." : (
          <button className="btn-link" onClick={() => setFocus(null)}>Show all routes</button>
        )}
      </div>

      <div className="cards">
        {result.routes.map((r) => {
          const stops = r.stop_ids.map((id) => stopsById.get(id)).filter((s): s is Stop => !!s);
          const canMakeUsual = r.kind === "volunteer" && !r.locked && stops.some((s) => s.label === "added" || s.label === "manual");
          return (
            <div key={r.driver_id} className={`card${focus === r.driver_id ? " card-focus" : ""}`}>
              <div className="card-head" onClick={() => setFocus(focus === r.driver_id ? null : r.driver_id)}>
                <span className="dot" style={{ background: r.color }} />
                <h3>{r.name}</h3>
                <Badge kind={r.kind === "volunteer" ? "vol" : "staff"}>{r.kind === "volunteer" ? "Volunteer" : "Staff"}</Badge>
                {r.locked && <Badge kind="lock">🔒 Locked</Badge>}
                {r.avoid_highways && <Badge kind="plain">Avoids highways</Badge>}
                {r.order_mode === "list" && <Badge kind="plain">List order</Badge>}
                {r.order_mode === "manual" && <Badge kind="info">Arranged by hand</Badge>}
              </div>
              <div className="card-stats">
                {r.stops} stops · {formatDuration(r.time_s)} driving · {formatDistance(r.distance_m, settings.units)}
              </div>
              {r.stops > 0 && (
                <div className="card-usage">Leaves {clock(r.start_time)} · done about {clock(r.finish_time)}</div>
              )}
              {r.order_mode === "manual" && (
                <button className="btn btn-small" disabled={busy} onClick={() => onResetOrder(r.driver_id)}>
                  Back to automatic order
                </button>
              )}
              {r.limits && usageText(r) && <div className="card-usage">Limits: {usageText(r)}</div>}
              {r.over_limit.map((o, i) => <div key={i} className="note note-error">Over limit: {o}</div>)}
              {canMakeUsual && (
                <button className="btn btn-small" disabled={busy} onClick={() => onMakeAllUsual(r.driver_id)}>
                  Make all added stops usual
                </button>
              )}
              {stops.length === 0 && <div className="muted">No stops today.</div>}
              <ol className="stops">
                {stops.map((s, i) => (
                  <li
                    key={s.id} id={`stop-${s.id}`}
                    onClick={(e) => { if (!(e.target as HTMLElement).closest("button, select, input, .grip")) setPicked({ id: s.id, from: "list", n: Date.now() }); }}
                    className={`${picked?.id === s.id ? "picked " : ""}${drag?.id === s.id ? "dragging" : ""}${over === s.id && drag && drag.driver === r.driver_id && drag.id !== s.id ? " drop-here" : ""}`}
                    onDragOver={(e) => { if (drag && drag.driver === r.driver_id) { e.preventDefault(); setOver(s.id); } }}
                    onDrop={(e) => { e.preventDefault(); drop(r, s.id); }}
                  >
                    <span
                      className="grip" title="Drag to move this stop within the route" draggable={!busy}
                      onDragStart={(e) => { e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", String(s.id)); setDrag({ driver: r.driver_id, id: s.id }); }}
                      onDragEnd={() => { setDrag(null); setOver(null); }}
                    >⠿</span>
                    <div className="stop-order">
                      <button className="btn-plain" title="Earlier in the route" disabled={busy || i === 0} onClick={() => onReorder(s, -1)}>▲</button>
                      <span className="stop-num" style={{ background: r.color }}>{s.stop_number}</span>
                      <button className="btn-plain" title="Later in the route" disabled={busy || i === stops.length - 1} onClick={() => onReorder(s, 1)}>▼</button>
                    </div>
                    <div className="stop-main">
                      <div>
                        {s.eta && <span className="eta">{clock(s.eta)}</span>}
                        {[s.street, s.unit].filter(Boolean).join(", ")}
                      </div>
                      <div className="muted small">
                        {s.city} {s.zip} · list row {s.seq}
                        {s.label === "added" && s.added_time_s !== null && s.added_distance_m !== null && (
                          <> · adds {formatDuration(Math.max(0, s.added_time_s))}, {formatDistance(Math.max(0, s.added_distance_m), settings.units)}</>
                        )}
                      </div>
                      <NoteLine value={s.notes} disabled={busy} onSave={(v) => onNotes(s, v)} />
                      <div className="chips">
                        {chip(s)}
                        {s.is_new_address && r.kind === "volunteer" && <Badge kind="new">New address</Badge>}
                        {r.kind === "volunteer" && !r.locked && (s.label === "added" || s.label === "manual") && (
                          <button className="btn btn-small" disabled={busy} onClick={() => onMakeUsual(s)}>Make usual stop</button>
                        )}
                      </div>
                    </div>
                    <select
                      className="move" value="" disabled={busy || (r.locked && s.label === "usual")}
                      title={r.locked && s.label === "usual" ? "Locked: turn the lock off to move this stop" : "Move this stop for today"}
                      onChange={(e) => {
                        const v = e.target.value;
                        if (v === "auto") onMove(s, null);
                        else if (v) onMove(s, Number(v));
                      }}
                    >
                      <option value="">Move…</option>
                      {s.manual_driver_id !== null && <option value="auto">Back to automatic</option>}
                      {working.filter((d) => d.id !== r.driver_id && !(d.locked && d.kind === "volunteer")).map((d) => (
                        <option key={d.id} value={d.id}>To {d.name}</option>
                      ))}
                    </select>
                  </li>
                ))}
              </ol>
            </div>
          );
        })}
      </div>
    </div>
  );
}
