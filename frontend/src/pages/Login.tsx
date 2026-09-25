import { useState, type FormEvent } from "react";
import { errText } from "../components/ui";
import { useSession } from "../lib/session";

export default function Login() {
  const { login } = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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

  return (
    <main className="auth">
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
    </main>
  );
}
