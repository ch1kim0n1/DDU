# Auth / RBAC Design

DDU is an operational system handling sensitive investigation data. Auth is mandatory from day 1, not bolted on later.

## Principles

1. **Investigation-scoped access.** A user's permissions are evaluated within the context of a specific investigation. Global admins exist but are rare.
2. **Agents inherit, never escalate.** An agent runs with the permissions of the user who launched it. Agents cannot self-elevate.
3. **Every action audited.** Every read, write, agent action, evidence access, and resolution decision is logged with user id, investigation id, timestamp, and target.
4. **Collection boundaries enforced per connector.** A connector can only access data sources permitted by its configured scope and the active investigation's policy.
5. **No auto high-impact merges.** Identity merges, evidence deletion, and verification state changes require human authorization at or above the investigation's `analyst` role.

## Identity

- **IdP:** OIDC (Keycloak in dev, any OIDC provider in prod — Okta, Auth0, Google, Azure AD).
- **Service auth:** mTLS between `ddu-*` services. Service mesh (or simple mTLS via env-loaded certs in MVP).
- **User auth:** OIDC access token (JWT) verified by `ddu-api`.
- **API keys:** supported for automation, scoped to a service account, investigation-scoped, revocable.

## Roles

Global roles:
- `platform_admin` — manage users, services, global config. Cannot read investigation data unless added to investigation.
- `security_officer` — audit log access, compliance exports. Read-only on investigations.

Investigation-scoped roles (assigned per investigation):
- `investigation_owner` — full control: members, settings, deletion.
- `lead_analyst` — everything except member management and deletion. Can verify/reject candidate relationships.
- `analyst` — read/write evidence, observations, entities. Cannot verify/reject candidate relationships.
- `viewer` — read-only.
- `agent` — assigned to service accounts backing LangGraph workflows. Inherits launching user's role at launch time.

## Permission Matrix

| Action | viewer | analyst | lead_analyst | investigation_owner | agent (inherits) |
|--------|--------|---------|--------------|---------------------|------------------|
| Read investigation | ✓ | ✓ | ✓ | ✓ | ✓ |
| Add evidence | — | ✓ | ✓ | ✓ | ✓ |
| Add observation | — | ✓ | ✓ | ✓ | ✓ |
| Create candidate relationship | — | ✓ | ✓ | ✓ | ✓ |
| Verify / reject candidate relationship | — | — | ✓ | ✓ | — |
| Merge entities (high-impact) | — | — | ✓ | ✓ | — |
| Delete evidence | — | — | ✓ | ✓ | — |
| Manage members | — | — | — | ✓ | — |
| Delete investigation | — | — | — | ✓ | — |
| Launch agent workflow | — | ✓ | ✓ | ✓ | — |
| Agent self-elevation | — | — | — | — | DENIED |

## Enforcement Layers

1. **`ddu-api`** — JWT verification, role extraction, investigation-scope check on every request. Returns `403` on violation.
2. **Service-level** — every `ddu-*` service receives a forwarded identity context (user id, investigation id, role) in request metadata. Services re-check role for high-impact operations (verify, merge, delete). Defense in depth.
3. **Data-level** — Neo4j, Qdrant, MinIO buckets are partitioned by investigation id. Service queries always include `investigation_id` filter. Cross-investigation access requires explicit platform_admin action.

## Audit Log

Append-only, stored in MinIO `ddu-audit` bucket (created in Phase 1) and mirrored to a SQL store for queryability.

Fields: `timestamp`, `user_id`, `investigation_id`, `action`, `target_type`, `target_id`, `result`, `request_id`, `ip_address`, `user_agent`.

Examples:
- `2026-07-21T12:00:00Z user=u1 inv=case-001 action=READ target=Evidence id=sha256:abc result=200`
- `2026-07-21T12:01:00Z user=u1 inv=case-001 action=VERIFY_CANDIDATE target=CandidateRelationship id=cr-42 result=200`
- `2026-07-21T12:02:00Z user=agent-1 inv=case-001 action=CREATE_OBSERVATION target=Observation id=obs-99 result=200 launched_by=u1`

## Collection Boundaries

Each connector (`ddu-collector`, `ddu-webcapture`, `ddu-osint`, `ddu-discovery`) declares:
- `supported_sources` — what it can access.
- `access_requirements` — public / authenticated / restricted.
- `rate_limit` — per-source.
- `retention_policy` — how long collected data lives.
- `investigation_scope` — bound to active investigation.

Agents cannot access data outside the active investigation's policy. Hardcoded in service-level enforcement.

## Secrets

- **Vault** (HashiCorp Vault in prod) or **SOPS + age** (dev/small deployments).
- Never in repo. Never in env files committed to git.
- Service secrets injected at container start via env or mounted secret files.
- Connector credentials (SpiderFoot API keys, gallery-dl cookies, CompreFace keys) stored per-investigation or per-tenant in Vault.

## Encryption

- **At rest:** MinIO server-side encryption (SSE-S3 or SSE-KMS). Neo4j, Qdrant, Postgres volumes encrypted at the disk level (LUKS in prod, optional in dev).
- **In transit:** TLS everywhere. mTLS between services. No plaintext internal traffic in prod.

## MVP Scope (Phase 1)

- OIDC integration with Keycloak (dev) or external IdP.
- `ddu-api` JWT verification + role check.
- Investigation-scoped roles: `viewer`, `analyst`, `lead_analyst`, `investigation_owner`.
- Audit log to MinIO + Postgres.
- Per-investigation data partitioning.
- mTLS between services (self-signed certs in dev, real CA in prod).

## Phase 2+

- Service accounts with scoped API keys.
- Agent permission inheritance enforcement at service level.
- Collection boundary policy engine.
- Data retention policy enforcement.
- Deletion workflows with audit trail.
- Compliance export (GDPR / legal hold).
