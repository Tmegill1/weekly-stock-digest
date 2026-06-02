-- Returns (company_id, max_trading_date) for all companies that have prices.
-- Used by the stale-price quality check.
create or replace function public.max_trading_dates()
returns table(company_id uuid, max_date date)
language sql
security invoker
stable
as $$
  select company_id, max(trading_date)
  from   public.prices
  group  by company_id;
$$;
