import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Async, errText, useToast } from "../components/ui";
import { api, patch, post } from "../lib/api";
import { relTime, titleCase } from "../lib/format";
import { useSession, useTheme } from "../lib/session";
import { enablePush, pushState } from "../lib/push";
import type { Page, Role, User } from "../lib/types";

function Users() {
  const toast = useToast();
  const qc = useQueryClient();
  const users = useQuery({ queryKey: ["users"], queryFn: () => api<Page<User>>("/admin/users", { query: { limit: 200 } }) });
  const [f, setF] = useState({ email: "", full_name: "", password: "", role: "analyst" as Role });
  const create = async () => {
    try { await post("/admin/users", f); toast("User created"); setF({ email: "", full_name: "", password: "", role: "analyst" }); qc.invalidateQueries({ queryKey: ["users"] }); }
    catch (e) { toast(errText(e), "error"); }
  };
  const update = async (id: string, body: Partial<User>) => {
    try { await patch(`/admin/users/${id}`, body); qc.invalidateQueries({ queryKey: ["users"] }); } catch (e) { toast(errText(e), "error"); }
  };
  return (
    <section className="panel" style={{ marginTop: 12 }} data-tour-id="users-roles">
      <div className="panel-head"><h2>Users & roles</h2></div>
      <div className="section row wrap" style={{ alignItems: "flex-end" }}>
        <div className="field"><label htmlFor="u-email">Email</label><input id="u-email" className="input" type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></div>
        <div className="field"><label htmlFor="u-name">Full name</label><input id="u-name" className="input" value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} /></div>
        <div className="field"><label htmlFor="u-pw">Initial password</label><input id="u-pw" className="input" type="password" autoComplete="new-password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></div>
        <div className="field"><label htmlFor="u-role">Role</label><select id="u-role" className="select" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value as Role })}>{["viewer", "analyst", "supervisor", "admin"].map((r) => <option key={r}>{r}</option>)}</select></div>
        <button className="btn primary" onClick={create} disabled={!f.email || !f.full_name || f.password.length < 12}>Create user</button>
        <div className="help faint" style={{ width: "100%", fontSize: 11.5 }}>Passwords need ≥ 12 characters mixing three of: lowercase, uppercase, digits, symbols.</div>
      </div>
      <Async q={users}>{(d) => (
        <table className="table"><thead><tr><th scope="col">User</th><th scope="col">Role</th><th scope="col">Status</th><th scope="col">Last login</th></tr></thead>
          <tbody>{d.items.map((u) => (
            <tr key={u.id}><td>{u.full_name}<div className="faint" style={{ fontSize: 11.5 }}>{u.email}</div></td>
              <td><select className="select" aria-label={`Role for ${u.email}`} value={u.role} onChange={(e) => update(u.id, { role: e.target.value as Role })}>{["viewer", "analyst", "supervisor", "admin"].map((r) => <option key={r}>{r}</option>)}</select></td>
              <td><label className="check"><input type="checkbox" checked={u.is_active} onChange={(e) => update(u.id, { is_active: e.target.checked })} /> active</label></td>
              <td className="num">{relTime(u.last_login_at)}</td></tr>
          ))}</tbody></table>
      )}</Async>
    </section>
  );
}

export default function Settings() {
  const { user, can } = useSession();
  const [theme, setTheme] = useTheme();
  const toast = useToast();
  const [push, setPush] = useState(pushState());
  return (
    <div className="page">
      <div className="page-head"><div><h1>Settings</h1></div></div>
      <div className="grid cols-2">
        <section className="panel"><div className="panel-head"><h2>Account</h2></div><div className="panel-body">
          <dl className="kv"><dt>Name</dt><dd>{user?.full_name}</dd><dt>Email</dt><dd>{user?.email}</dd><dt>Role</dt><dd>{titleCase(user?.role)}</dd><dt>Last login</dt><dd>{relTime(user?.last_login_at)}</dd></dl>
        </div></section>
        <section className="panel"><div className="panel-head"><h2>Preferences</h2></div><div className="panel-body stack">
          <div className="field"><label>Theme</label><div className="seg">{(["light", "dark"] as const).map((t) => <button key={t} className={theme === t ? "on" : ""} onClick={() => setTheme(t)}>{titleCase(t)}</button>)}</div></div>
          <div className="field"><label>Push notifications on this device</label>
            <div className="row"><button className="btn" disabled={push !== "available"} onClick={async () => { try { await enablePush(); setPush("enabled"); toast("Push notifications enabled"); } catch (e) { toast(errText(e), "error"); } }}>
              {push === "enabled" ? "Enabled" : "Enable"}</button>
              <span className="faint" style={{ fontSize: 12 }}>{push === "unsupported" ? "This browser does not support Web Push." : push === "denied" ? "Blocked in browser settings." : "Requires server VAPID configuration."}</span></div></div>
        </div></section>
      </div>
      {can("admin") && <Users />}
    </div>
  );
}
