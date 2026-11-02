# ADR 0006: Least-privilege runtime identities and topology allowlists

- Status: Accepted
- Date: 2026-11-02

## Context

The local stack originally used the simulator PostgreSQL bootstrap owner for Order and Redis's
default all-capability user for Inventory. Compose validation proved broad isolation properties but
did not reject a service that gained an extra network, credential, bind mount, writable volume, or
configuration file. The control plane documented append-only audit grants but lacked one deployable
post-migration runtime-role contract and a real-login refusal matrix.

An LLM is not an execution authority, but process isolation alone is insufficient if a compromised
runtime process holds owner credentials or can expand laterally. The project needs deterministic,
testable least-privilege boundaries without pretending the repository provisions a production
identity system or secret manager.

## Decision

1. Separate database bootstrap/migration authority from application runtime authority.
   `agentops_runtime` is a deployment-created restricted login; the checked-in post-migration grant
   script permits required business DML while denying schema creation, temporary tables,
   public-schema function execution, audit-row mutation, and audit tenant-head mutation.
2. Keep API and worker as separate processes but use one control-plane runtime role until their
   persistence repositories have a measured, enforceable table-level split. Process separation
   alone is not evidence for distinct SQL grants.
3. Split simulator PostgreSQL into `simulator_admin` and `simulator_app`. Order receives only the
   latter and performs no request-time DDL. Its table grants are `SELECT` and `INSERT` only.
4. Disable the Redis default user. Inventory uses `inventory_app`, limited to `stock:*` and
   `reservation:*` plus the exact readiness and atomic-reservation commands.
5. Treat every Compose service's networks, secrets, named volumes, and config mounts as exact
   allowlists. Password-bearing environment settings must be file references below `/run/secrets`.
6. Require the five local runtime credential paths and values to be pairwise distinct. Ground Truth
   retains its separate evaluation-only credential and topology.
7. Validate control-plane SQL authority through a second authenticated real PostgreSQL session,
   not `SET ROLE` from an owner session. Validate simulator roles/ACLs on fresh local volumes and
   keep the complete static topology contract in the normal quality gate.

## Consequences

- A compromised Order or Inventory process has materially less database/cache authority and no
  bootstrap credential.
- Adding a legitimate service network, secret, mount, or config now requires an intentional
  contract and test update.
- Local users need one additional simulator database owner secret. Reusing files or values fails
  `doctor`.
- Simulator PostgreSQL initialization runs only for a new local volume; later password rotation is
  an explicit owner operation. Production volume deletion is never a rotation procedure.
- The local control PostgreSQL container still starts with a bootstrap owner because API and worker
  are not Compose services. Production composition must use the restricted runtime URL.
- The shared control-plane runtime role has broad business-table DML. A finer API/worker split is a
  future measured change, not a current claim.

## Alternatives considered

- **Continue using database/cache owners.** Rejected because component compromise would grant DDL,
  destructive mutation, and administrative cache commands.
- **Infer isolation from internal networks and read-only roots.** Rejected because those controls do
  not constrain database grants, secret distribution, or an accidental additional mount/network.
- **Create one SQL role per repository immediately.** Deferred because current API and worker
  compositions share repository surfaces; a nominal split would either break operation or grant
  both roles the same authority while overstating isolation.
- **Add a control-plane broker or external identity service.** Rejected for this decision; neither
  is required to enforce the measured database and Compose boundaries.

## Verification

- Static Compose tests mutate each network, secret, target, volume, config, and password boundary
  and require a fail-closed diagnostic.
- Runtime prerequisite tests reject missing, oversized, duplicate-path, and duplicate-value secret
  files without exposing content.
- PostgreSQL integration creates a fresh restricted login, applies the checked-in grant script,
  proves required append/business access, and proves DDL, audit/head mutation, and owner-role
  assumption are denied.
- Simulator dependency tests prove Order performs no DDL and Inventory supplies the named Redis
  user. A fresh-volume local rehearsal proved PostgreSQL and Redis refusal matrices and all six
  simulator containers healthy.
