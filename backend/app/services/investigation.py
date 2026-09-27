"""Investigation workspace: the evidence stages of one event, their availability, the event timeline, comparison
records and similarity reasons.

Everything here is computed from the stored investigation bundle (repositories.events.get_bundle): no provider is
called and nothing is inferred beyond what the bundle holds. Missing evidence is reported as missing with the reason
(not requested, pending, no data, failed), never as a negative finding.

Knowledge types, shown wherever they matter:
- observed: retrieved directly from a provider or the database (FIRMS pixels, weather values, scenes);
- derived: calculated from observed data (clustering, persistence, NDVI/NBR change, distances);
- inferred: an interpretation by rules or a model (attribution, classification, confidence);
- analyst: an explicit human decision.

Availability itself is defined once, in services.evidence_rules, and shared with alerts and analytics.
`completeness` counts evidence stages that are available. It is evidence availability, not confidence, and it says
nothing about which interpretation is correct.
"""
from datetime import datetime, timedelta

from app.services.evidence_rules import RULES, STAGE_KEYS  # noqa: F401  (STAGE_KEYS re-exported; availability is defined there)

STATES = ("available", "pending", "no_data", "not_requested", "failed", "review")
STATE_LABELS = {"available": "Available", "pending": "Pending", "no_data": "No data", "not_requested": "Not requested",
                "failed": "Failed", "review": "Requires analyst review"}
CONFIRMED_STATES = ("CONFIRMED", "ANALYST_CONFIRMED", "ANALYST_REJECTED", "ANALYST_REVIEWED")


def _pending(ev: dict, kind: str, step: str | None = None) -> dict | None:
    """The latest queued/running job of `kind` covering `step` (a full enrichment covers every step)."""
    jobs = [j for j in ev.get("jobs") or [] if j["kind"] == kind and (step is None or not j["steps"] or step in j["steps"])]
    jobs.sort(key=lambda j: j["created_at"], reverse=True)
    return jobs[0] if jobs and jobs[0]["status"] in ("queued", "running") else None


def _failed_job(ev: dict, kind: str, step: str | None, recorded_at: str | None) -> dict | None:
    jobs = [j for j in ev.get("jobs") or [] if j["kind"] == kind and (step is None or not j["steps"] or step in j["steps"])]
    jobs.sort(key=lambda j: j["created_at"], reverse=True)
    if not jobs or jobs[0]["status"] != "failed":
        return None
    finished = jobs[0]["finished_at"] or jobs[0]["created_at"]
    if recorded_at and str(finished) <= str(recorded_at):
        return None
    return jobs[0]


def _step_state(ev: dict, step: str, has_value: bool) -> tuple[str, str | None]:
    """Available / pending / no data / failed / not requested for an enrichment step, and the reason when not available."""
    state = (ev.get("enrichment_state") or {}).get(step) or {}
    if has_value:
        return "available", None
    if _pending(ev, "enrich_event", step):
        return "pending", "Retrieval is queued or running."
    job = _failed_job(ev, "enrich_event", step, state.get("at"))
    if job:
        return "failed", f"The retrieval job did not complete ({job.get('error_type') or 'error'})."
    if state.get("status") == "failed":
        return "failed", f"Provider failure ({(state.get('category') or 'error').replace('_', ' ')})."
    if state.get("status") in ("ok", "no_data"):
        return "no_data", "The provider answered without data for this event."
    return "not_requested", "Not retrieved for this event yet."


def _fmt(v, nd=1, unit=""):
    return "—" if v is None else f"{v:.{nd}f}{unit}"


