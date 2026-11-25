import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useEffect, useRef } from "react";

export interface MapMarker {
  lat: number;
  lon: number;
  text?: string; // shown inside the pin, for example a stop number
  color?: string;
  title?: string;
  shape?: "pin" | "square";
  draggable?: boolean;
  onDrag?: (lat: number, lon: number) => void;
  onClick?: () => void;
  highlight?: boolean;
}

export interface MapLine {
  points: [number, number][];
  color: string;
}

interface Props {
  tileUrl: string;
  markers?: MapMarker[];
  lines?: MapLine[];
  height?: number | string;
  fitKey?: string; // the view re-fits whenever this changes
  panTo?: { lat: number; lon: number; key: string } | null; // move to this spot when the key changes
  onClick?: (lat: number, lon: number) => void;
  interactive?: boolean;
}

function icon(m: MapMarker): L.DivIcon {
  const color = m.color || "#2563eb";
  const cls = m.shape === "square" ? "map-pin map-pin-square" : "map-pin";
  const wide = ((m.text || "").length > 2 ? " map-pin-wide" : "") + (m.highlight ? " map-pin-hot" : "");
  return L.divIcon({
    className: "",
    html: `<div class="${cls}${wide}" style="background:${color}">${m.text ?? ""}</div>`,
    iconSize: [26, 26],
    iconAnchor: [13, 13],
  });
}

export default function MapView({ tileUrl, markers = [], lines = [], height = 360, fitKey, panTo, onClick, interactive = true }: Props) {
  const holder = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);
  const clickRef = useRef(onClick);
  clickRef.current = onClick;

  useEffect(() => {
    if (!holder.current || map.current) return;
    const m = L.map(holder.current, {
      zoomControl: interactive, dragging: interactive, scrollWheelZoom: interactive,
      doubleClickZoom: interactive, boxZoom: interactive, keyboard: interactive, touchZoom: interactive,
    }).setView([39.5, -98.35], 4);
    L.tileLayer(tileUrl, {
      maxZoom: 19, crossOrigin: true,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(m);
    m.on("click", (e) => clickRef.current?.(e.latlng.lat, e.latlng.lng));
    layer.current = L.layerGroup().addTo(m);
    map.current = m;
    const observer = new ResizeObserver(() => m.invalidateSize());
    observer.observe(holder.current);
    return () => {
      observer.disconnect();
      m.remove();
      map.current = null;
    };
  }, [tileUrl, interactive]);

  useEffect(() => {
    const group = layer.current;
    if (!group) return;
    group.clearLayers();
    for (const line of lines) {
      if (line.points.length > 1) {
        L.polyline(line.points, { color: "#ffffff", weight: 7, opacity: 0.9 }).addTo(group);
        L.polyline(line.points, { color: line.color, weight: 4, opacity: 0.95 }).addTo(group);
      }
    }
    for (const mk of markers) {
      const marker = L.marker([mk.lat, mk.lon], { icon: icon(mk), draggable: !!mk.draggable });
      if (mk.title) {
        // Leaflet reads a string as HTML. The title carries pasted address text, so pass it as plain text.
        const label = document.createElement("span");
        label.textContent = mk.title;
        marker.bindTooltip(label);
      }
      if (mk.onClick) marker.on("click", mk.onClick);
      if (mk.highlight) marker.setZIndexOffset(1000);
      if (mk.onDrag) {
        marker.on("dragend", () => {
          const p = marker.getLatLng();
          mk.onDrag?.(p.lat, p.lng);
        });
      }
      marker.addTo(group);
      if (mk.title) marker.getElement()?.setAttribute("aria-label", mk.title);
    }
  }, [markers, lines]);

  useEffect(() => {
    const m = map.current;
    if (!m) return;
    const pts: [number, number][] = [
      ...markers.map((x) => [x.lat, x.lon] as [number, number]),
      ...lines.flatMap((l) => l.points),
    ];
    if (pts.length === 1) m.setView(pts[0], 16);
    else if (pts.length > 1) m.fitBounds(L.latLngBounds(pts), { padding: [28, 28], maxZoom: 16 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fitKey]);

  useEffect(() => {
    if (map.current && panTo) map.current.setView([panTo.lat, panTo.lon], Math.max(map.current.getZoom(), 15), { animate: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [panTo?.key]);

  return <div ref={holder} className="map" style={{ height }} />;
}
