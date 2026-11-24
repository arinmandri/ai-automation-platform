#!/usr/bin/env bash
set -euo pipefail

: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${APP_MIGRATOR_USER:?APP_MIGRATOR_USER is required}"
: "${APP_MIGRATOR_PASSWORD:?APP_MIGRATOR_PASSWORD is required}"
: "${APP_API_USER:?APP_API_USER is required}"
: "${APP_API_PASSWORD:?APP_API_PASSWORD is required}"
: "${APP_WORKER_USER:?APP_WORKER_USER is required}"
: "${APP_WORKER_PASSWORD:?APP_WORKER_PASSWORD is required}"
: "${APP_CONTROL_USER:?APP_CONTROL_USER is required}"
: "${APP_CONTROL_PASSWORD:?APP_CONTROL_PASSWORD is required}"

psql --set=ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set=db_name="$POSTGRES_DB" \
  --set=migrator_user="$APP_MIGRATOR_USER" \
  --set=migrator_password="$APP_MIGRATOR_PASSWORD" \
  --set=api_user="$APP_API_USER" \
  --set=api_password="$APP_API_PASSWORD" \
  --set=worker_user="$APP_WORKER_USER" \
  --set=worker_password="$APP_WORKER_PASSWORD" \
  --set=control_user="$APP_CONTROL_USER" \
  --set=control_password="$APP_CONTROL_PASSWORD" <<'SQL'
SELECT 'CREATE ROLE app_owner NOLOGIN NOINHERIT'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_owner') \gexec

SELECT 'CREATE ROLE app_migrator NOLOGIN NOINHERIT'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_migrator') \gexec

SELECT 'CREATE ROLE app_api NOLOGIN NOINHERIT'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_api') \gexec

SELECT 'CREATE ROLE app_worker NOLOGIN NOINHERIT'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_worker') \gexec

SELECT 'CREATE ROLE app_control NOLOGIN NOINHERIT'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_control') \gexec

GRANT app_owner TO app_migrator;
SELECT format('GRANT CREATE, CONNECT, TEMPORARY ON DATABASE %I TO app_owner', :'db_name') \gexec

SELECT format('CREATE ROLE %I LOGIN INHERIT', :'migrator_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'migrator_user') \gexec
SELECT format('ALTER ROLE %I PASSWORD %L', :'migrator_user', :'migrator_password') \gexec
SELECT format('GRANT app_migrator TO %I', :'migrator_user') \gexec

SELECT format('CREATE ROLE %I LOGIN INHERIT', :'api_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'api_user') \gexec
SELECT format('ALTER ROLE %I PASSWORD %L', :'api_user', :'api_password') \gexec
SELECT format('GRANT app_api TO %I', :'api_user') \gexec

SELECT format('CREATE ROLE %I LOGIN INHERIT', :'worker_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'worker_user') \gexec
SELECT format('ALTER ROLE %I PASSWORD %L', :'worker_user', :'worker_password') \gexec
SELECT format('GRANT app_worker TO %I', :'worker_user') \gexec

SELECT format('CREATE ROLE %I LOGIN INHERIT', :'control_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'control_user') \gexec
SELECT format('ALTER ROLE %I PASSWORD %L', :'control_user', :'control_password') \gexec
SELECT format('GRANT app_control TO %I', :'control_user') \gexec
SQL
