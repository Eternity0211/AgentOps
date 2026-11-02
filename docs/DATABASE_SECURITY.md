# Database and service least privilege

Phase 13 separates bootstrap/migration authority from application runtime authority and validates
the local service topology as an exact allowlist. This is a deployable reference contract, not a
claim that the repository provisions production identities or a production secret manager.

## Control-plane PostgreSQL roles

The deployment owns three distinct identities:

| Identity | Purpose | Runtime use |
| --- | --- | --- |
| database/object owner | create the database, extensions, schema, and roles | never supplied to API or worker |
| migrator | run the reviewed Alembic revision set as, or on behalf of, the object owner | deployment job only |
| `agentops_runtime` | API and worker SQLAlchemy connections | normal application operation only |

Create `agentops_runtime` through the deployment's secret manager as a `LOGIN NOSUPERUSER
NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS` role. After every migration, run
`config/postgres/control-plane-runtime-grants.sql` as the database/object owner with the target
database passed as the psql `database_name` variable. For example, with credentials supplied by
the deployment rather than the shell history:

```text
psql --set database_name=agentops --file config/postgres/control-plane-runtime-grants.sql
```

The script removes public schema creation and temporary-table authority, permits the runtime role
to connect and perform required business-table DML, and permits sequence use. Audit events remain
read/append-only. The runtime role cannot update/delete/truncate `audit_events`, cannot insert or
mutate `audit_tenant_sequences`, cannot create schema objects, and receives no direct execution
grant on public-schema functions. Tenant sequence assignment remains inside the reviewed
`SECURITY DEFINER` trigger with a fixed search path.

API and worker are separate processes but currently share the same persistence repository surface,
so the reference runtime role is shared. Splitting their table grants requires a measured process
repository boundary and a superseding migration/grant contract; it must not be claimed merely from
process separation. The local `control-postgres` Compose service still uses its bootstrap owner
because API and worker are not Compose services yet. A production deployment must never place that
owner URL in API or worker configuration.

The PostgreSQL integration suite creates a fresh login with the exact role flags, applies the
checked-in grant script, connects through a second real client session, and proves required audit
append/business DML privileges. It also proves refusal of audit/head mutation, permanent and
temporary table creation, table alteration, and owner-role assumption.

## Diagnosed simulator stores

The simulator PostgreSQL container receives two distinct file secrets. `simulator_admin` owns the
database and runs the first-initialization script; Order receives only `simulator_app`, which has
`CONNECT`, schema `USAGE`, and `SELECT`/`INSERT` on `simulator_orders`. Order no longer attempts DDL
at request time. The runtime account cannot create tables or update/delete stored orders.

The Redis default user is disabled. Inventory authenticates as `inventory_app`, whose ACL is
limited to `stock:*` and `reservation:*` keys plus the exact commands needed for readiness and the
atomic reservation script. It cannot access unrelated keys or run administrative commands such as
`CONFIG`.

PostgreSQL initialization scripts run only for a new local named volume. Changing either simulator
database secret after initialization therefore requires an explicit owner-driven password rotation
or recreation of the disposable local simulator volume. Never delete a non-disposable or
production volume to rotate a credential.

## Network, mount, and credential allowlists

`python scripts/dev.py compose` compares every service against exact network, secret, named-volume,
and read-only config bindings. It rejects an added lateral network, credential, bind mount, writable
store, config mount, plaintext password environment value, or secret target outside `/run/secrets`.
Root filesystems remain read-only and only the declared named volumes and bounded `tmpfs` paths are
writable.

The evaluation Compose contract remains separate: the evaluator has one isolated network, one
credential, and two read-only inputs, while runtime services have no Ground Truth network, mount,
or credential path.

## Reproducible verification

Run the static contract and focused tests with:

```text
python scripts/dev.py compose
python scripts/dev.py test --suite integration
python scripts/dev.py quality
```

The 2026-10-30 local runtime rehearsal additionally created fresh PostgreSQL/Redis volumes, proved
the simulator role and ACL refusal matrix through authenticated clients, rebuilt the simulator
image, and reached healthy state for Gateway, Order, Inventory, Payment, PostgreSQL, and Redis.
This proves the local contract on that environment only; it is not a production isolation or
penetration-test claim.
