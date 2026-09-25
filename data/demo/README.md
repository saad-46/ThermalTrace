# Synthetic demo dataset — NOT raw NASA FIRMS records

`firms_demo_india.csv` and `facilities_demo_india.json` are **hand-constructed, synthetic**
data used only when no `FIRMS_MAP_KEY` is configured or the live API is unreachable. They are
inspired by publicly documented thermal-activity *patterns* at real, named locations (a refinery
flare pattern near Jamnagar, persistent coal-seam fire behavior near Jharia, seasonal stubble
burning in Punjab, a forest-fire season cluster in Uttarakhand, a stable thermal-power-plant
process-heat pattern, and one deliberately sparse/ambiguous case) so that every branch of the
classifier taxonomy (`docs/01-research.md` §3) has a demonstrable example, including the
"insufficient evidence" state.

**They are not a claim that these exact detections occurred.** Every row ingested from this file
is tagged `data_mode='demo'` in the database, is never mixed silently with live FIRMS data, and
the frontend always shows a visible "DEMO DATA — synthetic, for demonstration only" banner
whenever `data_mode='demo'` records are being displayed. See `docs/ARCHITECTURE.md` §3.

Coordinates are approximate to the named region, not exact facility footprints.
