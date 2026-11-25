import { useCallback, useState } from "react";

/** The message to show for something that was thrown. */
export function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/**
 * Runs a request for a screen: "busy" is true while it is under way, and "error"
 * holds the message if it failed. run() gives back the result, or null on failure.
 */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const run = useCallback(async <T>(fn: () => Promise<T>): Promise<T | null> => {
    setBusy(true);
    setError("");
    try {
      return await fn();
    } catch (e) {
      setError(errorText(e));
      return null;
    } finally {
      setBusy(false);
    }
  }, []);
  return { busy, error, setError, run };
}
