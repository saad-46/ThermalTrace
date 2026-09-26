# Guided exploration ("Explore as Analyst / Admin")

Two entry points on the login page let a first-time visitor (a judge, an evaluator, a new teammate) use the real
application without an account, guided by a step-by-step tour. It is an overlay on the production UI and its real
data, not a separate demo app. Normal sign-in is unchanged.

## Enabling it

`EXPLORE_MODE_ENABLED=true` (off by default; on in `.env.development.example`). When off, the login page does not
show the section and `POST /api/v1/auth/demo` returns 404. `EXPLORE_SESSION_MINUTES` (default 120) sets how long a
session lasts.

## Security model

| Control | Where |
|---|---|
| One system account per role (`analyst`, `admin`), flagged `users.is_demo`, created on first use with an `@thermaltrace.invalid` address and a password hash derived from a random secret that is never stored. Password login is refused for demo accounts. No credential exists anywhere. | `services/explore.py`, `api/v1/auth.py` |
| **Read-only, enforced server-side for every authenticated route**: any non-GET request from a demo session is rejected with `403 demo_read_only`, except logging out. | `core/deps.get_current_user` → `explore.enforce_read_only` |
| Reads with a paid or limited external quota (the Copernicus SWIR render) are refused (`demo_quota_protected`). | same |
| Personal data is masked for demo sessions: e-mail addresses (`a***@domain`) and IP addresses in the user list, audit log and training-dataset export. | `explore.mask_pii` |
| Short-lived sessions, audited (`auth.demo_session`), rate-limited like login, revocable; Exit revokes the session on the server. | `api/v1/auth.py`, `core/middleware.py` |
| Demo accounts never appear in assignment pickers. | `/users/directory` |
| Switching roles ends the current demo session before starting the other one, after an explicit confirmation. | `tour/ExploreBanner.tsx` |

An admin demo session can see admin views (system health, data sources, model versions, audit trail, users) but the
server refuses every change: activation, training, ingestion triggers, user edits.

## Tour architecture (frontend `src/tour/`)

| File | Role |
|---|---|
| `types.ts` | `TourStep`: id, title, body (what it is), optional *why this matters*, *limitation* (always shown), *how it is generated* and *learn more*, glossary terms, `data-tour-id` target, route (may depend on real data), phone overrides, `needsEvent` + fallback text, optional `action` and its `cleanup`. |
| `tours.ts` | The analyst (19 steps, ending with the investigation summary) and admin (14 steps) tours. Wording follows docs/ML.md, DATA_SOURCES.md and GIS.md; the admin tour states what does not exist (no active trained model unless an admin activated one, no imagery-based classifier, no calibrated probabilities, no real-time imagery confirmation). |
| `glossary.ts` | Short definitions (FIRMS, FRP, persistence, NDVI, NBR, SHAP, PostGIS, spatial hold-out, …). |
| `TourProvider.tsx` | State (`thermaltrace_demo_role`, `thermaltrace_tour_progress` in sessionStorage; no credentials), route navigation, and the featured event from `GET /api/v1/events/featured`: the real event carrying the most evidence (facility within 2 km, specific classification, confidence above insufficient, persistence, land cover, Sentinel-2 analysis), then triage priority. The response lists which evidence it has and which is unavailable, and the tour says both. |
| `TourOverlay.tsx` | Non-blocking spotlight (the app stays usable) and the explanation card: a popover on desktop/tablet, a bottom sheet on phones that moves to the top when the target is at the bottom. |
| `target.ts` | Waits for targets with a `MutationObserver` (no fixed sleeps), popover placement that never leaves the viewport. |
| `ExploreBanner.tsx` | "Demo mode · Analyst/Admin" banner: restart tour, switch role, exit. |

**Targets** are stable `data-tour-id` attributes on existing components; a unit test fails if a tour references
one that is not rendered anywhere.

**Failure handling.** A missing target does not break anything: the tour waits up to 15 s while showing
"Loading the next part of the tour…", then shows the explanation without a spotlight and lets the user continue. With
no events ingested, event steps explain that there is no data yet instead of pointing at nothing.

**Accessibility.** Semantic buttons; the card is a labelled, non-modal dialog whose title receives focus on each step;
→ / ← move between steps, Esc closes the tour; progress is text ("Step 4 of 17"); *Learn more* uses `<details>`;
`prefers-reduced-motion` disables spotlight motion and smooth scrolling.

## Tests

- Backend: explore off by default (404), read-only for both roles, PII masking, SWIR quota protection, demo accounts
  cannot log in with a password, logout revokes (`tests/test_integration.py`, `tests/test_units.py`).
- Frontend unit: step ids unique, every target rendered somewhere, glossary keys resolve, banned marketing phrases,
  route/target resolution (desktop, phone, empty database), placement, target waiting (`__tests__/tour.test.tsx`).
- E2E (`e2e/explore.spec.ts`, skipped unless explore mode is enabled): login page, both full tours on desktop, tablet
  and phones at 360/390/430 px, every step checked for horizontal overflow, the card inside the viewport and not
  covering its target; Back/Next/Skip/Restart, keyboard, a review refused in demo mode, explicit role switch with
  privileges checked, exit revoking the session on the server.
