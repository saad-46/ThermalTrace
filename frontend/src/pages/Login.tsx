import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { errText } from "../components/ui";
import { api } from "../lib/api";
import { useSession } from "../lib/session";
import type { DemoRole } from "../lib/types";

const EXPLORE: { role: DemoRole; title: string; text: string; button: string }[] = [
  { role: "analyst", title: "Explore as Analyst", button: "Explore analyst mode",
    text: "Investigate thermal events, review evidence, understand classifications and see how decisions are made." },
  { role: "admin", title: "Explore as Admin", button: "Explore admin mode",
    text: "See the platform behind the analysis: data sources, processing, models, alerts, audit trail and governance." },
];

export default function Login() {
  const { login, startDemo } = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [exploring, setExploring] = useState<DemoRole | null>(null);
  const [exploreError, setExploreError] = useState<string | null>(null);
  // Offered only when the server enables read-only guided exploration.
  const explore = useQuery({ queryKey: ["explore-config"], queryFn: () => api<{ enabled: boolean }>("/auth/demo"), retry: false, staleTime: 60_000 });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email.trim(), password);
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  };

  const start = async (role: DemoRole) => {
    setExploring(role);
    setExploreError(null);
    try {
      await startDemo(role);
    } catch (err) {
      setExploreError(errText(err));
      setExploring(null);
    }
  };

  return (
    <main className="auth">
      <div className="stack auth-stack">
        <form className="panel auth-card stack" style={{ gap: 14 }} onSubmit={submit} aria-labelledby="login-title">
          <div className="row" style={{ gap: 10 }}>
            <span className="brand-mark" aria-hidden />
            <div>
              <h1 id="login-title">ThermalTrace</h1>
              <div className="faint" style={{ fontSize: 12 }}>Industrial fire & persistent thermal source monitoring</div>
            </div>
          </div>
          <div className="field">
            <label htmlFor="email">Email</label>
            <input id="email" className="input" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </div>
          <div className="field">
            <label htmlFor="password">Password</label>
            <input id="password" className="input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </div>
          {error && <div role="alert" style={{ color: "var(--bad)", fontSize: 12.5 }}>{error}</div>}
          <button className="btn primary" type="submit" disabled={busy} style={{ justifyContent: "center" }}>
            {busy && <span className="spinner" />} Sign in
          </button>
          <div className="faint" style={{ fontSize: 11.5 }}>
            Accounts are issued by an administrator. Data: NASA FIRMS, OpenStreetMap, Copernicus Sentinel-2, Open-Meteo.
          </div>
        </form>

        {explore.data?.enabled && (
          <section className="panel auth-card explore-panel" aria-labelledby="explore-title">
            <h2 id="explore-title">Explore ThermalTrace</h2>
            <div className="faint" style={{ fontSize: 12 }}>No account required. A guided, read-only tour of the live application.</div>
            <div className="explore-options">
              {EXPLORE.map((o) => (
                <div key={o.role} className="explore-option">
                  <h3>{o.title}</h3>
                  <p>{o.text}</p>
                  <button className="btn" type="button" onClick={() => start(o.role)} disabled={exploring !== null} aria-busy={exploring === o.role}>
                    {exploring === o.role && <span className="spinner" />} {o.button}
                  </button>
                </div>
              ))}
            </div>
            {exploreError && <div role="alert" style={{ color: "var(--bad)", fontSize: 12.5 }}>{exploreError}</div>}
          </section>
        )}
      </div>
    </main>
  );
}