def stages(ev: dict, available: dict[str, bool]) -> list[dict]:
    """The 13 evidence stages of an event, from the thermal detection to its current status.

    `available` comes from evidence_rules.availability() (the one definition shared with alerts and analytics): a stage
    is "available" exactly when that rule says so. For the others this function explains why (pending, no data, not
    requested, failed, requires analyst review) from the event's recorded state; it never upgrades them to available."""
    es = ev.get("enrichment_state") or {}
    links = ev.get("facilities") or []
    top = next((f for f in links if f.get("rank") == 1), links[0] if links else None)
    pm = ev.get("persistence_metrics")
    lc = ev.get("landcover")
    w = (ev.get("weather") or [None])[0]
    scenes = ev.get("satellite") or []
    ia = ev.get("imagery_analysis")
    readiness = ev.get("imagery_readiness") or {}
    cls = ev.get("classification_current")
    preds = ev.get("predictions") or []
    explained = [p for p in preds if p.get("explanation")]
    pred = next((p for p in explained if cls and p["model_version_id"] == cls.get("primary_model_id")), explained[0] if explained else None)
    explanation = (pred or {}).get("explanation")
    reviews = ev.get("reviews") or []
    osm = es.get("osm") or {}
    titles = {r.key: r.title for r in RULES}
    out: list[dict] = []

    def add(key, state, value, *, detail=None, source, at=None, contributes, limitation, knowledge, reason=None):
        # the shared rule is authoritative for availability in both directions
        if available.get(key) and state != "available":
            state, reason = "available", None
        elif not available.get(key) and state == "available":
            state = "no_data"
        out.append({"key": key, "title": titles[key], "state": state, "state_label": STATE_LABELS[state], "value": value,
                    "detail": detail, "reason": reason, "source": source, "at": at, "contributes": contributes,
                    "limitation": limitation, "knowledge": knowledge})

    add("detection", "available" if available["detection"] else "no_data",
        f"{ev.get('observation_count', 0)} FIRMS detection(s) from {ev.get('sensor_count', 0)} platform(s); peak FRP {_fmt(ev.get('frp_max'), 1, ' MW')}",
        detail=", ".join(ev.get("sensors") or []), source="NASA FIRMS (MODIS / VIIRS active fire)", at=ev.get("last_detected"),
        contributes="Heat was observed at this place and time.",
        limitation="A detection alone does not say what caused the heat; pixels are 375 m to 1 km.", knowledge="observed")
    add("clustering", "available" if available["clustering"] else "pending",
        f"{ev.get('observation_count', 0)} detection(s) grouped over {ev.get('days_active', 0)} active day(s)",
        reason=None if available["clustering"] else "Waiting for the processing pipeline.",
        source=f"ThermalTrace processing {ev.get('processing_version') or ''}".strip(), at=ev.get("processed_at") or ev.get("created_at"),
        contributes="Turns nearby pixels in space and time into one event that can be analysed and reviewed.",
        limitation="Two separate sources close together can be grouped into one event.", knowledge="derived")
    add("persistence", "available" if available["persistence"] else "pending",
        f"{ev.get('persistence_class') or '—'}: active on {pm.get('active_days')} of {pm.get('span_days')} day(s)" if pm else "Not computed yet",
        detail=(pm or {}).get("rationale"), reason=None if available["persistence"] else "Computed when the event is processed.",
        source="Derived from the event's daily FIRMS observations", at=ev.get("last_detected"),
        contributes="Repeated detections over days suggest sustained activity; a single detection is an isolated observation.",
        limitation="Satellite revisit, cloud and night/day coverage limit how often heat can be seen.", knowledge="derived")

    fac_state, fac_reason = _step_state(ev, "osm", False)
    within2 = sum(1 for f in links if f["distance_m"] <= 2000)
    add("facility_proximity", "available" if available["facility_proximity"] else fac_state,
        (f"{len(links)} mapped facilit{'y' if len(links) == 1 else 'ies'} within 10 km ({within2} within 2 km); nearest "
         f"{top['name'] or 'unnamed'} at {top['distance_m']:.0f} m" if links
         else "No mapped facility within 10 km" if osm.get("status") == "ok" else "Not checked yet"),
        reason=fac_reason, source="OpenStreetMap, WRI GPPD, Global Energy Monitor, CEA",
        at=(links[0].get("computed_at") if links else None) or osm.get("at"),
        contributes="Places the heat relative to mapped industrial sites (2 km rule threshold, 10 km search radius).",
        limitation="Facility mapping is incomplete; an unmapped source cannot be found.", knowledge="derived")
    attr_state, attr_reason = (("no_data", "No mapped facility within the search radius.") if osm.get("status") == "ok"
                               else (fac_state, fac_reason))
    add("facility_attribution", "available" if available["facility_attribution"] else attr_state,
        f"{top['name'] or 'Unnamed'} ranked #{top['rank']}, attribution score {top['attribution_score']:.2f}" if top else "No facility attributed",
        detail=f"{top['facility_type'].replace('_', ' ')}, {top['distance_m']:.0f} m" if top else None, reason=attr_reason,
        source="Distance-decay attribution over mapped facilities", at=(top or {}).get("computed_at") or osm.get("at"),
        contributes="The facility most consistent with the location of the heat.",
        limitation="Attribution is supporting evidence from proximity; it does not prove the facility caused the heat.",
        knowledge="inferred")

    st, why = _step_state(ev, "landcover", available["landcover"])
    top_lc = sorted((lc or {}).get("fractions", {}).items(), key=lambda kv: -kv[1])[:2]
    add("landcover", st, " · ".join(f"{k.replace('_', ' ')} {v:.0%}" for k, v in top_lc) if lc else STATE_LABELS[st], reason=why,
        source="ESA WorldCover 10 m (2021)", at=(lc or {}).get("retrieved_at") or (es.get("landcover") or {}).get("at"),
        contributes="Context: cropland is consistent with agricultural burning, built-up or bare ground with industry.",
        limitation="2021 product; land use may have changed. Context only, it does not decide the classification.",
        knowledge="observed")

    st, why = _step_state(ev, "weather", available["weather"])
    add("weather", st,
        (f"{w.get('condition') or '—'}, {_fmt(w.get('temperature_c'), 1, ' °C')}, wind {_fmt(w.get('wind_speed_ms'), 1, ' m/s')}"
         if w else STATE_LABELS[st]), reason=why, detail=(w or {}).get("dataset"), source="Open-Meteo (ERA5 reanalysis / recent hourly model)",
        at=(w or {}).get("retrieved_at") or (es.get("weather") or {}).get("at"),
        contributes="Environmental context around the last detection (wind, temperature, precipitation).",
        limitation="Context only; weather does not show what caused the heat.", knowledge="observed")

    st, why = _step_state(ev, "satellite", available["satellite"])
    sat_state = es.get("satellite") or {}
    if st == "no_data":
        why = f"No scene under {sat_state.get('max_cloud', 60):.0f}% cloud in the searched window."
    add("satellite", st,
        (f"{len(scenes)} Sentinel-2 L2A scene(s): {sum(1 for s in scenes if s['relation'] == 'before')} before, "
         f"{sum(1 for s in scenes if s['relation'] == 'after')} after" if scenes else
         "No suitable Sentinel-2 scene" if st == "no_data" else STATE_LABELS[st]),
        reason=why, source="Copernicus Sentinel-2 L2A via Element84 Earth Search", at=sat_state.get("at"),
        contributes="Scenes allow visual inspection and before/after comparison of the surface.",
        limitation="Scene availability depends on revisit and cloud; a scene list alone confirms nothing.", knowledge="observed")

    if available["spectral"]:
        d = (ia or {}).get("deltas") or {}
        st, why, value = "available", None, (f"NDVI change {d.get('ndvi', 0):+.2f}, NBR change {d.get('nbr', 0):+.2f}: "
                                            f"{((ia or {}).get('finding') or '').replace('_', ' ')}")
    else:
        if _pending(ev, "imagery_analysis"):
            st, why = "pending", "Computation is queued or running."
        elif _failed_job(ev, "imagery_analysis", None, (ia or {}).get("retrieved_at")):
            st, why = "failed", "The computation job did not complete."
        elif ia and ia.get("status") == "failed":
            st, why = "failed", ia.get("reason")  # the provider could not be read: never reported as no data
        elif ia:
            st, why = "no_data", ia.get("reason")
        else:
            st, why = "not_requested", readiness.get("reason") or "Not computed for this event yet."
        value = STATE_LABELS[st]
    add("spectral", st, value, reason=why, source="Sentinel-2 band windows (1 km, cloud-masked)", at=(ia or {}).get("retrieved_at"),
        contributes="A drop in both indices is consistent with burned vegetation.",
        limitation="Needs a clear scene before and after the event; consistent with burning, not proof; no change does not rule out a fire.",
        knowledge="derived")

    add("classification", "available" if available["classification"] else "pending",
        (f"{ev['classification'].replace('_', ' ')} · {(ev.get('confidence_state') or '').replace('_', ' ').capitalize()} "
         f"({_fmt(ev.get('confidence_score'), 2)})" if ev.get("classification") else "Not classified yet"),
        reason=None if available["classification"] else "Classified when the event is processed.",
        source=(cls or {}).get("primary_model_id") or "rule cascade", at=(cls or {}).get("created_at"),
        contributes="The explanation most consistent with the available evidence.",
        limitation="An automated interpretation, not a verified fact. Confidence reflects supporting evidence, not a probability.",
        knowledge="inferred")
    add("explainability", "available" if available["explainability"] else "no_data",
        ((f"SHAP contributions for {len(explanation.get('contributions', []))} feature(s)" if explanation.get("kind") == "shap"
          else f"Rule trace, {len(explanation.get('trace', []))} step(s)") if explanation else "No explanation recorded"),
        reason=None if available["explainability"] else "No model output with an explanation is stored for this event.",
        source="SHAP (trained model)" if (explanation or {}).get("kind") == "shap" else "Rule cascade trace",
        at=(pred or {}).get("created_at"),
        contributes="Shows which features or rules drove the automated output.",
        limitation="SHAP shows how features contributed to the model output. It does not establish causation.",
        knowledge="inferred")
    last = reviews[0] if reviews else None
    add("review", "available" if available["review"] else "review",
        (f"{last['decision'].replace('_', ' ')}{' by ' + last['reviewer'] if last.get('reviewer') else ''}" if last
         else "No analyst decision yet"), detail=(last or {}).get("notes"), source="Analyst review (audited)",
        at=(last or {}).get("created_at"), contributes="A human decision on the automated interpretation.",
        limitation="Reviews reflect the evidence available to the analyst at the time.", knowledge="analyst")
    disp = ev.get("display_state") or ev.get("confidence_state")
    add("final_status", "available" if available["final_status"] else "review",
        (disp or "").replace("_", " ").capitalize(), source="Classification state and review status",
        at=(last or {}).get("created_at") or (cls or {}).get("created_at"),
        contributes="Whether the interpretation has been confirmed, rejected or closed as reviewed.",
        limitation="Confirmed only after imagery confirmation or analyst review.", knowledge="analyst" if last else "inferred")
    return out


