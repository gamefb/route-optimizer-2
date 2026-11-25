import type {
  Address,
  Candidate,
  Driver,
  ImportJob,
  PendingAddress,
  Plan,
  RegionInfo,
  Settings,
  SettingsPatch,
} from "./types";

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") message = data.detail;
      else if (Array.isArray(data.detail)) message = data.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      /* keep the generic message */
    }
    throw new Error(message);
  }
  return res.json() as Promise<T>;
}

const get = <T>(p: string) => call<T>("GET", p);
const post = <T>(p: string, b: unknown = {}) => call<T>("POST", p, b);
const put = <T>(p: string, b: unknown) => call<T>("PUT", p, b);
const del = <T>(p: string) => call<T>("DELETE", p);

export const api = {
  settings: () => get<Settings>("/settings"),
  saveSettings: (s: SettingsPatch) => put<Settings>("/settings", s),
  region: () => get<RegionInfo>("/region"),
  regionCatalog: () => get<{ name: string; url: string }[]>("/region/catalog"),
  loadRegion: (name: string, url: string) => post<RegionInfo>("/region", { name, url }),
  geocode: (query: string) => post<Candidate[]>("/geocode", { query }),

  drivers: () => get<Driver[]>("/drivers"),
  createDriver: (d: Partial<Driver>) => post<Driver>("/drivers", d),
  updateDriver: (id: number, d: Partial<Driver>) => put<Driver>(`/drivers/${id}`, d),
  deleteDriver: (id: number) => del<{ ok: boolean }>(`/drivers/${id}`),

  addresses: (q = "", driverId?: number) =>
    get<Address[]>(`/addresses?q=${encodeURIComponent(q)}${driverId ? `&driver_id=${driverId}` : ""}`),
  setUsual: (id: number, driverId: number | null) =>
    put<Address>(`/addresses/${id}`, { set_usual: true, usual_driver_id: driverId }),
  moveAddress: (id: number, lat: number, lon: number) => put<Address>(`/addresses/${id}`, { lat, lon }),
  setNotes: (id: number, notes: string) => put<Address>(`/addresses/${id}`, { notes }),
  deleteAddress: (id: number) => del<{ ok: boolean }>(`/addresses/${id}`),

  planForDay: (day: string) => get<Plan>(`/plans/by-day/${day}`),
  updatePlan: (id: number, body: Partial<Pick<Plan, "objective" | "working_driver_ids" | "start_time">>) =>
    put<Plan>(`/plans/${id}`, body),
  paste: (id: number, text: string, mode: "replace" | "append") => post<Plan>(`/plans/${id}/paste`, { text, mode }),
  setLayout: (id: number, layout: string[]) => post<Plan>(`/plans/${id}/layout`, { layout }),
  addStop: (id: number, fields: Record<string, string>) => post<Plan>(`/plans/${id}/stops`, fields),
  clearStops: (id: number) => del<Plan>(`/plans/${id}/stops`),
  editStop: (id: number, fields: Record<string, string>) => put<Plan>(`/stops/${id}`, fields),
  deleteStop: (id: number) => del<Plan>(`/stops/${id}`),
  shiftStop: (id: number, direction: number) => post<Plan>(`/stops/${id}/shift`, { direction }),
  confirmMatch: (id: number, addressId?: number) =>
    post<Plan>(`/stops/${id}/confirm-match`, { address_id: addressId ?? null }),
  markNew: (id: number) => post<Plan>(`/stops/${id}/mark-new`),
  candidates: (id: number) =>
    get<{ candidates: Candidate[]; nearby_known: Address[]; error: string }>(`/stops/${id}/candidates`),
  confirmLocation: (id: number, lat: number, lon: number) => post<Plan>(`/stops/${id}/confirm-location`, { lat, lon }),

  compute: (id: number) => post<Plan>(`/plans/${id}/compute`),
  moveStop: (id: number, driverId: number | null) => post<Plan>(`/stops/${id}/move`, { driver_id: driverId }),
  makeUsual: (id: number) => post<Plan>(`/stops/${id}/make-usual`),
  makeAllUsual: (planId: number, driverId: number) =>
    post<Plan>(`/plans/${planId}/make-all-usual`, { driver_id: driverId }),
  csvUrl: (id: number) => `/api/plans/${id}/export.csv`,
  reorderStop: (id: number, direction: number) => post<Plan>(`/stops/${id}/reorder`, { direction }),
  resetOrder: (planId: number, driverId: number) => post<Plan>(`/plans/${planId}/reset-order`, { driver_id: driverId }),
  undo: (planId: number) => post<Plan>(`/plans/${planId}/undo`),

  importPreview: (text: string) =>
    post<{ layout: string[]; sample: string[][]; rows: number }>("/import/preview", { text }),
  importStart: (text: string, layout: string[], autoSave: boolean) =>
    post<ImportJob>("/import/addresses", { text, layout, auto_save: autoSave }),
  importStatus: () => get<ImportJob>("/import/status"),
  pending: () => get<PendingAddress[]>("/pending"),
  confirmPending: (key: string, lat: number, lon: number) => post<Address>("/pending/confirm", { key, lat, lon }),
  discardPending: (key: string) => post<{ ok: boolean }>("/pending/discard", { key }),
  backupUrl: "/api/backup",
  backupFiles: () => get<{ enabled: boolean; keep: number; files: { name: string; bytes: number }[] }>("/backup/files"),
  backupSave: () => post<{ ok: boolean; name: string }>("/backup/save"),
  setOrder: (planId: number, driverId: number, stopIds: number[]) =>
    post<Plan>(`/plans/${planId}/set-order`, { driver_id: driverId, stop_ids: stopIds }),
  restore: (data: unknown) => post<{ ok: boolean; drivers: number; addresses: number }>("/restore", data),
};
