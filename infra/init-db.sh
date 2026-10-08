#!/bin/sh
set -eu
for service in console reference simulator; do
    case "$service" in
        console) runtime_password="$CONSOLE_DB_PASSWORD" ;;
        reference) runtime_password="$REFERENCE_DB_PASSWORD" ;;
        simulator) runtime_password="$SIMULATOR_DB_PASSWORD" ;;
    esac
    psql --username "$POSTGRES_USER" --dbname postgres --set ON_ERROR_STOP=1 \
        --set service="$service" --set runtime_password="$runtime_password" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD %L', :'service' || '_runtime', :'runtime_password') \gexec
SELECT format('CREATE DATABASE %I', :'service') \gexec
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', :'service') \gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO %I', :'service', :'service' || '_runtime') \gexec
SQL
done
