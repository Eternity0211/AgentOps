\set ON_ERROR_STOP on

-- Run as the database/object owner after migrations. The login role is created and
-- password-managed by the deployment secret manager, never by this repository.
REVOKE CREATE, TEMPORARY ON DATABASE :"database_name" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"database_name" TO agentops_runtime;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO agentops_runtime;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO agentops_runtime;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO agentops_runtime;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC, agentops_runtime;

-- The application may append and read audit events. The SECURITY DEFINER trigger owns
-- tenant-head assignment, so the runtime role never mutates the sequence head directly.
REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM agentops_runtime;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON audit_tenant_sequences FROM agentops_runtime;

-- Keep grants correct for later migrations executed by this same object owner.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO agentops_runtime;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO agentops_runtime;