def completeness(st: list[dict]) -> dict:
    counts = {s: 0 for s in STATES}
    for s in st:
        counts[s["state"]] += 1
    return {"available": counts["available"], "total": len(st), "by_state": counts,
            "note": "Evidence availability: how many stages have evidence. It is not a confidence score."}


def freshness(ev: dict) -> dict:
    """Distinct timestamps, never conflated: when heat was last observed, when evidence was last refreshed by a provider
    or computation, and when the event record itself last changed (reprocessing also changes it)."""
    es = ev.get("enrichment_state") or {}
    refreshed = [s.get("at") for s in es.values() if isinstance(s, dict) and s.get("at")]
    refreshed += [x for x in ((ev.get("landcover") or {}).get("retrieved_at"), (ev.get("imagery_analysis") or {}).get("retrieved_at")) if x]
    refreshed += [w["retrieved_at"] for w in ev.get("weather") or [] if w.get("retrieved_at")]
    refreshed += [s["retrieved_at"] for s in ev.get("satellite") or [] if s.get("retrieved_at")]
    return {"latest_observation_at": ev.get("last_detected"),
            "latest_evidence_refresh_at": max(refreshed, key=lambda v: _ts(v)) if refreshed else None,
            "processed_at": ev.get("processed_at"), "record_updated_at": ev.get("updated_at")}


