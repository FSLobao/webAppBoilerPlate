-- Create the least-privilege runtime role used by the webapp API.
-- Target: PostgreSQL 18, database db_webapp, after 001_schema.sql.
-- Execution: run once by the official postgres image through psql from
-- /docker-entrypoint-initdb.d, as the image superuser. Requires psql: uses \set.
-- Parameters: the password is read from /run/secrets/api-db-password, mounted read-only;
-- it never appears in process arguments or logs.
-- Transaction: one transaction for the role and its grants.
-- Side effects: creates login role webapp_api with DML on webapp.TB_USUARIO only.
-- Rollback: DROP OWNED BY webapp_api; DROP ROLE webapp_api;

\set api_password `cat /run/secrets/api-db-password`

BEGIN;

CREATE ROLE webapp_api LOGIN PASSWORD :'api_password';

COMMENT ON ROLE webapp_api IS
    'Papel de execução da API webapp; somente leitura e escrita de dados, sem DDL.';

REVOKE ALL ON DATABASE db_webapp FROM PUBLIC;
GRANT CONNECT ON DATABASE db_webapp TO webapp_api;
GRANT USAGE ON SCHEMA webapp TO webapp_api;
GRANT SELECT, INSERT, UPDATE, DELETE ON webapp.TB_USUARIO TO webapp_api;

COMMIT;

\unset api_password
