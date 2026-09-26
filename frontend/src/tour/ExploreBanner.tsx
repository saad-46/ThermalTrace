/** Shown during read-only demo sessions: states the mode plainly and offers restart, role switch and exit. */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { errText, useToast } from "../components/ui";
import { useSession } from "../lib/session";
import type { DemoRole } from "../lib/types";
import { clearTourState, useTour } from "./TourProvider";

export default function ExploreBanner({ compact }: { compact?: boolean }) {
  const { user, isDemo, logout, startDemo } = useSession();
  const { restart } = useTour();
  const navigate = useNavigate();
  const toast = useToast();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  if (!isDemo || !user) return null;
  const role = user.role as DemoRole;
  const other: DemoRole = role === "admin" ? "analyst" : "admin";
  const label = role === "admin" ? "Admin" : "Analyst";
  const otherLabel = other === "admin" ? "admin" : "analyst";

  const exit = async () => {
    setBusy(true);
    try { await logout(); } finally {
      clearTourState();
      navigate("/", { replace: true });
      setBusy(false);
    }
  };
  const switchRole = async () => {
    setBusy(true);
    try {
      clearTourState();
      await startDemo(other);
      navigate("/", { replace: true });
      setConfirming(false);
    } catch (e) {
      toast(errText(e), "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={`banner explore ${compact ? "compact" : ""}`} role="region" aria-label="Demo mode">
      <b className="explore-tag">Demo mode · {label}</b>
      {!compact && <span className="explore-text">A guided exploration using live ThermalTrace data. Changes are disabled in demo mode.</span>}
      <span className="spacer" />
      {confirming ? (
        <span className="row" style={{ gap: 6 }} role="group" aria-label={`Switch to the ${otherLabel} demo`}>
          <span>Switch to the {otherLabel} demo? This ends the {label.toLowerCase()} session.</span>
          <button className="btn sm primary" onClick={switchRole} disabled={busy}>Switch</button>
          <button className="btn sm" onClick={() => setConfirming(false)} disabled={busy}>Cancel</button>
        </span>
      ) : (
        <>
          <button className="btn sm ghost" onClick={restart}>Restart tour</button>
          <button className="btn sm ghost" onClick={() => setConfirming(true)}>Switch to {otherLabel} demo</button>
          <button className="btn sm" onClick={exit} disabled={busy}>Exit demo</button>
        </>
      )}
    </div>
  );
}
