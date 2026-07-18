# ITTU — Identity & Access Architecture (target state)

> How a user gets in, what they're allowed to do, and which data they can touch — across the POC
> (today) and the real multi-agency government deployment (target). Extends
> [Security-Evidence.md](Security-Evidence.md) §1–2 with the IdP direction, delegated administration,
> and cross-agency sharing worked out for the production build. Nothing here changes the enforcement
> core (RBAC + RLS) — it only changes where *identity* and *role assignment* come from.

## The one idea: three layers, three questions

Every request passes through three independent gates. None can cover for the others.

| Layer | Question | Where it lives | Status |
|---|---|---|---|
| **IdP / Authentication** | Are you really you? | Google today; Keycloak (brokering Google + agency IdPs) at scale | Google done; Keycloak planned |
| **RBAC / Authorization** | Is this action allowed for your role? | ITTU — `require_role(...)` on endpoints | Done |
| **RLS / Data isolation** | Which rows may you touch? | Postgres — `agency_id = current_agency()` policies | Done |

```
 Budi logs in
   │
 [ IdP ]   Google/Keycloak verifies him → "this is Budi, verified"        ← WHO ARE YOU
   │
 ITTU mints its OWN JWT: { sub, agency_id: bareskrim, role: police-investigator, exp }
   │
 [ RBAC ]  may a police-investigator perform this action?                 ← WHAT MAY YOU DO
   │
 ITTU sets DB "current agency = bareskrim" for the request
   │
 [ RLS ]   Postgres returns ONLY bareskrim rows for every query           ← WHICH DATA
   │
 Budi sees his cases. PPATK's data was never fetched.
```

**Design payoff:** ITTU always verifies an external identity and then mints *its own* JWT (`{sub,
agency_id, role, exp}`). Everything downstream depends only on that JWT — so swapping the IdP (Google →
Keycloak) changes only the top box. RBAC and RLS — the parts that actually protect the data — never move.

---

## 1. Identity Provider (IdP)

An IdP is the system that verifies logins and vouches for identity via a signed token (OIDC/SAML). Apps
delegate authentication to it instead of handling passwords themselves.

- **Today (POC):** Google OAuth is the IdP. Backend verifies the `id_token` (audience-checked — see
  [OAuth-Live-Validation.md](OAuth-Live-Validation.md)) and mints ITTU's JWT.
- **Target: Keycloak as an identity *broker*.** ITTU integrates with **one** IdP (Keycloak); Keycloak
  fans out to many upstream sources:

  ```
  user ─► ITTU ─► Keycloak ─┬─► Google (social / external users)
        (one OIDC)           ├─► Bareskrim Active Directory / Entra
                             ├─► PPATK / OJK IdP (SAML/OIDC)
                             └─► local users Keycloak hosts itself
  ```

  Adding a new agency's login = a Keycloak config change, **zero ITTU code**. Self-hosted (Keycloak or the
  lighter Zitadel) keeps identity data in-country — matches the K3s/on-prem data-sovereignty posture in
  [Deploy.md](Deploy.md). Google is kept *behind* Keycloak, not replaced.
- **"Upstream"** = whatever system the login came from before ITTU (Google, an agency directory).
  ITTU is *downstream*: it receives identity, it does not originate it.
- **Selected by MODE** (per [Adapter-MODE-Framework.md](Adapter-MODE-Framework.md)): cloud POC verifies
  Google directly; on-prem verifies Keycloak. Same "verify external OIDC token → provision → mint JWT"
  seam — make that seam a pluggable boundary so the switch is config, not a rewrite.

## 2. Provisioning & role assignment (who gets in, as what)

Authentication proves identity; it does **not** grant ITTU access. A verified user gets in only if
provisioned. Two inputs decide the ITTU role, both resolved **inside ITTU** (never blindly trusting an
upstream claim):

**a. Role-mapping table (the bulk default).** An admin-managed table in ITTU maps an upstream group/role
to a *default* ITTU role, applied on first login (JIT). This is the zero-touch path — 500 investigators in
the right upstream group are all assigned automatically.