def _ts(v) -> datetime:
    return v if isinstance(v, datetime) else datetime.fromisoformat(str(v).replace("Z", "+00:00"))


def timeline(ev: dict) -> list[dict]:
    """What happened to the event, in order, from stored timestamps only. Gaps between detection days are shown
    explicitly; nothing is interpolated."""
    items: list[dict] = []

    def add(at, kind, label, detail=None, knowledge="observed"):
        if at is not None:
            items.append({"at": at, "kind": kind, "label": label, "detail": detail, "knowledge": knowledge})

    dets = ev.get("detections") or []
    if dets:
        d0 = dets[0]
        add(d0["acq_datetime"], "first_seen", "First detection", f"{d0['satellite']} ({d0['dataset']}), FRP {_fmt(d0.get('frp'), 1, ' MW')}")
    else:
        add(ev.get("first_detected"), "first_seen", "First detection")
    obs = ev.get("observations") or []
    prev_day = None
    for o in obs:
        day = datetime.fromisoformat(str(o["obs_date"]))
        if prev_day is not None and (day - prev_day).days > 1:
            add(o["first_at"] - timedelta(seconds=1) if isinstance(o["first_at"], datetime) else o["first_at"], "gap",
                f"No detections for {(day - prev_day).days - 1} day(s)", "Heat was not observed on these days (cloud, revisit or inactivity).",
                "derived")
        add(o["first_at"], "observation", f"{o['detection_count']} detection(s)",
            f"{', '.join(o['sensors'])}; peak FRP {_fmt(o.get('frp_max'), 1, ' MW')}")
        prev_day = day
    add(ev.get("created_at"), "clustered", "Event created by clustering", f"Public id {ev.get('public_id')}", "derived")
    links = ev.get("facilities") or []
    if links and links[0].get("computed_at"):
        top = links[0]
        add(top["computed_at"], "facility", "Facility proximity established",
            f"{top['name'] or 'Unnamed'} at {top['distance_m']:.0f} m (rank #{top['rank']})", "derived")
    es = ev.get("enrichment_state") or {}
    for step, label in (("osm", "Infrastructure and land use checked"), ("landcover", "Land cover retrieved"),
                        ("weather", "Weather retrieved"), ("satellite", "Sentinel-2 searched"), ("geocode", "Place geocoded")):
        s = es.get(step)
        if s:
            outcome = {"ok": "", "no_data": " (no data)", "failed": " (provider failure)"}.get(s.get("status"), "")
            # failures show their category, never the raw provider message (which may contain URLs)
            detail = (s.get("category") or "error").replace("_", " ") if s.get("status") == "failed" else s.get("detail")
            add(s.get("at"), "enrichment", label + outcome, detail, "observed")
    for s in ev.get("satellite") or []:
        add(s["acquired_at"], "satellite", f"Sentinel-2 scene acquired ({s['relation']})",
            f"{s.get('platform') or 'Sentinel-2'}, {_fmt(s.get('cloud_cover'), 0, '% cloud')}")
    for w in ev.get("weather") or []:
        add(w["observed_at"], "weather", "Weather observation", f"{w.get('condition') or '—'}, wind {_fmt(w.get('wind_speed_ms'), 1, ' m/s')}")
    ia = ev.get("imagery_analysis")
    if ia:
        add(ia.get("retrieved_at"), "spectral", "NDVI / NBR analysis" + {"ok": "", "failed": " failed"}.get(ia["status"], " unavailable"),
            (ia.get("finding") or ia.get("reason") or "").replace("_", " "), "derived")
    for c in reversed((ev.get("classification_history") or [])[:8]):
        add(c["created_at"], "classification", f"Classified: {c['source_class']} / {c['persistence_class']}",
            f"{c['confidence_state']} ({c['confidence_score']:.2f}) by {c['primary_model_id']}", "inferred")
    for r in ev.get("reviews") or []:
        change = f"{r.get('previous_status') or '—'} → {r.get('new_status') or '—'}" if r.get("new_status") else ""
        add(r["created_at"], "review", f"Analyst: {r['decision'].replace('_', ' ')}",
            " · ".join(x for x in (r.get("reviewer"), change, (r.get("notes") or "")[:140]) if x), "analyst")
    for n in ev.get("notes") or []:
        add(n["created_at"], "note", "Analyst note" if n["kind"] == "note" else "Evidence link", (n.get("body") or "")[:140], "analyst")
    for a in ev.get("alerts") or []:
        add(a["triggered_at"], "alert", f"Alert ({a['severity']})", a["rule_name"], "derived")
    add(ev.get("last_detected"), "latest", "Latest detection")
    return sorted(items, key=lambda i: _ts(i["at"]))


