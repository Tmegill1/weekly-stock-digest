-- Phase 2: Event Extraction
-- Tables: event_taxonomy (reference), events (one row per extracted event)

create table public.event_taxonomy (
  id                  uuid         primary key default uuid_generate_v4(),
  event_code          text         not null unique,
  category            text         not null,
  label               text         not null,
  description         text         not null,
  scoring_weight_hint numeric(5,2) not null default 1.0,
  created_at          timestamptz  not null default now()
);

insert into public.event_taxonomy (event_code, category, label, description, scoring_weight_hint) values
  ('insider_buy_large',      'insider_trading', 'Large Insider Buy',      'Insider purchase > $1M',             1.5),
  ('insider_sell_large',     'insider_trading', 'Large Insider Sell',     'Insider sale > $1M',                 1.5),
  ('insider_buy_small',      'insider_trading', 'Small Insider Buy',      'Insider purchase <= $1M',            1.0),
  ('insider_sell_small',     'insider_trading', 'Small Insider Sell',     'Insider sale <= $1M',                0.8),
  ('earnings_beat',          'earnings',        'Earnings Beat',          'EPS above consensus estimate',       1.2),
  ('earnings_miss',          'earnings',        'Earnings Miss',          'EPS below consensus estimate',       1.2),
  ('earnings_inline',        'earnings',        'Earnings Inline',        'EPS in line with consensus',         0.5),
  ('guidance_raised',        'guidance',        'Guidance Raised',        'Forward guidance increased',         1.3),
  ('guidance_lowered',       'guidance',        'Guidance Lowered',       'Forward guidance decreased',         1.3),
  ('guidance_initiated',     'guidance',        'Guidance Initiated',     'First-time forward guidance issued', 1.0),
  ('acquisition_announced',  'corporate',       'Acquisition Announced',  'Company acquiring another entity',   1.4),
  ('merger_announced',       'corporate',       'Merger Announced',       'Merger of equals announced',         1.4),
  ('divestiture_announced',  'corporate',       'Divestiture Announced',  'Sale of business unit announced',    1.1),
  ('ceo_change',             'executive',       'CEO Change',             'Chief Executive Officer change',     1.3),
  ('cfo_change',             'executive',       'CFO Change',             'Chief Financial Officer change',     1.1),
  ('executive_change_other', 'executive',       'Other Executive Change', 'Other C-suite or director change',   0.8),
  ('buyback_announced',      'capital',         'Buyback Announced',      'Share repurchase program announced', 1.1),
  ('dividend_change',        'capital',         'Dividend Change',        'Dividend initiated, raised, or cut', 1.0);

create table public.events (
  id           uuid    primary key default uuid_generate_v4(),
  filing_id    uuid    not null references public.filings (id) on delete cascade,
  company_id   uuid    not null references public.companies (id) on delete cascade,
  event_code   text    not null references public.event_taxonomy (event_code),
  filed_date   date    not null,
  sentiment    text    not null check (sentiment in ('positive', 'negative', 'neutral')),
  magnitude    numeric(10,4),
  details      jsonb   not null default '{}',
  extracted_by text    not null check (extracted_by in ('rules', 'claude')),
  created_at   timestamptz not null default now(),
  constraint events_filing_event_unique unique (filing_id, event_code)
);

create index events_company_date_idx on public.events (company_id, filed_date);
create index events_filed_date_idx   on public.events (filed_date);
create index events_event_code_idx   on public.events (event_code);
create index events_filing_id_idx    on public.events (filing_id);

alter table public.event_taxonomy enable row level security;
alter table public.events         enable row level security;

create policy "event_taxonomy_authenticated_read"
  on public.event_taxonomy for select to authenticated using (true);
create policy "events_authenticated_read"
  on public.events for select to authenticated using (true);