| Upstream group/role (from Keycloak/Workspace) | → | ITTU role (default on first login) |
|---|---|---|
| `ittu-investigators` | → | `police-investigator` |
| `ittu-analysts` | → | `regulator-analyst` |
| *unmapped / no group* | → | `read-only` (safe fallback) |

**b. Per-user override (the exceptions).** An agency-admin can set a specific user's role regardless of the
mapping. Stored in ITTU as the authoritative *effective* role.

**Security rule — default low, elevate explicitly.** The upstream claim is a *hint*, not the final word.
Never auto-grant a privileged role (investigator/dispatch) from an upstream group; default new users to a
low-privilege role and require an explicit elevation *in ITTU* to reach anything sensitive. The mapping
table is authored in ITTU, so ITTU — not the upstream — controls the ceiling.

Interim POC mechanism: `ITTU_OAUTH_PROVISION` (env allowlist, see
[OAuth-Live-Validation.md](OAuth-Live-Validation.md)) is the bootstrap-only stand-in for the table — fine
for validation, demoted to bootstrapping the first admin once the table exists.

## 3. Delegated administration

Admin authority is tiered and **agency-scoped** — enforced for free by RLS (an agency-admin's writes are
constrained to their own `agency_id`; they physically cannot touch another agency's users).

```
Platform-admin  (ITTU owner)
   ├─ manages agencies, creates each agency's first admin, owns the global role-mapping table
   │
   ├─ Bareskrim agency-admin ─► manages ONLY Bareskrim users + roles
   ├─ PPATK agency-admin     ─► manages ONLY PPATK users + roles
   └─ OJK agency-admin        ─► manages ONLY OJK users + roles
          └─ investigators / analysts / compliance  (no admin powers)
```

**Bootstrap chain:** platform-admin (seeded/bootstrapped) → creates each agency + its first agency-admin →
that admin manages their own employees. No one is pulled into another agency's day-to-day onboarding.

Onboarding a new investigator (Budi, Bareskrim, Google Workspace brokered by Keycloak):

| Step | Who | Where |
|---|---|---|
| Create work identity; put in `ittu-*` group | Bareskrim IT/HR | Google Workspace (upstream) |
| First login → JIT-created at mapped default role | Budi + systems | ITTU |
| Elevate to `police-investigator` if needed | Bareskrim agency-admin | ITTU |
| Define what `police-investigator` may *do* | (set once, at build) | ITTU (RBAC) |
| **Offboard:** disable the work account | Bareskrim IT | Workspace → login dies everywhere |

## 4. Cross-agency access (collaboration without breaking isolation)

Financial-crime cases are joint (police + PPATK + OJK), so cross-agency access is core — but it's exactly
what the isolation protects, so it is **never** a unilateral agency-admin action.

- **Forbidden:** an agency-admin granting blanket access into another agency (would dissolve the tenant
  boundary — one careless admin could reach the regulator's cases).
- **Model instead — consented, case-scoped, audited sharing:** the **owning** agency shares *a specific
  case* with *a specific user* from another agency, time-boxed and logged. Same collaboration outcome,
  boundary intact.
- **Blanket cross-agency access** (if ever needed) is a rare **platform-admin** action.

**Mechanism:** RLS keeps enforcing "your home agency." A cross-agency grant is an explicit additional
record — *user X may also see case Y in agency Z until date D* — checked *in addition to* the home-agency
policy. A sharing/ACL layer **over** isolation, never a hole in it.

---

## Build status

- **Done:** RBAC roles + `require_role` dependencies; Postgres RLS agency isolation (proven by
  `backend/tests/test_rls_isolation.py`); Google OAuth login with audience verification + operator
  allowlist provisioning; the non-owning `ittu_app` role that makes RLS bite.
- **Planned (real-deployment increments):** Keycloak brokering behind a pluggable IdP boundary; the
  admin-managed `core.users` roster with a `status` column; the role-mapping table; agency-admin
  management screens/endpoints; the consented cross-agency case-sharing grant.

See also: [Security-Evidence.md](Security-Evidence.md) (RLS + evidence contract),
[Persistence-Plan.md](Persistence-Plan.md) (the `core.users`/repository foundation these build on),
[OAuth-Live-Validation.md](OAuth-Live-Validation.md) (validating the current Google path).