def compare_record(ev: dict) -> dict:
    """The facts of one event side by side with another: no ranking, no score."""
    top = (ev.get("facilities") or [None])[0]
    lc = ev.get("landcover")
    w = (ev.get("weather") or [None])[0]
    ia = ev.get("imagery_analysis")
    preds = ev.get("predictions") or []
    shap = next((p["explanation"] for p in preds if (p.get("explanation") or {}).get("kind") == "shap"), None)
    dets = ev.get("detections") or []
    bright = [d["brightness"] for d in dets if d.get("brightness") is not None]
    st = (ev.get("evidence_stages") or {}).get("stages") or []
    return {
        "id": ev["id"], "public_id": ev["public_id"], "latitude": ev["latitude"], "longitude": ev["longitude"],
        "place": ev.get("place_name") or ev.get("admin_district"), "state": ev.get("admin_state") or ev.get("place_admin1"),
        "first_detected": ev["first_detected"], "last_detected": ev["last_detected"],
        "classification": ev.get("classification"), "confidence_state": ev.get("confidence_state"),
        "confidence_score": ev.get("confidence_score"), "display_state": ev.get("display_state"), "priority_score": ev.get("priority_score"),
        "frp_max": ev.get("frp_max"), "frp_mean": ev.get("frp_mean"), "brightness_max": max(bright) if bright else None,
        "observation_count": ev.get("observation_count"), "persistence_class": ev.get("persistence_class"),
        "days_active": ev.get("days_active"),
        "facility": {"name": top["name"], "type": top["facility_type"], "distance_m": top["distance_m"], "rank": top["rank"],
                     "attribution_score": top["attribution_score"]} if top else None,
        "landcover": {"dominant": lc["dominant"], "share": (lc.get("fractions") or {}).get(lc["dominant"])} if lc else None,
        "weather": {k: w.get(k) for k in ("condition", "temperature_c", "wind_speed_ms", "wind_direction_deg", "observed_at")} if w else None,
        "imagery": {"scenes": len(ev.get("satellite") or []), "spectral_status": (ia or {}).get("status"),
                    "finding": (ia or {}).get("finding"), "deltas": (ia or {}).get("deltas"), "reason": (ia or {}).get("reason")},
        "shap_top": sorted((shap or {}).get("contributions", []), key=lambda c: -abs(c.get("contribution", 0)))[:5] if shap else None,
        "review_status": ev.get("review_status"),
        "completeness": completeness(st) if st else (ev.get("evidence_stages") or {}).get("completeness"),
    }


_FP_LABELS = {"intensity": "thermal intensity", "persistence": "persistence", "facility_proximity": "distance to the nearest facility",
              "night_share": "share of night-time detections", "sensor_agreement": "multi-sensor agreement"}


def similarity_reasons(me: dict, other: dict) -> list[str]:
    """Why a fingerprint neighbour is considered similar, from the dimensions that actually match."""
    a, b = me.get("fingerprint") or {}, other.get("fingerprint") or {}
    out = []
    for dim, label in _FP_LABELS.items():
        try:
            if a.get(dim) is not None and b.get(dim) is not None and abs(float(a[dim]) - float(b[dim])) <= 0.1:
                out.append(f"similar {label}")
        except (TypeError, ValueError):
            continue
    if a.get("facility_type") and a.get("facility_type") == b.get("facility_type"):
        out.append(f"same nearest facility type ({str(a['facility_type']).replace('_', ' ')})")
    if me.get("persistence_class") and me.get("persistence_class") == other.get("persistence_class"):
        out.append(f"same persistence class ({me['persistence_class']})")
    if me.get("classification") and me.get("classification") == other.get("classification"):
        out.append("same automated classification (not a shared cause)")
    return out or ["closest overall thermal fingerprint"]
