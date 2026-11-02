#!/bin/sh
set -eu

runtime_password_file=/run/secrets/simulator_db_password
if [ ! -s "$runtime_password_file" ]; then
    echo "simulator runtime credential is missing or empty" >&2
    exit 1
fi

runtime_password="$(cat "$runtime_password_file")"
psql --set ON_ERROR_STOP=1 \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" \
    --set database_name="$POSTGRES_DB" \
    --set runtime_password="$runtime_password" <<'SQL'
SELECT format(
    'CREATE ROLE simulator_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD %L',
    :'runtime_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'simulator_app') \gexec

ALTER ROLE simulator_app PASSWORD :'runtime_password';
REVOKE CREATE, TEMPORARY ON DATABASE :"database_name" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"database_name" TO simulator_app;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO simulator_app;

CREATE TABLE IF NOT EXISTS simulator_orders (
    order_id text PRIMARY KEY,
    items jsonb NOT NULL,
    amount_minor bigint NOT NULL CHECK (amount_minor > 0),
    currency character(3) NOT NULL,
    correlation_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
REVOKE ALL ON TABLE simulator_orders FROM PUBLIC, simulator_app;
GRANT SELECT, INSERT ON TABLE simulator_orders TO simulator_app;
SQL

unset runtime_password
