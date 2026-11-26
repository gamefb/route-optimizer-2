import { InputHTMLAttributes, ReactNode, useEffect, useRef, useState } from "react";
import { api } from "./api";
import MapView from "./MapView";
import type { Candidate } from "./types";
import { useAction } from "./useAction";

export function Modal({
  title,
  onClose,
  children,
  wide,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal${wide ? " modal-wide" : ""}`} role="dialog" aria-label={title}>
        <div className="modal-head">
          <h2>{title}</h2>
          <button className="btn-plain" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}

export function ErrorNote({ message }: { message: string }) {
  return message ? <div className="note note-error">{message}</div> : null;
}

export function Badge({ kind, children }: { kind: string; children: ReactNode }) {
  return <span className={`badge badge-${kind}`}>{children}</span>;
}

type InputProps = Omit<
  InputHTMLAttributes<HTMLInputElement>,
  "value" | "className" | "onChange" | "onBlur" | "onKeyDown"
>;

/** A text box that saves when you leave it or press Enter, and only if the text changed. */
export function SaveOnBlurInput({
  value,
  onSave,
  trim,
  className,
  ...rest
}: InputProps & {
  value: string;
  onSave: (v: string) => void;
  trim?: boolean; // ignore spaces at either end
  className?: string | ((text: string) => string);
}) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  const next = trim ? text.trim() : text;
  return (
    <input
      {...rest}
      className={typeof className === "function" ? className(text) : className}
      value={text}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => next !== value && onSave(next)}
      onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
    />
  );
}

export interface PickedLocation {
  label: string;
  lat: number | null;
  lon: number | null;
}

/** Type an address, pick the result, and fine-tune the pin on a map. */
export function LocationPicker({
  value,
  onChange,
  tileUrl,
  placeholder,
}: {
  value: PickedLocation;
  onChange: (v: PickedLocation) => void;
  tileUrl: string;
  placeholder?: string;
}) {
  const [query, setQuery] = useState(value.label);
  const [found, setFound] = useState<Candidate[]>([]);
  const { busy, error, setError, run } = useAction();

  useEffect(() => setQuery(value.label), [value.label]);

  const search = () =>
    run(async () => {
      const res = await api.geocode(query);
      setFound(res);
      if (!res.length) setError("No match found. Check the address, or click the map to place the pin.");
      else pick(res[0]);
    });

  function pick(c: Candidate) {
    onChange({ label: query || c.label, lat: c.lat, lon: c.lon });
    if (c.on_map === false) setError("That spot is outside the loaded map region.");
  }

  const has = value.lat !== null && value.lon !== null;
  return (
    <div className="picker">
      <div className="row">
        <input
          value={query}
          placeholder={placeholder || "Street address, city, state, zip"}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), search())}
        />
        <button type="button" className="btn" disabled={busy || !query.trim()} onClick={search}>
          {busy ? "Looking…" : "Find"}
        </button>
      </div>
      {found.length > 1 && (
        <div className="choices">
          {found.map((c, i) => (
            <button type="button" key={i} className="choice" onClick={() => pick(c)}>
              {c.label}
            </button>
          ))}
        </div>
      )}
      <ErrorNote message={error} />
      <MapView
        tileUrl={tileUrl}
        height={320}
        fitKey={has ? `${value.lat},${value.lon}` : "none"}
        markers={
          has
            ? [
                {
                  lat: value.lat as number,
                  lon: value.lon as number,
                  draggable: true,
                  onDrag: (lat, lon) => onChange({ ...value, label: value.label || query, lat, lon }),
                },
              ]
            : []
        }
        onClick={(lat, lon) => onChange({ label: value.label || query, lat, lon })}
      />
      <div className="hint">
        {has ? "Drag the pin or click the map to adjust." : "Find an address, or click the map to place the pin."}
      </div>
    </div>
  );
}

function recall(key: string, fallback: boolean): boolean {
  try {
    const v = window.localStorage.getItem(key);
    return v === null ? fallback : v === "1";
  } catch {
    return fallback;
  }
}

/** A section that folds away to its heading to save space. Remembers its state on this computer. */
export function Fold({
  id,
  title,
  step,
  summary,
  startOpen = true,
  plain,
  done,
  children,
}: {
  id: string;
  title: string;
  step?: number;
  summary?: string;
  startOpen?: boolean;
  plain?: boolean;
  done?: boolean; // folds itself when this turns true, and opens again when it turns false
  children: ReactNode;
}) {
  const key = `fold:${id}`;
  const [open, setOpen] = useState(() => (done === undefined ? recall(key, startOpen) : !done));
  const wasDone = useRef(done);
  useEffect(() => {
    if (done !== undefined && done !== wasDone.current) setOpen(!done);
    wasDone.current = done;
  }, [done]);
  function toggle() {
    const next = !open;
    setOpen(next);
    try {
      window.localStorage.setItem(key, next ? "1" : "0");
    } catch {
      /* not remembered, still works */
    }
  }
  const head = (
    <button
      type="button"
      className={`fold-head${plain ? " fold-head-plain" : ""}`}
      onClick={toggle}
      aria-expanded={open}
    >
      <span className="fold-arrow">{open ? "▾" : "▸"}</span>
      {step !== undefined && <span className="step">{step}</span>}
      <span className="fold-title">{title}</span>
      {summary && <span className="fold-summary">{summary}</span>}
    </button>
  );
  if (plain)
    return (
      <div className="fold-plain">
        {head}
        {open && <div className="fold-body">{children}</div>}
      </div>
    );
  return (
    <section className={open ? "" : "folded"}>
      {head}
      {open && <div className="fold-body">{children}</div>}
    </section>
  );
}
