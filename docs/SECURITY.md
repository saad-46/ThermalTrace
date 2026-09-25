# Security

## Fixed from the source repositories (see REPOSITORY_AUDIT.md)

| Issue | Resolution |
|---|---|
| Hard-coded backdoor login (`rayyan@gmail.com` / `verystrongpass`) and a `user_id=99999` token bypass in sih-fire-backend | Removed. No accounts are hard-coded and no code path skips the DB and session check. **The credential is public in that repo's git history. Treat it as compromised anywhere it was reused.** |
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
- **Rate limiting**: per-IP fixed window, 240/min on the API and 10/min on login. This limiter runs inside each API process. Behind multiple replicas, also rate-limit at the gateway or ingress.
- **Input validation**: Pydantic schemas with bounds (bbox, limits, enums, URL schemes for evidence links). SQL is always parameterised; the ORM and `text()` binds are used everywhere, with no string-built values.
- **File access**: registry imports are confined to `DATASETS_DIR`. Report downloads are confined to `REPORT_STORAGE_DIR`.
- **Audit log**: logins (including failures), reviews, notes, assignments, rule changes, job triggers, user and role changes, report creation, and model activation. It is visible to admins.
- **Headers**: `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options: DENY` on the API and the static web server.
- **Secrets**: none in the repository. `.env*` files are git-ignored (only `*.example` files are tracked). Local dev credentials are generated randomly into `backend/var/dev-credentials.txt`, which is git-ignored.
- **Containers**: the API image runs as a non-root user (uid 10001).
- **Supply chain**: CI runs `pip-audit` and `npm audit` in report mode.

## Known gaps

- Tokens are stored in `localStorage`. This is standard for a bearer-token SPA plus PWA, but it is exposed to XSS. The mitigations are React's escaping, no `dangerouslySetInnerHTML` of user input (map popups escape names), and a strict CSP recommended at the edge.
- There is no MFA or SSO yet (roadmap).
- There is no automatic account lockout beyond rate limiting.
