import { useState } from "react";
import type { Driver, Plan, Stop } from "./types";
import { Badge, SaveOnBlurInput } from "./ui";
import { addressLine, fuzzyMatch } from "./util";

const FIELDS = ["street", "unit", "city", "state", "zip"] as const;
const WIDTH_CH = { street: 24, unit: 8, city: 14, state: 4, zip: 10 }; // room for a typical value, in characters

interface Props {
  plan: Plan;
  drivers: Driver[];
  busy: boolean;
  onEdit: (stop: Stop, fields: Record<string, string>) => void;
  onDelete: (stop: Stop) => void;
  onShift: (stop: Stop, direction: number) => void;
  onConfirmMatch: (stop: Stop, addressId: number) => void;
  onMarkNew: (stop: Stop) => void;
  onValidate: (stop: Stop) => void;
  onAdd: (fields: Record<string, string>) => void;
}

export default function ReviewTable(p: Props) {
  const [onlyAttention, setOnlyAttention] = useState(false);
  const [query, setQuery] = useState("");
  const [draft, setDraft] = useState({ street: "", unit: "", city: "", state: "", zip: "" });
  const names = new Map(p.drivers.map((d) => [d.id, d.name]));
  const needs = p.plan.stops.filter((s) => s.match_state !== "matched");
  const base = onlyAttention ? needs : p.plan.stops;
  const rows = query.trim()
    ? base.filter((s) =>
        fuzzyMatch(
          query,
          `${s.seq} ${addressLine(s)} ${s.usual_driver_id ? names.get(s.usual_driver_id) || "" : ""} ${s.extras.join(" ")}`,
        ),
      )
    : base;

  function status(s: Stop) {
    if (s.match_state === "matched") {
      return (
        <>
          <Badge kind="ok">Matched</Badge>
          {s.is_new_address && <Badge kind="info">New today</Badge>}
        </>
      );
    }
    if (s.match_state === "possible" && s.candidates.length) {
      return (
        <div className="possible">
          <Badge kind="warn">Possible match</Badge>
          <span>{s.candidates.length > 1 ? "Which place is this?" : "Is this the same place?"}</span>
          {s.candidates.map((c) => (
            <button
              key={c.id}
              className="btn btn-small"
              disabled={p.busy}
              title="Use this known address"
              onClick={() => p.onConfirmMatch(s, c.id)}
            >
              {addressLine(c)}
            </button>
          ))}
          <button className="btn btn-small btn-ghost" disabled={p.busy} onClick={() => p.onMarkNew(s)}>
            Add new
          </button>
        </div>
      );
    }
    if (s.match_state === "invalid") {
      return (
        <>
          <Badge kind="bad">Fix this row</Badge> <span className="muted">{s.problem}</span>
        </>
      );
    }
    return (
      <>
        <Badge kind="new">New address</Badge>
        <button className="btn btn-small" disabled={p.busy} onClick={() => p.onValidate(s)}>
          Check on map
        </button>
      </>
    );
  }

  return (
    <div>
      <div className="table-tools row">
        <input
          className="search"
          type="search"
          value={query}
          placeholder="Search the table (street, city, zip, volunteer)"
          onChange={(e) => setQuery(e.target.value)}
        />
        {query.trim() && (
          <span className="muted">
            {rows.length} of {base.length} rows
          </span>
        )}
        <label className="check">
          <input type="checkbox" checked={onlyAttention} onChange={(e) => setOnlyAttention(e.target.checked)} />
          Show only rows that need attention ({needs.length})
        </label>
      </div>

      <div className="table-wrap">
        <table className="grid">
          <thead>
            <tr>
              <th>#</th>
              <th>Street</th>
              <th>Unit</th>
              <th>City</th>
              <th>State</th>
              <th>Zip</th>
              <th>Status</th>
              <th>Usual volunteer</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => (
              <tr key={s.id} className={s.match_state !== "matched" ? "row-attention" : ""}>
                <td className="num">{s.seq}</td>
                {FIELDS.map((f) => (
                  <td key={f}>
                    <SaveOnBlurInput
                      className="cell"
                      style={{ width: `${WIDTH_CH[f]}ch` }}
                      value={s[f]}
                      onSave={(v) =>
                        p.onEdit(s, {
                          street: s.street,
                          unit: s.unit,
                          city: s.city,
                          state: s.state,
                          zip: s.zip,
                          [f]: v,
                        })
                      }
                    />
                  </td>
                ))}
                <td className="status">
                  {status(s)}
                  {s.duplicate_of_seq !== null && <Badge kind="warn">Same as row {s.duplicate_of_seq}</Badge>}
                </td>
                <td>{s.usual_driver_id ? names.get(s.usual_driver_id) || "" : ""}</td>
                <td className="row-actions">
                  <button className="btn-plain" title="Move up" disabled={p.busy} onClick={() => p.onShift(s, -1)}>
                    ↑
                  </button>
                  <button className="btn-plain" title="Move down" disabled={p.busy} onClick={() => p.onShift(s, 1)}>
                    ↓
                  </button>
                  <button className="btn-plain" title="Remove row" disabled={p.busy} onClick={() => p.onDelete(s)}>
                    ✕
                  </button>
                </td>
              </tr>
            ))}
            <tr className="row-add">
              <td className="num">+</td>
              {FIELDS.map((f) => (
                <td key={f}>
                  <input
                    className="cell"
                    placeholder={f === "street" ? "Add a row: street" : f}
                    style={{ width: `${WIDTH_CH[f]}ch` }}
                    value={draft[f]}
                    onChange={(e) => setDraft({ ...draft, [f]: e.target.value })}
                  />
                </td>
              ))}
              <td colSpan={3}>
                <button
                  className="btn btn-small"
                  disabled={p.busy || !draft.street.trim()}
                  onClick={() => {
                    p.onAdd(draft);
                    setDraft({ street: "", unit: "", city: "", state: "", zip: "" });
                  }}
                >
                  Add row
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}
