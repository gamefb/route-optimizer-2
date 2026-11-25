import { toPng } from "html-to-image";
import QRCode from "qrcode";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import MapView, { MapLine } from "./MapView";
import { routePins } from "./routePins";
import type { Driver, Plan, RouteResult, Settings, Stop } from "./types";
import { ErrorNote } from "./ui";
import { errorText } from "./useAction";
import { clock, decodeShape, formatDistance, formatDuration, googleMapsLinks, longDate } from "./util";

/** Printable driver sheets: one page per driver with a numbered map and the stop list. */
export default function PrintPage({ day, settings, drivers }: { day: string; settings: Settings; drivers: Driver[] }) {
  const [plan, setPlan] = useState<Plan | null>(null);
  const [error, setError] = useState("");
  const [only, setOnly] = useState<number | "all">("all");

  useEffect(() => {
    api.planForDay(day).then(setPlan).catch((e) => setError(errorText(e)));
  }, [day]);

  if (error) return <div className="page"><ErrorNote message={error} /></div>;
  if (!plan) return <div className="page muted">Loading…</div>;
  if (!plan.result) return <div className="page"><div className="note note-warn">Build the routes for this day first.</div></div>;

  const routes = plan.result.routes.filter((r) => r.stops > 0 && (only === "all" || only === r.driver_id));
  return (
    <div className="print-page">
      <div className="print-tools no-print">
        <b>Driver sheets for {longDate(day)}</b>
        <select value={only} onChange={(e) => setOnly(e.target.value === "all" ? "all" : Number(e.target.value))}>
          <option value="all">All drivers</option>
          {plan.result.routes.filter((r) => r.stops > 0).map((r) => <option key={r.driver_id} value={r.driver_id}>{r.name}</option>)}
        </select>
        <button className="btn btn-primary" onClick={() => window.print()}>Print or save as PDF</button>
        <span className="muted">Use "Download image" on a sheet for a picture file.</span>
      </div>
      {routes.map((r) => (
        <Sheet key={r.driver_id} route={r} plan={plan} settings={settings} drivers={drivers} />
      ))}
      {routes.length === 0 && <div className="page muted">No driver has stops on this day.</div>}
    </div>
  );
}

function Sheet({ route: r, plan, settings, drivers }: { route: RouteResult; plan: Plan; settings: Settings; drivers: Driver[] }) {
  const ref = useRef<HTMLDivElement>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const names = new Map(drivers.map((d) => [d.id, d.name]));
  const byId = useMemo(() => new Map(plan.stops.map((s) => [s.id, s])), [plan.stops]);
  const stops = r.stop_ids.map((id) => byId.get(id)).filter((s): s is Stop => !!s); // in driving order
  const [codes, setCodes] = useState<{ url: string; image: string; label: string }[]>([]);

  // Links (and QR codes) that open the route on a phone, in driving order.
  useEffect(() => {
    let live = true;
    const located = stops.filter((s) => s.lat !== null && s.lon !== null);
    const points: [number, number][] = [r.start, ...located.map((s) => [s.lat, s.lon] as [number, number]), r.end];
    const links = googleMapsLinks(points);
    Promise.all(links.map((url) => QRCode.toDataURL(url, { margin: 1, width: 220, errorCorrectionLevel: "L" })))
      .then((images) => {
        if (!live) return;
        setCodes(links.map((url, i) => {
          // Part i runs from point i*9 to point i*9+9, where point 0 is the start and the last point is the end.
          const first = i * 9 + 1;
          const lastPoint = Math.min(i * 9 + 9, located.length + 1);
          const reachesEnd = lastPoint === located.length + 1;
          const last = Math.min(lastPoint, located.length);
          const label = first > located.length ? "Back to the end point"
            : `Stops ${first}-${last}${reachesEnd ? " and the end point" : ""}`;
          return { url, image: images[i], label: links.length === 1 ? "Whole route" : label };
        }));
      })
      .catch(() => live && setCodes([]));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [r, plan.stops]);

  const { markers, lines } = useMemo(() => {
    const lines: MapLine[] = r.shapes.map((s) => ({ points: decodeShape(s), color: "#111827" }));
    return { markers: routePins(r, stops, "#111827"), lines };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [r, plan.stops]);

  async function download() {
    if (!ref.current) return;
    setSaving(true);
    setError("");
    try {
      const url = await toPng(ref.current, { pixelRatio: 2, backgroundColor: "#ffffff", cacheBust: true });
      const a = document.createElement("a");
      a.href = url;
      a.download = `${plan.day}-${r.name.replace(/\s+/g, "-")}.png`;
      a.click();
    } catch {
      setError("Could not make the image. Use Print or save as PDF instead.");
    } finally {
      setSaving(false);
    }
  }

  function note(s: Stop): string {
    const who = s.covering_for_id ? names.get(s.covering_for_id) || "" : "";
    const parts = [];
    if (s.notes) parts.push(s.notes);
    if (s.label === "covering") parts.push(`Covering for ${who}`);
    if (s.label === "overflow") parts.push(`From ${who}`);
    if (s.label === "added") parts.push("Added today");
    return parts.join(" · ");
  }

  return (
    <div className="sheet-wrap">
      <div className="no-print sheet-tools">
        <button className="btn btn-small" disabled={saving} onClick={download}>{saving ? "Working…" : "Download image"}</button>
        {error && <span className="bad-text">{error}</span>}
      </div>
      <div className="sheet" ref={ref}>
        <div className="sheet-head">
          <div>
            <h1>{r.name}</h1>
            <div>{longDate(plan.day)}</div>
          </div>
          <div className="sheet-stats">
            <div><b>{r.stops}</b> stops</div>
            <div><b>{formatDuration(r.time_s)}</b> driving</div>
            <div><b>{formatDistance(r.distance_m, settings.units)}</b></div>
            <div>Leave <b>{clock(r.start_time)}</b>, done about <b>{clock(r.finish_time)}</b></div>
          </div>
        </div>
        <MapView tileUrl={settings.tile_url} markers={markers} lines={lines} height={380} fitKey={`${r.driver_id}:${plan.result?.computed_at}`} interactive={false} />
        <table className="sheet-table">
          <thead>
            <tr><th>Stop</th><th>List #</th><th>Arrive</th><th>Address</th><th>Unit</th><th>City</th><th>Zip</th><th>Note</th><th className="tick">Done</th></tr>
          </thead>
          <tbody>
            {stops.map((s) => (
              <tr key={s.id}>
                <td className="sheet-num">{s.stop_number}</td>
                <td className="sheet-list">{s.seq}</td>
                <td className="sheet-eta">{s.eta ? clock(s.eta) : ""}</td>
                <td>{s.street}</td><td>{s.unit}</td><td>{s.city}</td><td>{s.zip}</td>
                <td>{note(s)}</td><td className="tick"><span className="box" /></td>
              </tr>
            ))}
          </tbody>
        </table>
        {codes.length > 0 && (
          <div className="sheet-codes">
            <div className="sheet-codes-title">Open this route on a phone (scan with the camera)</div>
            <div className="sheet-codes-row">
              {codes.map((c, i) => (
                <a key={i} className="sheet-code" href={c.url} target="_blank" rel="noreferrer">
                  <img src={c.image} alt={`QR code: ${c.label}`} width={110} height={110} />
                  <span>{codes.length > 1 ? `Part ${i + 1}: ` : ""}{c.label}</span>
                </a>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
