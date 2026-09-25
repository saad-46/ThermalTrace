# Roadmap

The current state is described in `FINAL_STATUS.md`. The items below are ordered by the value they add to the SIH26162 core question: *what is this hot spot, really?*

| Horizon | Item | Why |
|---|---|---|
| Now | 12-month FIRMS backfill (needs MAP_KEY) | Persistence and seasonality need history |
| Now | Self-hosted Overpass or a preloaded India OSM extract | Full facility and land context for every event |
| Next | ESA WorldCover land-cover feature | Separates agricultural burns from wildfires properly |
| Next | Sentinel-2 SWIR hot-pixel test | An evidence-backed `CONFIRMED` state |
| Next | Train, calibrate and monitor LightGBM on adjudicated labels | Data-driven classification with SHAP evidence |
| Next | VIIRS Nightfire (licence permitting), GEM trackers, CEA list | Stronger flare and industrial attribution |
| Later | Daily intelligence brief, multi-event correlation, anomaly severity index | Operational reporting |
| Later | Team workspaces, comments, saved investigation templates, SSO/MFA | Collaboration and security |
| Later | Expo native app on the shared `src/lib` | Native notifications and offline sync |
| Later | Model drift monitoring, model comparison dashboard | ML operations |
