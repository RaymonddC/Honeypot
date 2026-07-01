# ITTU — API Contract (OpenAPI surface)

> The HTTP/WS surface the Frontend + workers consume. FastAPI auto-generates OpenAPI/Swagger from
> Pydantic models. Locking this lets Frontend, Backend-Core, and AI-Engineer build in parallel.
> All routes are JWT-authenticated (except auth) and RLS-scoped by the token's `agency_id`.

## Conventions
- **Auth:** `Authorization: Bearer <jwt>`; JWT claims `{sub, agency_id, role, exp}`. Middleware sets
  `app.current_agency`/`app.current_user` Postgres session vars → RLS enforced.
- **Errors:** `{ "error": {"code","message","detail?"} }`, standard HTTP statuses.
- **Pagination:** cursor-based `?cursor=&limit=`; responses `{items, next_cursor}`.
- **IDs:** UUID. **Times:** ISO-8601 UTC. **Money:** integer minor units + currency.
- **Streaming:** SSE/WS for live honeypot + investigation reasoning (Glass Box), mirroring ELSA's
  `/analyze-stream` pattern.

## Auth & identity
```
POST /auth/google        {id_token}          → {jwt, user}         # Google OAuth → our JWT
GET  /auth/me                                 → {user, agency, role}
```

## Cases (core spine)
```
GET  /cases                                   → [case]             # RLS-scoped
POST /cases              {title, crime_type, data_mode}  → case
GET  /cases/{id}                               → case (+summary)
POST /cases/{id}/share   {agency_id, access}   → ok                # explicit cross-agency grant
```

## INFILTRATE (honeypot)
```
GET  /sessions?case=                           → [scam_session]
POST /sessions          {persona_id, channel_type, channel}  → session   # start (POC replay/LIVE)
GET  /sessions/{id}                            → session
GET  /sessions/{id}/messages                   → [message]         # hash-chained log
WS   /sessions/{id}/stream                      ← live turns + tool calls (Glass Box)
GET  /entities?session=&status=                → [entity]          # extracted, confidence-scored
POST /entities/{id}/review  {status}           → entity            # confirm/reject/poisoned
GET  /syndicates?case=                         → [syndicate]
```

## TAKEDOWN (Investigation Screen)
```
POST /investigate       {address, chain}       → {graph, scores}   # ingest+score, async job ok
GET  /wallets/{addr}                            → wallet (+features)
GET  /wallets/{addr}/graph?hops=3               → {nodes, edges}    # Cytoscape elements
POST /wallets/{addr}/expand  {node}            → {nodes, edges}     # lazy BFS
GET  /wallets/{addr}/risk                       → risk_score (+reasoning, patterns)
```

## TRACE (Bridge View)
```
POST /bridge/simulate   {case, params}         → ok                # gen synthetic PT A2Z fiat (POC)
GET  /bridge/sankey?case=                       → sankey_data
GET  /bridge/correlations?case=                 → [correlation]     # fiat↔crypto matches
GET  /bridge/mules?case=                         → [mule_cluster]
```

## UNCOVER (Action Panel)
```
POST /actions/generate  {case, entities, outputs[freeze|ltkm|alert|pack]}  → action_bundle (draft)
GET  /actions/{id}                              → action_bundle (+docs, status)
POST /actions/{id}/dispatch                     → status            # human-gated; POC mock / LIVE
GET  /documents/{id}                            → PDF binary        # download (hashed)
```

## Dashboard & shared
```
GET  /metrics/response?range=                   → dashboard_metrics
GET  /tags?address=&chain=                       → [address_tag]
```

## Worker (Dramatiq) jobs — not HTTP, listed for completeness
`ingest_wallet`, `score_wallet`, `honeypot_turn`, `run_correlation`, `generate_documents`,
`dispatch_notifications`, `poll_blockchain` (scheduled). All CPU/I/O-heavy work off the event loop.

## Notes
- `POST /investigate` and doc generation may return a job id + `GET` poll or WS push if slow.
- WS/SSE channels carry the **reasoning trace** so the Glass Box UI renders each step live.
