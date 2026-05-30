-- Replace partial unique index with a full unique constraint so PostgREST
-- ON CONFLICT works. Postgres treats NULL as distinct in unique constraints,
-- so multiple rows with cik IS NULL are still allowed.
drop index if exists public.companies_cik_entry_idx;
alter table public.companies
  add constraint companies_cik_entry_unique unique (cik, entry_date);
