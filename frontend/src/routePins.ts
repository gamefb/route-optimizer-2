import type { MapMarker } from "./MapView";
import type { RouteResult, Stop } from "./types";

/** Stops grouped by spot, in route order: several units in one building share a pin. */
function stopsBySpot(stops: Stop[]): Stop[][] {
  const groups = new Map<string, Stop[]>();
  for (const s of stops) {
    if (s.lat === null || s.lon === null) continue;
    const key = `${s.lat},${s.lon}`;
    groups.set(key, [...(groups.get(key) || []), s]);
  }
  return [...groups.values()];
}

/** What a pin says: "7" for one stop, "7-9" for several at the same spot. */
function pinText(group: Stop[]): string {
  const nums = group.map((s) => s.stop_number || 0).sort((a, b) => a - b);
  return nums.length > 1 ? `${nums[0]}-${nums[nums.length - 1]}` : String(nums[0]);
}

/**
 * The pins for one route: its start ("S"), its end ("E") if that is somewhere else,
 * and one numbered pin per spot. "each" can add to a stop pin (a title, a click).
 */
export function routePins(
  r: RouteResult,
  stops: Stop[],
  color: string,
  options: { titles?: boolean; each?: (group: Stop[], text: string) => Partial<MapMarker> } = {},
): MapMarker[] {
  const title = (what: string) => (options.titles ? { title: `${r.name}: ${what}` } : {});
  const pins: MapMarker[] = [
    { lat: r.start[0], lon: r.start[1], color, shape: "square", text: "S", ...title("start") },
  ];
  if (r.end[0] !== r.start[0] || r.end[1] !== r.start[1]) {
    pins.push({ lat: r.end[0], lon: r.end[1], color, shape: "square", text: "E", ...title("end") });
  }
  for (const group of stopsBySpot(stops)) {
    const text = pinText(group);
    pins.push({
      lat: group[0].lat as number,
      lon: group[0].lon as number,
      color,
      text,
      ...options.each?.(group, text),
    });
  }
  return pins;
}
