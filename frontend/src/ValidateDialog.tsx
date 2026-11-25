import { useEffect, useState } from "react";
import { api } from "./api";
import MapView from "./MapView";
import type { Address, Candidate, Stop } from "./types";
import { ErrorNote, Modal } from "./ui";
import { errorText, useAction } from "./useAction";
import { addressLine } from "./util";

interface Props {
  stop: Stop;
  remaining: number;
  tileUrl: string;
  onConfirm: (lat: number, lon: number) => Promise<void>;
  onUseKnown: (addressId: number) => Promise<void>;
  onSkip: () => void;
  onClose: () => void;
}

/** Confirm that a new address is geocoded to the right place before it is saved. */
export default function ValidateDialog({ stop, remaining, tileUrl, onConfirm, onUseKnown, onSkip, onClose }: Props) {
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [nearby, setNearby] = useState<Address[]>([]);
  const [chosen, setChosen] = useState(0);
  const [pin, setPin] = useState<{ lat: number; lon: number } | null>(null);
  const [moved, setMoved] = useState(false);
  const [loading, setLoading] = useState(true);
  const { busy, error, setError, run: act } = useAction();

  useEffect(() => {
    let live = true;
    setLoading(true);
    setError("");
    setCandidates([]);
    setNearby([]);
    setPin(null);
    setMoved(false);
    setChosen(0);
    api.candidates(stop.id)
      .then((res) => {
        if (!live) return;
        setCandidates(res.candidates);
        setNearby(res.nearby_known);
        if (res.candidates.length) setPin({ lat: res.candidates[0].lat, lon: res.candidates[0].lon });
        if (res.error && !res.candidates.length) setError(res.error);
      })
      .catch((e) => live && setError(errorText(e)))
      .finally(() => live && setLoading(false));
    return () => { live = false; };
  }, [stop.id, setError]);

  const current = candidates[chosen];
  const outside = !moved && current?.on_map === false;

  return (
    <Modal title="Check this address on the map" onClose={onClose} wide>
      <div className="validate">
        <div className="validate-side">
          <div className="field-label">Pasted address (row {stop.seq})</div>
          <div className="validate-address">{addressLine(stop)}</div>

          <div className="field-label">What the lookup found</div>
          {loading && <div className="muted">Looking up…</div>}
          {!loading && !candidates.length && (
            <div className="note note-warn">
              Nothing was found for this address. Fix the spelling in the table, or click the map to place the pin yourself.
            </div>
          )}
          {candidates.map((c, i) => (
            <label key={i} className={`candidate${i === chosen ? " candidate-on" : ""}`}>
              <input
                type="radio" checked={i === chosen}
                onChange={() => { setChosen(i); setPin({ lat: c.lat, lon: c.lon }); setMoved(false); }}
              />
              <span>
                {c.label}
                {c.confidence === "low" && <span className="warn-text"> Low confidence{c.note ? `: ${c.note}` : ""}.</span>}
                {c.on_map === false && <span className="bad-text"> Outside the loaded map region.</span>}
              </span>
            </label>
          ))}

          {nearby.length > 0 && (
            <div className="note note-info">
              This lands on an address you already have:
              {nearby.map((a) => (
                <div key={a.id} className="row" style={{ marginTop: 6 }}>
                  <b>{addressLine(a)}</b>
                  <button className="btn btn-small" disabled={busy} onClick={() => act(() => onUseKnown(a.id))}>
                    It's the same place
                  </button>
                </div>
              ))}
            </div>
          )}

          <ErrorNote message={error} />
          <div className="hint">Drag the pin or click the map if the spot is wrong. The confirmed spot is saved and reused.</div>
          <div className="row validate-actions">
            <button
              className="btn btn-primary" disabled={busy || !pin || outside}
              onClick={() => pin && act(() => onConfirm(pin.lat, pin.lon))}
            >Confirm location</button>
            <button className="btn btn-ghost" disabled={busy} onClick={onSkip}>Skip for now</button>
            <span className="muted">{remaining} left to check</span>
          </div>
        </div>
        <MapView
          tileUrl={tileUrl} height={420}
          fitKey={pin ? `${stop.id}:${chosen}:${moved ? "moved" : "auto"}:${pin.lat}` : `none:${stop.id}`}
          markers={pin ? [{
            lat: pin.lat, lon: pin.lon, draggable: true, color: "#dc2626",
            onDrag: (lat, lon) => { setPin({ lat, lon }); setMoved(true); },
          }] : []}
          onClick={(lat, lon) => { setPin({ lat, lon }); setMoved(true); }}
        />
      </div>
    </Modal>
  );
}
