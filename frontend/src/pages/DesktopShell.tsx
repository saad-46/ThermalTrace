import {
  Activity, Bell, BarChart3, Building2, Database, Eye, FileText, LayoutGrid, List, LogOut, Map as MapIcon, Moon, Server, Settings as Cog, Sun,
} from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";
import { DemoBanner, Freshness } from "../components/ui";
import { useUnread } from "../lib/hooks";
import { useSession, useTheme } from "../lib/session";
import { titleCase } from "../lib/format";

const NAV = [
  { group: "Monitor", items: [
    { to: "/overview", label: "Overview", icon: LayoutGrid },
    { to: "/map", label: "Live map", icon: MapIcon },
    { to: "/events", label: "Events", icon: List },
    { to: "/alerts", label: "Alerts", icon: Bell, badge: true },
    { to: "/watchlists", label: "Watchlists", icon: Eye },
  ] },
  { group: "Context", items: [
    { to: "/facilities", label: "Facilities", icon: Building2 },
    { to: "/analytics", label: "Analytics", icon: BarChart3 },
    { to: "/reports", label: "Reports", icon: FileText },
  ] },
  { group: "Operations", items: [
    { to: "/sources", label: "Data sources", icon: Database },
    { to: "/system", label: "System health", icon: Server, role: "admin" as const },
    { to: "/settings", label: "Settings", icon: Cog },
  ] },
];

export default function DesktopShell() {
  const { user, logout, can } = useSession();
  const unread = useUnread();
  const [theme, setTheme] = useTheme();
  return (
    <div className="shell">
      <nav className="nav" aria-label="Primary">
        <div className="brand"><span className="brand-mark" aria-hidden /> ThermalTrace</div>
        <div className="nav-list">
          {NAV.map((g) => (
            <div key={g.group}>
              <div className="nav-group">{g.group}</div>
              {g.items.filter((i) => !("role" in i) || can(i.role!)).map(({ to, label, icon: Icon, ...rest }) => (
                <NavLink key={to} to={to} className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}>
                  <Icon size={15} strokeWidth={1.75} aria-hidden /> {label}
                  {"badge" in rest && unread.data?.count ? <span className="count" aria-label={`${unread.data.count} unread`}>{unread.data.count}</span> : null}
                </NavLink>
              ))}
            </div>
          ))}
        </div>
        <div className="nav-foot">
          <div className="row" style={{ gap: 8 }}>
            <Activity size={14} className="faint" aria-hidden />
            <div style={{ minWidth: 0 }}>
              <div style={{ fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{user?.full_name}</div>
              <div className="faint" style={{ fontSize: 11.5 }}>{titleCase(user?.role)}</div>
            </div>
          </div>
          <div className="row">
            <button className="btn ghost sm icon" onClick={() => setTheme(theme === "dark" ? "light" : "dark")} aria-label="Toggle dark mode" title="Toggle theme">
              {theme === "dark" ? <Sun size={14} /> : <Moon size={14} />}
            </button>
            <button className="btn ghost sm" onClick={() => logout()}><LogOut size={14} /> Sign out</button>
          </div>
        </div>
      </nav>
      <header className="header">
        <Freshness />
        <span className="spacer" />
      </header>
      <main className="main" style={{ display: "flex", flexDirection: "column" }}>
        <DemoBanner />
        <div style={{ flex: 1, minHeight: 0, overflow: "auto", position: "relative" }}>
          <Outlet />
        </div>
      </main>
    </div>
  );
}
