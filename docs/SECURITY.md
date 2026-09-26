# Security

## Fixed from the donor backend (see PROJECT_HISTORY.md)

| Issue | Resolution |
|---|---|
| Hard-coded backdoor login (a fixed email and password, redacted here) and a `user_id=99999` token bypass in sih-fire-backend | Removed. No accounts are hard-coded and no code path skips the DB and session check. **The credential is public in that repo's git history. Treat it as compromised anywhere it was reused.** |
| Self-assignable roles at signup (`role: "admin"`) | Removed. There is no public signup. Only admins create users or change roles (`/admin/users`). Admins cannot change their own role or deactivate themselves. |
| Default JWT secret committed | `SECRET_KEY` has no usable default outside development. Staging and production refuse to start with a missing, dev or short (< 32 char) key. |
| `CORS *` with credentials | Explicit origin list (`CORS_ORIGINS`), `allow_credentials=false` (bearer tokens), explicit methods and headers. |
| LLM API key in a URL query string | LLM calls removed entirely. The FIRMS MAP_KEY sits in URL paths (required by FIRMS), so it is redacted from logs and from stored `source_ref`. |
| Raw exception text returned to clients | Structured errors with stable codes. Details are logged server-side with the request id. |

## Controls in place

- **Authentication**:
  - bcrypt (cost 12) password hashes.
  - Constant-time handling of unknown emails.
  - HS256 JWTs with issuer, expiry and `jti`.
  - Server-side `user_sessions`: logout and deactivation revoke immediately.
- **Password policy**: at least 12 characters, mixing at least three character classes.
- **Authorization**: role hierarchy enforced by FastAPI dependencies on every route. Object ownership is checked for alert rules, watchlists and alerts.
- **Rate limiting**: fixed window, 600/min per session token (hashed; per client IP for anonymous traffic) and 10/min per IP on login. This limiter runs inside each API process. Behind multiple replicas, also rate-limit at the gateway or ingress.
- **Input validation**: Pydantic schemas with bounds (bbox, limits, enums, URL schemes for evidence links). SQL is always parameterised; the ORM and `text()` binds are used everywhere, with no string-built values.
- **File access**: registry imports are confined to `DATASETS_DIR`. Report downloads are confined to `REPORT_STORAGE_DIR`.
- **Audit log**: logins (including failures), reviews, notes, assignments, rule changes, job triggers, user and role changes, report creation, and model activation. It is visible to admins.
- **Headers**: `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options: DENY` on the API and the static web server.
- **Secrets**: none in the repository. `.env*` files are git-ignored (only `*.example` files are tracked). No users are seeded: accounts are created with `python -m app.cli create-user`, which reads the password from `THERMALTRACE_PASSWORD` or a prompt. Keep any local password notes outside the repository. E2E tests read `E2E_EMAIL` / `E2E_PASSWORD` from the environment.
- **Containers**: the API image runs as a non-root user (uid 10001).
- **Supply chain**: CI runs `pip-audit` and `npm audit` in report mode.
- **Test isolation**: `tests/conftest.py` blanks every provider credential (FIRMS, Copernicus, SMTP, VAPID, Sentry) before the app loads settings, so a developer's local `.env` can never make the test suite send email or call keyed APIs. A test enforces this.
- **Fail-closed images**: the API image defaults to `ENVIRONMENT=production` and refuses to start with development secrets, the development database password, or localhost-only CORS. CI checks that the image refuses to start with defaults.

## Guided exploration (demo sessions)

`EXPLORE_MODE_ENABLED` adds credential-free, read-only demo sessions. Every non-GET request from them is refused
server-side, quota-consuming reads are refused, personal data is masked, sessions are short-lived and audited, and demo
accounts have no usable password. Details: `GUIDED_TOURS.md`. Keep it off unless a public demo is intended.

## Known gaps

- Tokens are stored in `localStorage`. This is standard for a bearer-token SPA plus PWA, but it is exposed to XSS. The mitigations are React's escaping, no `dangerouslySetInnerHTML` of user input (map popups escape names), and a strict CSP recommended at the edge.
- There is no MFA or SSO yet (roadmap).
- There is no automatic account lockout beyond rate limiting.

