-- Manual, auditable retirement of the legacy key-value table.
-- NEVER executed by init-db, sync, backfill-dashboard or debug_run.py.
--
-- Prerequisites (see README section 7):
--   1. All 12 classified tables and risk.bank_base_nii_eve are in use.
--   2. A full field-level reconciliation passed.
--   3. CLI / API / views / external jobs no longer read finance.metric_value.
--   4. A backup exists, e.g.:
--      pg_dump -t finance.metric_value --data-only <ai_database> > metric_value_backup.sql
--
-- The guard below refuses to drop the table while any view still depends on it.

BEGIN;

DO $$
BEGIN
    IF to_regclass('risk.bank_base_nii_eve') IS NULL THEN
        RAISE EXCEPTION 'Base NII/EVE view is missing; run init-db first';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_depend d
        JOIN pg_rewrite r ON r.oid = d.objid
        JOIN pg_class source_table ON source_table.oid = d.refobjid
        JOIN pg_namespace source_ns ON source_ns.oid = source_table.relnamespace
        WHERE d.classid = 'pg_rewrite'::regclass
          AND source_ns.nspname = 'finance'
          AND source_table.relname = 'metric_value'
    ) THEN
        RAISE EXCEPTION 'finance.metric_value still has dependent views; migrate them first';
    END IF;
END $$;

DROP TABLE IF EXISTS finance.metric_value;

COMMIT;
