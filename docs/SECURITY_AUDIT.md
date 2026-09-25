# Security audit — all source codebases (2026-09-25)

Scope: Production (`D:\Projects\ThermalTrace`), Prototype, Demo, and the donor `sih-fire-backend`. Controls in force are described in `SECURITY.md`.

## Method

- Repository-wide search of Python, TS/TSX, JS, YAML and JSON sources (excluding `node_modules`, `.next`, `.venv`, `.git`, lockfiles) for:
  - hard-coded credentials, keys, tokens and passwords;
  - JWT secrets;
  - the known backdoor identifiers (`99999`, the donor's hard-coded account);
  - `eval`/`exec`, `subprocess`/`shell=True`/`os.system`;
  - `dangerouslySetInnerHTML`;
  - wildcard CORS.
- Inspection of every `.env*` file, with values redacted during review and never printed.
- Manual review of authentication, authorisation, file I/O paths, outbound URL construction (SSRF) and SQL construction in production.

## Findings

| # | Codebase | Finding | Severity | Resolution |
|---|---|---|---|---|
| 1 | sih-fire-backend | Hard-coded backdoor login, and a `user_id=99999` token bypass (`routers/auth.py`, `oauth2.py`) | Critical | Never migrated. The credential stays public in that repository's history; **rotate it anywhere it was reused.** |
| 2 | sih-fire-backend | `allow_origins=["*"]` with credentials; self-assignable roles; default JWT secret | High | Not migrated. Production uses explicit origins, admin-only roles, and a required secret. |
| 3 | Demo | `.env` present with a dev-only DB password identical to `.env.example`; `FIRMS_MAP_KEY` empty | Info | No secret. Not copied. |
| 4 | Demo | Minified `frontend/dist` matches `exec(`/`eval`-like tokens | False positive | Third-party vendor bundle (React, MapLibre). Not migrated. |
| 5 | Prototype | `.env.local` holds only `DEMO_MODE` and the map style; no secrets. Next.js route handlers have no auth | Low | Not migrated. Production endpoints require JWT plus role guards. |
| 6 | Production | Rate limiting keyed per client IP: analysts behind one NAT shared a 240/min bucket (found during E2E) | Medium (availability) | **Fixed.** Keyed per session token (hashed), IP for anonymous traffic; login stays per IP. Test `test_rate_limit_is_per_token_not_per_ip`. |
| 7 | Production | Enrichment held a DB transaction open during slow provider calls ("idle in transaction") | Low (resource) | **Fixed.** Commit before provider calls. |
| 8 | Production | New training-dataset export exposes reviewer emails | Info | Supervisor or above only. Every export is audited (`ml.training_dataset.export`). |
| 9 | Production | No secrets, backdoors, debug routes or wildcard CORS found in tracked files | — | Verified before each commit (`git diff --cached` scan). |
| 10 | Production | `pip-audit`: starlette 0.41.3 (multiple advisories), **lightgbm 4.5.0 (PYSEC-2024-231, remote code execution)**, pyjwt 2.10.1, python-multipart 0.0.20, pytest 8.3.4 | High (critical for LightGBM) | **Fixed.** fastapi 0.141.1 + starlette 1.3.1, lightgbm 4.6.0, pyjwt 2.13.0, python-multipart 0.0.31, pytest 9.0.3. `pip-audit`: no known vulnerabilities. |
| 11 | Production | `npm audit`: maplibre-gl ≤ 6.4.0 (critical), react-router 6.x (moderate) | Critical | **Fixed.** maplibre-gl 6.11.2 and react-router-dom 7.18.4. `npm audit --omit=dev`: 0 vulnerabilities. Verified end to end (see BUG_FIXES #21–23). |

## Production review checklist

| Area | Result |
|---|---|
| Authentication bypass / backdoors | None. Every protected route requires a valid JWT and a non-revoked session row. |
| Privilege escalation | Roles are set only via `/admin/users` (admin). Admins cannot change their own role or deactivate themselves. No public signup. |
| SQL injection | All SQL is parameterised (ORM or `text()` binds). Dynamic `ORDER BY` uses an allow-list (`SORTS`). `bucket` in trends is regex-validated (`day\|week\|month`). |
| Path traversal | Registry imports are confined to `DATASETS_DIR`; report downloads to `REPORT_STORAGE_DIR` (both `resolve()` + parent checks). |
| SSRF | Outbound hosts come only from configuration (FIRMS, Overpass, STAC, Open-Meteo, Nominatim, CDSE). User input never selects a URL. Evidence links are stored and displayed (`http(s)` only, `rel="noopener noreferrer"`), never fetched. |
| File upload | None (dataset files are placed on disk by operators). |
| XSS | React escaping. The only HTML string is a map popup, and it escapes facility names. |
| Secrets in repo | None. `.env*` is ignored except `*.example`. Dev credentials are generated into git-ignored `backend/var/`. |
| CORS | Explicit origin list, `allow_credentials=false`. |
| Logging | Keys are redacted from URLs in logs and from the stored `source_ref`. |

## Residual risks

- Tokens are stored in `localStorage` (XSS exposure). Mitigations: escaping, no raw HTML, and a CSP recommended at the edge.
- The in-process rate limiter is per replica; use a shared limiter at the gateway for multi-replica deployments.
- No MFA or SSO yet.
