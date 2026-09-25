"""seed reference data: roles, permissions, data-source registry

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

ROLES = [
    ("viewer", "Read-only access to events, map, facilities and reports.", 0),
    ("analyst", "Investigates events: reviews, notes, alerts, watchlists, reports.", 1),
    ("supervisor", "Analyst rights plus assignment, escalation handling and ingestion triggers.", 2),
    ("admin", "Full administration: users, roles, model versions, data sources.", 3),
]
PERMISSIONS = [
    ("events.read", "View thermal events and evidence"),
    ("events.review", "Record analyst decisions on events"),
    ("events.assign", "Assign events to analysts"),
    ("alerts.manage", "Create and manage own alert rules"),
    ("watchlists.manage", "Create and manage own watchlists"),
    ("reports.create", "Generate event reports"),
    ("ingestion.trigger", "Trigger ingestion / processing jobs"),
    ("admin.users", "Manage users and roles"),
    ("admin.system", "View system health, audit logs, model versions"),
]
GRANTS = {
    "viewer": ["events.read"],
    "analyst": ["events.read", "events.review", "alerts.manage", "watchlists.manage", "reports.create"],
    "supervisor": ["events.read", "events.review", "events.assign", "alerts.manage", "watchlists.manage",
                   "reports.create", "ingestion.trigger"],
    "admin": [p for p, _ in PERMISSIONS],
}
SOURCES = [
    ("firms", "NASA FIRMS", "detections", "https://firms.modaps.eosdis.nasa.gov",
     "NASA open data; cite 'NASA FIRMS'", "api", "NRT files refresh ~every 3h per sensor; polled every 30 min"),
    ("osm", "OpenStreetMap (Overpass)", "facilities", "https://www.openstreetmap.org",
     "ODbL 1.0 — © OpenStreetMap contributors", "api", "Continuous community edits; queried on demand, cached 7 days"),
    ("gem", "Global Energy Monitor trackers", "facilities", "https://globalenergymonitor.org/projects/",
     "CC BY 4.0 (per tracker terms)", "file_import", "Tracker releases (semi-annual); imported from downloaded release files"),
    ("cea", "Central Electricity Authority (India)", "facilities", "https://cea.nic.in",
     "Government of India open data", "file_import", "Official releases; imported from published files"),
    ("wri_gppd", "WRI Global Power Plant Database", "facilities", "https://datasets.wri.org/dataset/globalpowerplantdatabase",
     "CC BY 4.0", "file_import", "Static release (v1.3.0, 2021); India entries derived from CEA"),
    ("earth_search", "Sentinel-2 L2A (Element84 Earth Search)", "imagery", "https://earth-search.aws.element84.com/v1",
     "Copernicus Sentinel data, free and open", "api", "New scenes every ~5 days per location"),
    ("cdse", "Copernicus Data Space Ecosystem", "imagery", "https://dataspace.copernicus.eu",
     "Copernicus Sentinel data, free and open", "oauth", "STAC catalogue keyless; processing API requires OAuth client"),
    ("open_meteo", "Open-Meteo", "weather", "https://open-meteo.com",
     "CC BY 4.0", "api", "Hourly model data; ERA5 archive with ~5 day latency"),
    ("nominatim", "OSM Nominatim", "geocoding", "https://nominatim.openstreetmap.org",
     "ODbL 1.0 — © OpenStreetMap contributors", "api", "On demand, ≤1 request/second, cached"),
    ("demo", "Synthetic demo dataset", "detections", "data/demo/README.md",
     "Synthetic — not observational data", "file_import", "Static; loadable only when DEMO_MODE=true"),
]


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("INSERT INTO roles (name, description, rank) VALUES (:n, :d, :r) ON CONFLICT DO NOTHING"),
                 [{"n": n, "d": d, "r": r} for n, d, r in ROLES])
    conn.execute(sa.text("INSERT INTO permissions (code, description) VALUES (:c, :d) ON CONFLICT DO NOTHING"),
                 [{"c": c, "d": d} for c, d in PERMISSIONS])
    conn.execute(sa.text("INSERT INTO role_permissions (role, permission) VALUES (:r, :p) ON CONFLICT DO NOTHING"),
                 [{"r": r, "p": p} for r, perms in GRANTS.items() for p in perms])
    conn.execute(
        sa.text(
            "INSERT INTO data_sources (id, name, kind, homepage, license, access, cadence, status, records_total, "
            "requests_total, requests_failed) VALUES (:id, :name, :kind, :home, :lic, :access, :cadence, 'unknown', 0, 0, 0) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        [dict(zip(("id", "name", "kind", "home", "lic", "access", "cadence"), s)) for s in SOURCES],
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM role_permissions"))
    conn.execute(sa.text("DELETE FROM permissions"))
    # Seed rows may be referenced by real data (runs, facility sources, observations); only remove
    # the unreferenced ones — referenced rows disappear with their tables in 0001's downgrade.
    conn.execute(sa.text(
        """DELETE FROM data_sources d WHERE NOT EXISTS (SELECT 1 FROM ingestion_runs r WHERE r.source_id = d.id)
             AND NOT EXISTS (SELECT 1 FROM ingestion_checkpoints c WHERE c.source_id = d.id)
             AND NOT EXISTS (SELECT 1 FROM facility_sources f WHERE f.source_id = d.id)
             AND NOT EXISTS (SELECT 1 FROM weather_observations w WHERE w.source_id = d.id)
             AND NOT EXISTS (SELECT 1 FROM satellite_observations s WHERE s.source_id = d.id)"""))
