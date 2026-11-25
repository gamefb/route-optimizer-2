export type Kind = "staff" | "volunteer";

export interface Driver {
  id: number;
  name: string;
  kind: Kind;
  color: string;
  start_label: string;
  start_lat: number | null;
  start_lon: number | null;
  end_label: string;
  end_lat: number | null;
  end_lon: number | null;
  avoid_highways: boolean;
  start_time: string;
  max_stops: number | null;
  max_route_minutes: number | null;
  zip_codes: string[];
  locked: boolean;
  usual_stops: number;
}

export interface Address {
  id: number;
  street: string;
  unit: string;
  city: string;
  state: string;
  zip: string;
  lat: number;
  lon: number;
  usual_driver_id: number | null;
  notes: string;
}

export interface PendingAddress {
  key: string;
  street: string;
  unit: string;
  city: string;
  state: string;
  zip: string;
  usual_driver_id: number | null;
  notes: string;
  reason: string;
}

export interface ImportJob {
  status: "idle" | "running" | "done" | "error";
  total?: number;
  done?: number;
  saved?: number;
  updated?: number;
  pending?: number;
  problems?: string[];
  message?: string;
}

export type MatchState = "matched" | "possible" | "new" | "invalid";
export type Label = "" | "usual" | "added" | "covering" | "manual" | "staff" | "overflow";

export interface Stop {
  id: number;
  seq: number;
  street: string;
  unit: string;
  city: string;
  state: string;
  zip: string;
  extras: string[];
  match_state: MatchState;
  problem: string;
  duplicate_of_seq: number | null;
  is_new_address: boolean;
  address_id: number | null;
  lat: number | null;
  lon: number | null;
  usual_driver_id: number | null;
  notes: string;
  eta: string | null;
  candidates: Address[];
  manual_driver_id: number | null;
  driver_id: number | null;
  label: Label;
  covering_for_id: number | null;
  stop_number: number | null;
  added_time_s: number | null;
  added_distance_m: number | null;
}

export interface Limits {
  max_stops: number | null;
  max_route_minutes: number | null;
  zip_codes: string[];
}

export interface RouteResult {
  driver_id: number;
  name: string;
  kind: Kind;
  color: string;
  locked: boolean;
  avoid_highways: boolean;
  order_mode: "optimized" | "manual";
  start_time: string;
  finish_time: string;
  stop_ids: number[];
  stops: number;
  time_s: number;
  distance_m: number;
  over_limit: string[];
  shapes: string[];
  start: [number, number];
  end: [number, number];
  limits: Limits | null;
}

export interface PlanResult {
  objective: "time" | "distance";
  computed_at: string;
  routes: RouteResult[];
  unassigned: { stop_id: number; reason: string; covering_for_id: number | null }[];
  warnings: string[];
  totals: { time_s: number; distance_m: number; stops: number };
  minutes_per_stop: number;
}

export interface Plan {
  id: number;
  day: string;
  objective: "time" | "distance";
  working_driver_ids: number[];
  layout: string[];
  stale: boolean;
  start_time: string;
  undo_label: string;
  result: PlanResult | null;
  stops: Stop[];
}

export interface Candidate {
  lat: number;
  lon: number;
  label: string;
  confidence: "high" | "low";
  note: string;
  source: string;
  on_map: boolean | null;
}

export interface Settings {
  units: "mi" | "km";
  geocoder: string;
  tile_url: string;
  staff_balance: "stops" | "time" | "off";
  minutes_per_stop: number;
  default_start_time: string;
  has_google_key: boolean;
  has_mapbox_key: boolean;
  has_geocodio_key: boolean;
}

export interface SettingsPatch extends Partial<Settings> {
  google_key?: string;
  mapbox_key?: string;
  geocodio_key?: string;
}

export interface RegionInfo {
  status: string;
  name: string;
  url: string;
  message: string;
  built_at: string | null;
  ready: boolean;
  pending: { name: string; url: string; status: string; message: string } | null;
}
