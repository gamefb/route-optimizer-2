import type { Stop } from "./types";

export function formatDuration(seconds: number): string {
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m ? `${h} h ${m} min` : `${h} h`;
}

export function formatDistance(meters: number, units: "mi" | "km"): string {
  const value = units === "mi" ? meters / 1609.344 : meters / 1000;
  return `${value.toFixed(value < 10 ? 1 : 0)} ${units}`;
}

export function addressLine(s: Pick<Stop, "street" | "unit" | "city" | "state" | "zip">): string {
  const first = [s.street, s.unit].filter(Boolean).join(", ");
  const second = [s.city, [s.state, s.zip].filter(Boolean).join(" ")].filter(Boolean).join(", ");
  return [first, second].filter(Boolean).join(", ");
}

/** Decode a Valhalla route shape (encoded polyline, 6 decimal places). */
export function decodeShape(encoded: string): [number, number][] {
  const out: [number, number][] = [];
  let index = 0;
  let lat = 0;
  let lon = 0;
  while (index < encoded.length) {
    for (const which of [0, 1]) {
      let shift = 0;
      let result = 0;
      let byte: number;
      do {
        byte = encoded.charCodeAt(index++) - 63;
        result |= (byte & 0x1f) << shift;
        shift += 5;
      } while (byte >= 0x20);
      const delta = result & 1 ? ~(result >> 1) : result >> 1;
      if (which === 0) lat += delta;
      else lon += delta;
    }
    out.push([lat / 1e6, lon / 1e6]);
  }
  return out;
}

export function today(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function shiftDay(day: string, by: number): string {
  const [y, m, d] = day.split("-").map(Number);
  const date = new Date(y, m - 1, d + by);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function longDate(day: string): string {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

/** "14:05" to "2:05 PM". */
export function clock(time: string): string {
  const [h, m] = time.split(":").map(Number);
  if (Number.isNaN(h) || Number.isNaN(m)) return time;
  const suffix = h >= 12 ? "PM" : "AM";
  return `${h % 12 === 0 ? 12 : h % 12}:${String(m).padStart(2, "0")} ${suffix}`;
}

/**
 * Links that open a route in Google Maps. Google Maps shows at most 10 places
 * per route, so a long route is split into parts that each start where the last ended.
 */
export function googleMapsLinks(points: [number, number][]): string[] {
  const links: string[] = [];
  const fmt = (p: [number, number]) => `${p[0].toFixed(6)},${p[1].toFixed(6)}`;
  let i = 0;
  while (i < points.length - 1) {
    const part = points.slice(i, i + 10);
    const params = new URLSearchParams({
      api: "1",
      travelmode: "driving",
      origin: fmt(part[0]),
      destination: fmt(part[part.length - 1]),
    });
    const middle = part.slice(1, -1);
    if (middle.length) params.set("waypoints", middle.map(fmt).join("|"));
    links.push(`https://www.google.com/maps/dir/?${params.toString()}`);
    i += part.length - 1;
  }
  return links;
}

/**
 * Forgiving search: every word typed must appear in the text, allowing for small
 * typos ("mechnic" finds "Mechanic") and for letters typed in order with gaps ("lncstr").
 */
export function fuzzyMatch(query: string, text: string): boolean {
  const hay = text.toLowerCase();
  const words = hay.split(/[^a-z0-9]+/).filter(Boolean);
  return query
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((q) => {
      if (hay.includes(q)) return true;
      if (q.length < 3) return false;
      return words.some((w) => inOrder(q, w) || nearly(q, w.slice(0, Math.max(q.length, 1) + 1)));
    });
}

function inOrder(q: string, w: string): boolean {
  let i = 0;
  for (const ch of w) if (ch === q[i]) i++;
  return i === q.length && q.length * 2 >= w.length;
}

function nearly(a: string, b: string): boolean {
  // Edit distance of at most 1 (2 for longer words).
  const limit = a.length >= 7 ? 2 : 1;
  if (Math.abs(a.length - b.length) > limit + 1) return false;
  let prev = Array.from({ length: b.length + 1 }, (_, j) => j);
  let before = prev;
  for (let i = 1; i <= a.length; i++) {
    const cur = [i];
    for (let j = 1; j <= b.length; j++) {
      cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
      // two letters swapped ("gird" for "grid") counts as one slip
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1])
        cur[j] = Math.min(cur[j], before[j - 2] + 1);
    }
    before = prev;
    prev = cur;
  }
  return Math.min(prev[b.length], prev[Math.max(b.length - 1, 0)]) <= limit;
}
