# ProductBridge Mutation Route Reachability V1 — Implementation Plan

**Issue:** #190  
**Parent:** #187  
**Branch:** `fix/190-product-bridge-mutation-routes`  
**Base:** protected `main` at `d6d0cd1e69a09d59c2200b9e689319bb8c17f926`

## Root cause and boundary

The frontend data clients and Local API agree on fourteen exact stage routes
covering Case Analysis, Planning, offline-device authority, Technical Findings
and Budget. The ProductBridge exact-route allowlist omits them, so normal
same-origin UI operations terminate at the bridge with 404. Component tests
mock `fetch`, while the previous longitudinal test bypassed the bridge, leaving
the vertical composition unproved.

## Causal DAG

`frontend mutation path` -> `ProductBridge exact allowlist` -> `Local API route`
-> `application command` -> `guarded domain/persistence append`.

Critical path: deterministic real-bridge RED -> seven literal route mappings ->
same-origin real-bridge GREEN. The adversarial lane proves that wrong methods,
suffixes and unrelated namespaces remain denied. One mutation owner changes the
single shared allowlist boundary.

## Execution

1. Add a real ProductBridge RED proving exact Case Analysis, Planning and
   Technical Findings mutations return 404 while their base snapshots are
   reachable.
2. Add route-table unit REDs for all fourteen existing frontend/Local API paths
   and near-miss denials: two Case Analysis commands, Planning start, offline
   device GET/replace, five Technical Findings commands and four Budget detail
   commands.
3. Add only literal method/path allowlist mappings in `_proxy_target`; do not
   introduce wildcard forwarding or new authority.
4. Run focused ProductBridge, Case Analysis, Technical Findings, Local API and
   frontend data/view tests plus a sibling sweep of every mutable stage route.
5. Freeze one HEAD, run terminal assurance and `verify_core --full` once, then
   protected CI and independent reviews. Merge normally and post-main verify the
   exact routes before resuming #187.

## Invariants

- `NORMAL_OPERATION_REQUIRES_TERMINAL = 0`
- `EXACT_ROUTE_AUTHORITY_ONLY = PASS`
- `CROSS_SITE_MUTATION = DENIED`
- `GENERIC_PROXY_AUTHORITY = DENIED`
- `PRIVATE_EGRESS = FALSE`
- `P0 = 0`, `P1 = 0`
