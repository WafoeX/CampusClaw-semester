-- Synthetic isolated-test credentials; never used by the regular Compose stack.
CREATE ROLE apitest_owner LOGIN PASSWORD 'apitest-owner-only';
CREATE ROLE apitest_reader LOGIN PASSWORD 'apitest-reader-only';
REVOKE ALL ON DATABASE campusclaw_apitest FROM PUBLIC;
GRANT CONNECT ON DATABASE campusclaw_apitest TO apitest_owner, apitest_reader;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO apitest_owner;
GRANT USAGE ON SCHEMA public TO apitest_reader;
-- Bootstrap this trusted extension as admin; application owner needs no DB CREATE.
CREATE EXTENSION IF NOT EXISTS pg_trgm;
