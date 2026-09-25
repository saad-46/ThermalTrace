# Feature roadmap

The current state is in `FINAL_STATUS.md`. Items are ordered by the value they add to the SIH26162 core question: *what is this hot spot, really?*

## Done in the consolidation phase

- Local facility index: scheduled OSM tile sync instead of per-event Overpass queries.
- Triage priority with explanation, and a priority-ordered review queue.
- Global search: event ids, places, facilities, classifications, coordinates.
- Evidence chain, per-day persistence strip, qualitative confidence decomposition.
- Training feedback dataset export.
- Alert cooldown with recorded suppression.
- Facility thermal-activity profile; attribution rings on the map; weather in the timeline.
- Tablet layout, table accessibility semantics, frontend component tests.

## Next

| Horizon | Item | Why |
|---|---|---|
| Now | Add `FIRMS_MAP_KEY` and backfill 12 months of history | Persistence and seasonality need history. Today "persistent" means within the loaded window. |
| Now | Let the facility sync finish (297 tiles); optionally self-host Overpass | Full facility context for every event within hours, not days |
| Now | Analysts adjudicate the high-priority queue, then `train` and activate LightGBM | Data-driven classification with live SHAP evidence |
| Next | ESA WorldCover land-cover feature (then a land-cover filter) | Proper separation of agricultural burns from wildfires |
| Next | Sentinel-2 SWIR hot-pixel test (needs CDSE credentials) | An evidence-backed `CONFIRMED` state |
| Next | Shared filter state between map, list and analytics | One investigation context across screens |
| Next | VIIRS Nightfire (licence permitting), GEM trackers, CEA list | Stronger flare and industrial attribution |
| Later | Daily intelligence brief, multi-event correlation | Operational reporting |
| Later | Team workspaces, comments, SSO/MFA, shared rate limiter | Collaboration and security at scale |
| Later | Expo native app on the shared `src/lib` | Native notifications and offline sync |
| Later | Model drift and calibration monitoring | ML operations |
