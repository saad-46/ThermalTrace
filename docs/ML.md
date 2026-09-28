# Classification, confidence and explainability

## Taxonomy

Two independent axes are used.

**Source class**: `flare`, `process_heat`, `coal_seam_fire`, `agricultural_burn`, `wildfire`, `industrial_fire`, `other` or `unknown`.

**Persistence**: `transient`, `recurring` or `persistent` (see GIS.md §2).

## Models (`app/ml/`)

| Model | Kind | Role |
|---|---|---|
| `rule-cascade-v1.1` | `RuleCascadeClassifier` (deterministic) | Classifier of record, and the source of weak labels. It produces a readable rule trace. |
| `lgbm-<timestamp>` | `GradientBoostingClassifier` (LightGBM + TreeSHAP) | Trained on adjudicated plus weak labels. When active and at least as confident as the rules, it becomes the primary model. |
| `RemoteSensingClassifier` | Interface only | Extension point for a Sentinel-2 SWIR image model. It is deliberately not registered because no trained image model exists. |

Both models implement `BaseClassifier.predict(features, context) -> Prediction`. Every prediction is stored in `model_predictions` with the model version, label, probability, full probability vector, the exact features used, and its explanation (rule trace or SHAP).

### Rule cascade (summary)

The rules are applied in this order:

1. **Gate 0.** A single detection with FRP < 5 MW → `unknown` (insufficient signal).
2. **Oil and gas within 2 km.** With a recurring or persistent pattern and night share ≥ 40 % → `flare` (p ≤ 0.88). Without night dominance → `process_heat`, capped at 0.5 because this boundary is ambiguous.
3. **Heavy industry within 2 km.** Recurring or persistent → `process_heat` (capped at 0.75). Transient with ≥ 40 MW within 1 km → `industrial_fire` (p = 0.45, always sent to review).
4. **Mine within 3 km** with a recurring pattern → `coal_seam_fire`.
5. **Cropland mapped within 1.5 km** and not persistent → `agricultural_burn` (+0.12 in the Mar–May and Oct–Dec burning seasons). **Forest or scrub** → `wildfire`.
   *Raster fallback (v1.1):* when OSM land use has not been retrieved, ESA WorldCover within 750 m is used instead, but only when one class is a clear majority (≥ 50 %) and built-up area is ≤ 20 %. Probabilities on this path are capped at 0.60, because the product maps 2021 conditions and a 1.5 km window can mix land uses. The trace says which source was used.
6. **Persistent with no context** → `other` ("candidate unmapped industrial source"). Anything else → `unknown`.

### Training (`python -m app.cli train`, or *System health → Train*)

**Lifecycle.** Rules bootstrap labels → analysts adjudicate events → training dataset (exportable) → spatial hold-out evaluation → model card → **an admin decides** whether to activate (audited `model.activate`) → the model can be deactivated at any time (audited `model.deactivate`), which makes the rule cascade the classifier of record again. Training never activates a model by itself.

- **Labels**:
  - Analyst `confirm` or `reclassify` decisions, with weight 3.
  - Rule-cascade outputs with p ≥ 0.55, with weight 1. `unknown` and `other` are never used as labels.
- **Minimums**: 40 rows, and at least 2 classes with 5 or more rows each. Otherwise training refuses.
- **Validation**: a **spatial block split** holds out 20 % of 1° cells, so neighbouring pixels never appear on both sides.
- **Stored with the model version**: macro-F1 on the hold-out, the class counts, the label origins, and this caveat: *"Hold-out labels are mostly weak (rule-derived); this F1 measures agreement with the rule cascade, not accuracy against ground truth."*
- **Independent estimate**: macro-F1 on the **analyst-adjudicated** labels of the held-out blocks only
  (`macro_f1_holdout_analyst`, with `n_test_analyst`). It is the only figure that does not measure agreement with the
  rules; below 10 such labels it is reported as unavailable, with the reason. *System health* shows both.
- **Activation is never automatic**: `train_and_register` has no activation option and the `train_model` job always
  stores the model inactive. Activation (`POST /models/{id}/activate`, admin) records the previously active model;
  both activation and deactivation queue a full re-analysis under their own queue key.
- **Status**: the pipeline is tested end to end (`tests/test_ml.py`: train → save → load → predict → SHAP). On the live database it will train once enrichment has produced enough confidently labelled events, or once analysts have adjudicated events.

### Feature pipeline (`processing/features.py`)

There are 32 named features, each tagged with its origin (FIRMS, derived, facility, land, imagery, weather or calendar). Version 1.1 added four ESA WorldCover shares (`lc_vegetation_frac`, `lc_cropland_frac`, `lc_built_up_frac`, `lc_bare_frac`) and two Sentinel-2 change features (`dndvi`, `dnbr`); all are NaN until measured. The full table is shown in the UI (*System health → Feature pipeline*) and served by `GET /api/v1/models`.

