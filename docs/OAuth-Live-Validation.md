# Google OAuth — LIVE validation runbook

The `POST /api/auth/google` path (verify a Google `id_token` → mint ITTU's JWT) is
covered by tests with the verifier **mocked** (`tests/test_auth_api.py`), which prove
every branch: POC-closed, valid→JWT, unknown→403, bad→401, no-client-id→500,
allowlist→JWT. What tests *can't* cover is the real Google round-trip. This runbook
does that — a one-time, ~10-minute click-through with a real Google account.

## What the LIVE path enforces

- **MODE gate** — disabled unless the `auth` module is LIVE (`403 google_login_disabled`).
- **Audience** — `ITTU_GOOGLE_CLIENT_ID` **must** be set; without it the endpoint
  fails loud (`500 google_client_id_unset`) rather than verifying with no `aud`
  (which google-auth would silently accept from *any* OAuth client).
- **Provisioning, not signup** — a verified email logs in only if it's a seeded user
  **or** listed in `ITTU_OAUTH_PROVISION` (`403 user_not_provisioned` otherwise).
  First login materializes the user row; agency + role come from the allowlist.

## 1 · Create a Google OAuth Client ID (Web application)

1. [Google Cloud Console](https://console.cloud.google.com) → APIs & Services →
   **Credentials** → *Create credentials* → **OAuth client ID** → *Web application*.
2. **Authorized JavaScript origins** — add wherever you'll open the probe page:
   - `http://localhost:5500` (local probe, see step 4), and/or
   - your Vercel origin `https://honeypot-brown.vercel.app` if you serve it there.
3. Copy the **Client ID** (`…apps.googleusercontent.com`). No client *secret* is
   needed — `id_token` verification is public-key based.

## 2 · Provision your Google email

Pick the agency (slug) + role your identity should log in as. Slugs:
`bareskrim` (police), `ppatk`/`ojk` (regulator), `bank-bca` (bank), `indodax` (exchange).

```
ITTU_OAUTH_PROVISION=[{"email":"you@gmail.com","agency":"bareskrim","role":"police-investigator"}]
```

Set it on whichever backend you're testing (Render env, or local `.env`). A malformed
agency/role here fails loud (`500 provision_agency_unknown` / `provision_role_unknown`)
so a typo can't silently lock you out as "not provisioned".

## 3 · Put the backend in LIVE auth

```
ITTU_MODULE_MODES={"auth":"live"}
ITTU_GOOGLE_CLIENT_ID=<the client id from step 1>
```

(Local: also make sure `ITTU_CORS_ORIGINS` includes the probe origin, e.g.
`http://localhost:5500`, or the browser blocks the call. Then restart the backend.)

## 4 · Run the probe

`backend/scripts/google_login_probe.html` is a self-contained page (Google Identity
Services + fetch). Serve it from an authorized origin — **don't** open it as a `file://`:

```
cd backend/scripts
python -m http.server 5500
# open http://localhost:5500/google_login_probe.html
#   ?backend=http://localhost:8000&client=<client-id>   ← optional prefill
```

Enter the **backend URL** + **Client ID**, click *Load Google button*, then sign in
with your provisioned Google account.

## 5 · Expected result

On success the page shows ITTU's minted JWT (decoded claims), the `login` payload, and
a live `GET /api/auth/me` — proving the token works end-to-end:

```
ok: true
login:   { status: 200, role: "police-investigator", agency: { slug: "bareskrim" }, … }
ittu_jwt_claims: { sub, agency_id, role, email, exp, … }
auth_me: { status: 200, body: { user, agency, role } }
```

Deliberately exercise the failure modes to confirm the guards (the probe surfaces each
error `code`):

| Situation | Expected |
|---|---|
| Provisioned email, valid sign-in | `200` + JWT + `/me` echoes agency/role |
| Email not seeded and not in `ITTU_OAUTH_PROVISION` | `403 user_not_provisioned` |
| `ITTU_GOOGLE_CLIENT_ID` unset while LIVE | `500 google_client_id_unset` |
| Client ID mismatch (probe ID ≠ backend ID) | `401 invalid_google_token` (aud) |
| `auth` module still POC | `403 google_login_disabled` |

Once the `200` path works against real Google and the failure rows behave, the LIVE
OAuth path is validated. Revert `ITTU_MODULE_MODES` to POC (or leave `auth` LIVE if you
want Google-only login) when done.