## Audit (2026-09-25)

### Method

- Repository-wide search of Python, TS/TSX, JS, YAML and JSON sources (excluding `node_modules`, `.venv`, `.git`, lockfiles) for:
  - hard-coded credentials, keys, tokens and passwords;
  - JWT secrets;
  - the known backdoor identifiers (`99999`, the donor's hard-coded account);
  - `eval`/`exec`, `subprocess`/`shell=True`/`os.system`;
  - `dangerouslySetInnerHTML`;
  - wildcard CORS.
- Inspection of every `.env*` file, with values redacted during review and never printed.
- Manual review of authentication, authorisation, file I/O paths, outbound URL construction (SSRF) and SQL construction in production.

### Findings

| # | Codebase | Finding | Severity | Resolution |
|---|---|---|---|---|
| 1 | sih-fire-backend | Hard-coded backdoor login, and a `user_id=99999` token bypass (`routers/auth.py`, `oauth2.py`) | Critical | Never migrated. The credential stays public in that repository's history; **rotate it anywhere it was reused.** |
| 2 | sih-fire-backend | `allow_origins=["*"]` with credentials; self-assignable roles; default JWT secret | High | Not migrated. Production uses explicit origins, admin-only roles, and a required secret. |
| 3 | Production | Rate limiting keyed per client IP: analysts behind one NAT shared a 240/min bucket (found during E2E) | Medium (availability) | **Fixed.** Keyed per session token (hashed), IP for anonymous traffic; login stays per IP. Test `test_rate_limit_is_per_token_not_per_ip`. |
| 4 | Production | Enrichment held a DB transaction open during slow provider calls ("idle in transaction") | Low (resource) | **Fixed.** Commit before provider calls. |
| 5 | Production | New training-dataset export exposes reviewer emails | Info | Supervisor or above only. Every export is audited (`ml.training_dataset.export`). |
| 6 | Production | No secrets, backdoors, debug routes or wildcard CORS found in tracked files | — | Verified before each commit (`git diff --cached` scan). |
| 7 | Production | `pip-audit`: starlette 0.41.3 (multiple advisories), **lightgbm 4.5.0 (PYSEC-2024-231, remote code execution)**, pyjwt 2.10.1, python-multipart 0.0.20, pytest 8.3.4 | High (critical for LightGBM) | **Fixed.** fastapi 0.141.1 + starlette 1.3.1, lightgbm 4.6.0, pyjwt 2.13.0, python-multipart 0.0.31, pytest 9.0.3. `pip-audit`: no known vulnerabilities. |
| 8 | Production | `npm audit`: maplibre-gl ≤ 6.4.0 (critical), react-router 6.x (moderate) | Critical | **Fixed.** maplibre-gl 6.11.2 and react-router-dom 7.18.4. `npm audit --omit=dev`: 0 vulnerabilities. Verified end to end (see BUG_FIXES #21–23). |

### Review checklist

| Area | Result |
|---|---|
| Authentication bypass / backdoors | None. Every protected route requires a valid JWT and a non-revoked session row. |
| Privilege escalation | Roles are set only via `/admin/users` (admin). Admins cannot change their own role or deactivate themselves. No public signup. |
| SQL injection | All SQL is parameterised (ORM or `text()` binds). Dynamic `ORDER BY` uses an allow-list (`SORTS`). `bucket` in trends is regex-validated (`day\|week\|month`). |
| Path traversal | Registry imports are confined to `DATASETS_DIR`; report downloads to `REPORT_STORAGE_DIR` (both `resolve()` + parent checks). |
| SSRF | Outbound hosts come only from configuration (FIRMS, Overpass, STAC, Open-Meteo, Nominatim, CDSE). User input never selects a URL. Evidence links are stored and displayed (`http(s)` only, `rel="noopener noreferrer"`), never fetched. |
| File upload | None (dataset files are placed on disk by operators). |
| XSS | React escaping. The only HTML string is a map popup, and it escapes facility names. |
| Secrets in repo | None. `.env*` is ignored except `*.example`. No users are seeded. |
| CORS | Explicit origin list, `allow_credentials=false`. |
| Logging | Keys are redacted from URLs in logs and from the stored `source_ref`. |
