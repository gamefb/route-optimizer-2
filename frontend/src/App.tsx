import { useCallback, useEffect, useState } from "react";
import AddressesPage from "./AddressesPage";
import { api } from "./api";
import DayPage from "./DayPage";
import DriversPage from "./DriversPage";
import PrintPage from "./PrintPage";
import SettingsPage from "./SettingsPage";
import type { Driver, RegionInfo, Settings } from "./types";
import { errorText } from "./useAction";
import { today } from "./util";

function useHash(): string[] {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const on = () => setHash(window.location.hash);
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return hash.replace(/^#\/?/, "").split("/").filter(Boolean);
}

export default function App() {
  const parts = useHash();
  const page = parts[0] || "day";
  const [settings, setSettings] = useState<Settings | null>(null);
  const [drivers, setDrivers] = useState<Driver[]>([]);
  const [region, setRegion] = useState<RegionInfo | null>(null);
  const [error, setError] = useState("");

  const reloadDrivers = useCallback(() => {
    api
      .drivers()
      .then(setDrivers)
      .catch((e) => setError(errorText(e)));
  }, []);
  const reloadRegion = useCallback(() => {
    api
      .region()
      .then(setRegion)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    api
      .settings()
      .then(setSettings)
      .catch((e) => setError(errorText(e)));
    reloadDrivers();
    reloadRegion();
  }, [reloadDrivers, reloadRegion]);

  // While a map region is being prepared, keep checking on it.
  const preparing = !!region?.pending && region.pending.status !== "error";
  useEffect(() => {
    if (!preparing) return;
    const t = setInterval(reloadRegion, 3000);
    return () => clearInterval(t);
  }, [preparing, reloadRegion]);

  // Remember the day being worked on, so leaving for another tab and coming back returns to it.
  const [lastDay, setLastDay] = useState<string>(() => {
    try {
      return window.sessionStorage.getItem("day") || today();
    } catch {
      return today();
    }
  });
  const urlDay = page === "day" && /^\d{4}-\d{2}-\d{2}$/.test(parts[1] || "") ? parts[1] : "";
  useEffect(() => {
    if (!urlDay) return;
    setLastDay(urlDay);
    try {
      window.sessionStorage.setItem("day", urlDay);
    } catch {
      /* still remembered until the page is closed */
    }
  }, [urlDay]);
  const day = urlDay || lastDay;

  if (error && !settings)
    return (
      <div className="page">
        <div className="note note-error">Cannot reach the server: {error}</div>
      </div>
    );
  if (!settings) return <div className="page muted">Loading…</div>;

  if (page === "print") {
    return <PrintPage day={parts[1] || today()} settings={settings} drivers={drivers} />;
  }

  const tab = (name: string, label: string, href: string) => (
    <a className={`tab${page === name ? " tab-on" : ""}`} href={href}>
      {label}
    </a>
  );
  return (
    <>
      <header className="top">
        <div className="brand">Route Planner</div>
        <nav>
          {tab("day", "Day plan", `#/day/${day}`)}
          {tab("drivers", "Drivers", "#/drivers")}
          {tab("addresses", "Addresses", "#/addresses")}
          {tab("settings", "Settings", "#/settings")}
        </nav>
        <div className="top-status">
          {region && (region.ready ? `Map: ${region.name}` : preparing ? "Preparing map…" : "No map loaded")}
        </div>
      </header>
      {page === "day" && (
        <DayPage
          day={day}
          setDay={(d) => {
            window.location.hash = `#/day/${d}`;
          }}
          settings={settings}
          drivers={drivers}
          region={region}
          reloadDrivers={reloadDrivers}
        />
      )}
      {page === "drivers" && <DriversPage drivers={drivers} settings={settings} reload={reloadDrivers} />}
      {page === "addresses" && (
        <AddressesPage
          drivers={drivers}
          settings={settings}
          driverId={parts[1] ? Number(parts[1]) : null}
          reloadDrivers={reloadDrivers}
        />
      )}
      {page === "settings" && (
        <SettingsPage
          settings={settings}
          region={region}
          onSettings={setSettings}
          reloadRegion={reloadRegion}
          reloadAll={() => {
            api
              .settings()
              .then(setSettings)
              .catch(() => undefined);
            reloadDrivers();
          }}
        />
      )}
    </>
  );
}
