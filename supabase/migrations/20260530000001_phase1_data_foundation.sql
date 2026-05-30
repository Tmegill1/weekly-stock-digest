-- =============================================================================
-- Phase 1: Data Foundation
-- Tables: companies, prices, filings, data_quality_log
--
-- Core invariant enforced throughout:
--   Every record has a public_date (the date it became publicly available).
--   For prices:  public_date = trading_date
--   For filings: public_date = filed_date  (NEVER period_date)
--
-- Backtest queries must filter on these dates to prevent lookahead bias.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Extensions
-- ---------------------------------------------------------------------------

create extension if not exists "uuid-ossp";
create extension if not exists "pg_trgm"; -- for text search on company names/tickers


-- ---------------------------------------------------------------------------
-- companies
-- The stock universe with historical membership.
-- Includes delisted, acquired, and bankrupt companies to prevent
-- survivorship bias. Use entry_date / exit_date for point-in-time queries.
-- ---------------------------------------------------------------------------

create table public.companies (
  id             uuid        primary key default uuid_generate_v4(),
  ticker         text        not null,
  cik            text,                          -- SEC Central Index Key
  name           text        not null,
  sector         text,                          -- GICS sector
  industry       text,                          -- GICS industry group
  exchange       text,                          -- NYSE, NASDAQ, etc.
  is_benchmark   boolean     not null default false, -- true for SPY and other benchmarks
  entry_date     date        not null,          -- date added to the tracked universe
  exit_date      date,                          -- null = still active
  exit_reason    text        check (exit_reason in (
                               'delisted', 'acquired', 'bankrupt',
                               'removed_from_index', null
                             )),
  created_at     timestamptz not null default now(),

  constraint companies_exit_after_entry check (
    exit_date is null or exit_date > entry_date
  ),
  constraint companies_exit_reason_requires_date check (
    exit_reason is null or exit_date is not null
  )
);

-- A CIK maps to one company per entry window (supports re-additions)
create unique index companies_cik_entry_idx
  on public.companies (cik, entry_date)
  where cik is not null;

create index companies_ticker_idx       on public.companies (ticker);
create index companies_cik_idx          on public.companies (cik);
create index companies_dates_idx        on public.companies (entry_date, exit_date);
create index companies_active_idx       on public.companies (id) where exit_date is null;
create index companies_name_trgm_idx    on public.companies using gin (name gin_trgm_ops);

comment on table  public.companies                is 'Stock universe with full historical membership. Includes delisted/bankrupt companies to prevent survivorship bias.';
comment on column public.companies.cik            is 'SEC Central Index Key — links a company to its EDGAR filings.';
comment on column public.companies.is_benchmark   is 'True for benchmark instruments (e.g. SPY). Benchmarks are always active and not subject to universe filters.';
comment on column public.companies.entry_date     is 'Date the company entered the tracked universe.';
comment on column public.companies.exit_date      is 'Date the company left the universe. NULL means currently active.';
comment on column public.companies.exit_reason    is 'Why the company left: delisted, acquired, bankrupt, or removed_from_index.';


-- ---------------------------------------------------------------------------
-- prices
-- Daily OHLCV price data for all universe companies and benchmarks.
-- adj_close is the canonical return field (split + dividend adjusted).
-- trading_date IS the public_date — prices are only visible after market close.
-- ---------------------------------------------------------------------------

create table public.prices (
  id            uuid        primary key default uuid_generate_v4(),
  company_id    uuid        not null references public.companies (id) on delete cascade,
  trading_date  date        not null,  -- public_date for price data
  open          numeric(14, 6),
  high          numeric(14, 6),
  low           numeric(14, 6),
  close         numeric(14, 6),
  adj_close     numeric(14, 6) not null, -- use this for all return calculations
  volume        bigint,
  created_at    timestamptz not null default now(),

  constraint prices_hloc_sanity check (
    high >= low
    and (open      is null or (open      between low and high))
    and (close     is null or (close     between low and high))
    and (adj_close > 0)
  )
);

create unique index prices_company_date_idx on public.prices (company_id, trading_date);
create index prices_trading_date_idx        on public.prices (trading_date);
create index prices_company_id_idx          on public.prices (company_id);

comment on table  public.prices               is 'Daily OHLCV. adj_close is split/dividend-adjusted. trading_date is the public availability date — do not query prices dated after the backtest as-of date.';
comment on column public.prices.adj_close     is 'Split and dividend adjusted close. Always use this for return calculations, never raw close.';
comment on column public.prices.trading_date  is 'The trading date. This is the public_date for price data.';


-- ---------------------------------------------------------------------------
-- filings
-- SEC EDGAR filing metadata.
--
-- CRITICAL: filed_date is the public availability date.
--           period_date is the period the filing COVERS.
--           ALL event study timestamps must use filed_date, never period_date.
-- ---------------------------------------------------------------------------

create table public.filings (
  id                 uuid        primary key default uuid_generate_v4(),
  company_id         uuid        not null references public.companies (id) on delete cascade,
  cik                text        not null,     -- denormalized for fast EDGAR lookups
  accession_number   text        not null unique, -- e.g. 0001234567-24-000001
  form_type          text        not null,     -- '8-K', '10-Q', '10-K', '4'
  filed_date         date        not null,     -- PUBLIC AVAILABILITY DATE — use for event timestamps
  period_date        date,                     -- period the filing covers — NOT the event date
  filing_url         text,                     -- EDGAR submission index URL
  raw_storage_path   text,                     -- path to locally cached raw filing
  is_parsed          boolean     not null default false, -- true once event extraction has run
  created_at         timestamptz not null default now(),

  constraint filings_form_type_check check (
    form_type in ('8-K', '10-Q', '10-K', '4', 'SC 13G', 'SC 13D', 'other')
  ),
  -- filed_date should generally be >= period_date (report comes after the period)
  constraint filings_filed_after_period check (
    period_date is null or filed_date >= period_date
  )
);