Missing inputs stay **NaN**; nothing is imputed with invented constants. For example, the land-use flags are NaN until OSM has actually been checked.

## Explainability

- **Rules**: an ordered trace of the rules that fired, plus signed contributions for the features involved.
- **LightGBM**: exact TreeSHAP values for the predicted class, top 10 by magnitude, computed by LightGBM itself
  (`predict(..., pred_contrib=True)`). This is the same path-dependent TreeSHAP that `shap.TreeExplainer` returns
  for a LightGBM model (verified identical: maximum difference 0.0 for 2-, 3- and 8-class models), without the
  `shap` package and its numba / llvmlite / pandas stack (~235 MB). `test_tree_shap_rows_are_exact_contributions_
  of_the_predicted_score` checks additivity: contributions plus the expected value equal the raw model score.
- Both the UI and the reports label SHAP as *"model evidence — not causal proof"*.

## Confidence engine (`processing/confidence.py`)

Confidence is a weighted sum. Every component is stored and displayed with its explanation.

| Component | Weight | Meaning |
|---|---|---|
| model_probability | 0.28 | Primary model's probability |
| model_agreement | 0.12 | Rules and GBM agree 1.0, disagree 0.25, no GBM 0.5 |
| context_support | 0.16 | Facility attribution (industrial classes) or land cover (vegetation classes) |
| temporal_consistency | 0.14 | Persistence pattern expected for the label |
| sensor_agreement | 0.10 | 1 platform 0.2 · 2 platforms 0.6 · 3 or more 1.0 |
| satellite | 0.08 | Clear scene 1.0 · cloudy 0.5 · none 0.1 · not searched 0.3 |
| weather | 0.04 | Available or not |
| data_quality | 0.08 | Data-quality score |

**States**:

- `INSUFFICIENT_EVIDENCE` when any of these holds: the label is unknown, data quality is poor, or the score is < 0.40.
- Otherwise `LOW` below 0.55, `MODERATE` below 0.72, and `HIGH` from 0.72.
- **`CONFIRMED`** requires all of: HIGH, 2 or more sensors, consistent persistence, strong context, **and** a passed imagery (SWIR) check. The system therefore never claims confirmation from FIRMS alone.
- Analyst decisions override the displayed state (`ANALYST_CONFIRMED`, `ANALYST_REJECTED`, `ANALYST_REVIEWED` for a review
  closed without confirming or rejecting, `UNDER_REVIEW`). The system state is kept.

**Data quality** is graded excellent, good, limited or poor from seven weighted factors: sensor availability, location precision (pixel footprint), facility coverage, satellite cloud, weather availability, historical depth and source freshness. Each factor stores its reason.

## Triage priority (not a model output, not a risk score)

The analyst queue is ordered by a 0–100 **triage priority** (`processing/priority.py`). It is the sum of five 20-point components:

- thermal intensity (log FRP)
- persistence score
- industrial proximity (attribution score)
- system confidence
- sensor corroboration

Tiers are high (≥ 70), elevated (≥ 50), routine (≥ 30) and low. The breakdown is stored per event and shown as "Why is this prioritised?". It answers *what to look at first*, never *how dangerous*.

## Feedback loop

- Every analyst decision is stored with a snapshot of the system label and confidence at that time (`analyst_reviews`).
- *Analytics → Analyst feedback loop* shows how many adjudicated labels exist, false positives by reason (industrial process heat, agricultural burn, sensor artefact, construction, known static source, sun glint, other), and a system-versus-analyst agreement table.
- Retraining uses adjudicated labels at 3× weight.
- **Export**: `GET /api/v1/ml/training-dataset?format=csv|json` (supervisor or above, audited). One row per decision: event, decision, analyst label, false-positive reason, system label and confidence at review time, model and pipeline version, reviewer, timestamp, and the 26 features as they were when the analyst decided.

## Not implemented (stated plainly)

- **XGBoost.** Only LightGBM is implemented; the presentation's "XGBoost/LightGBM" refers to this family of models.
- **Probability calibration.** Model probabilities are not calibrated (no isotonic or Platt step), and the rule probabilities are expert settings, not frequencies. The confidence score is a documented weighted sum, not a calibrated probability.
- **Model monitoring.** There is no automated drift monitoring. The analyst feedback view (*Analytics → Analyst feedback loop*) shows system-versus-analyst agreement, which is the current manual check.
- **Image classifier.** No trained model uses imagery pixels. Imagery contributes only the measured `dndvi` / `dnbr` features and evidence.