create index filings_company_form_date_idx on public.filings (company_id, form_type, filed_date);
create index filings_filed_date_idx        on public.filings (filed_date);
create index filings_form_type_idx         on public.filings (form_type);
create index filings_cik_idx               on public.filings (cik);
create index filings_unparsed_idx          on public.filings (id) where is_parsed = false;

comment on table  public.filings                  is 'SEC EDGAR filing metadata. filed_date is the public availability date for all event study purposes.';
comment on column public.filings.filed_date       is 'Date EDGAR received and published the filing. ALWAYS use this as the event timestamp — never period_date.';
comment on column public.filings.period_date      is 'The accounting period the filing covers (e.g. quarter end). NOT the public availability date. Never use as an event timestamp.';
comment on column public.filings.accession_number is 'EDGAR accession number. Unique identifier for a filing globally.';
comment on column public.filings.is_parsed        is 'Set to true once event extraction (Phase 2) has processed this filing.';


-- ---------------------------------------------------------------------------
-- data_quality_log
-- Append-only log of data quality checks and issues.
-- Checked before every weekly digest run.
-- ---------------------------------------------------------------------------

create table public.data_quality_log (
  id           uuid        primary key default uuid_generate_v4(),
  checked_at   timestamptz not null default now(),
  check_type   text        not null check (check_type in (
                             'price_gap', 'stale_price', 'price_anomaly',
                             'missing_filing', 'freshness', 'other'
                           )),
  company_id   uuid        references public.companies (id) on delete set null,
  severity     text        not null check (severity in ('error', 'warning', 'info')),
  message      text        not null,
  details      jsonb,      -- structured extra context (e.g. {gap_days: 5, from: '2024-01-01'})
  resolved_at  timestamptz
);

create index data_quality_checked_at_idx  on public.data_quality_log (checked_at desc);
create index data_quality_severity_idx    on public.data_quality_log (severity, checked_at desc);
create index data_quality_company_idx     on public.data_quality_log (company_id) where company_id is not null;
create index data_quality_unresolved_idx  on public.data_quality_log (id) where resolved_at is null;

comment on table  public.data_quality_log             is 'Append-only log of data quality checks. Query for unresolved errors before each weekly digest run.';
comment on column public.data_quality_log.check_type  is 'price_gap: missing trading days | stale_price: data not updated | price_anomaly: >50% single-day move | missing_filing: expected filing not found | freshness: source not updated within window';
comment on column public.data_quality_log.details     is 'JSON bag of structured context for the issue (dates, magnitudes, counts, etc.).';


-- ---------------------------------------------------------------------------
-- Row Level Security
-- This is a backend pipeline tool — the Python service uses service_role
-- (which bypasses RLS). Authenticated users (you) get read access.
-- Anon gets nothing.
-- ---------------------------------------------------------------------------

alter table public.companies          enable row level security;
alter table public.prices             enable row level security;
alter table public.filings            enable row level security;
alter table public.data_quality_log   enable row level security;

create policy "companies_authenticated_read"
  on public.companies for select
  to authenticated using (true);

create policy "prices_authenticated_read"
  on public.prices for select
  to authenticated using (true);

create policy "filings_authenticated_read"
  on public.filings for select
  to authenticated using (true);

create policy "data_quality_authenticated_read"
  on public.data_quality_log for select
  to authenticated using (true);


-- ---------------------------------------------------------------------------
-- Helper: universe_as_of(date)
-- Returns the companies that were in the universe on a given date.
-- Use this in every backtest query to enforce point-in-time correctness.
-- ---------------------------------------------------------------------------

create or replace function public.universe_as_of(as_of_date date)
returns setof public.companies
language sql
security invoker
stable
as $$
  select *
  from   public.companies
  where  entry_date  <= as_of_date
    and  (exit_date  is null or exit_date > as_of_date)
    and  is_benchmark = false;
$$;

comment on function public.universe_as_of is
  'Returns non-benchmark companies active in the universe on as_of_date. '
  'Use in every backtest step to prevent lookahead bias.';


-- ---------------------------------------------------------------------------
-- Helper: prices_as_of(uuid, date)
-- Returns the most recent price for a company on or before a given date.
-- ---------------------------------------------------------------------------

create or replace function public.price_as_of(
  p_company_id uuid,
  as_of_date   date
)
returns public.prices
language sql
security invoker
stable
as $$
  select *
  from   public.prices
  where  company_id   = p_company_id
    and  trading_date <= as_of_date
  order by trading_date desc
  limit  1;
$$;

comment on function public.price_as_of is
  'Most recent price for a company on or before as_of_date. '
  'Safe for backtest use — never returns a future price.';


-- ---------------------------------------------------------------------------
-- Seed: SPY benchmark row
-- SPY must exist in companies so price data can be stored and queried.
-- ---------------------------------------------------------------------------

insert into public.companies (ticker, name, is_benchmark, entry_date)
values ('SPY', 'SPDR S&P 500 ETF Trust', true, '1993-01-29')
on conflict do nothing;
