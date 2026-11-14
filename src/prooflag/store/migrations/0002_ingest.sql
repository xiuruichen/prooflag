-- S2: ingest columns, rule-change log, bid/ask/last in snapshots, Polymarket token ids.

-- Rules text lives only in market_versions (exact stored text, spans verified against it).
alter table markets drop column rules_text;
alter table markets drop column rules_secondary;

alter table markets add column series_ticker text;
alter table markets add column event_id text;
alter table markets add column event_title text;
alter table markets add column category text;
alter table markets add column open_time_utc text;
alter table markets add column vol24_contracts real;     -- Kalshi: contracts, not dollars
alter table markets add column vol24_usd_est real;       -- Kalshi: contracts x last price; Polymarket: volume24hr
alter table markets add column open_interest_contracts real;  -- Kalshi only
alter table markets add column liquidity_usd real;       -- Polymarket only; never treated as OI
alter table markets add column meaningful integer not null default 0;
alter table markets add column watched integer not null default 0;   -- sticky once set
alter table markets add column current_rules_sha text;
alter table markets add column result text;              -- yes | no | other | null
alter table markets add column settled_at text;
alter table markets add column yes_label text;           -- outcome that bid/ask/last refer to
alter table markets add column history_through text;     -- last backfilled ts (UTC ISO)
create index idx_markets_watched on markets(watched, status);

alter table market_versions add column title text;
alter table market_versions add column rules_secondary text;

-- Every change of current rules (including A -> B -> A reverts) is logged; never mutated.
create table market_rule_changes (
  change_id integer primary key autoincrement,
  venue text not null,
  market_id text not null,
  from_sha text not null,
  to_sha text not null,
  seen_at text not null,
  foreign key (venue, market_id) references markets(venue, market_id)
);
create index idx_rule_changes_market on market_rule_changes(venue, market_id, change_id);
create trigger market_rule_changes_no_update before update on market_rule_changes
begin select raise(abort, 'append-only table: market_rule_changes'); end;
create trigger market_rule_changes_no_delete before delete on market_rule_changes
begin select raise(abort, 'append-only table: market_rule_changes'); end;

alter table price_snapshots add column yes_bid real;
alter table price_snapshots add column yes_ask real;
alter table price_snapshots add column last_price real;

create table market_tokens (
  venue text not null,
  market_id text not null,
  outcome text not null,
  token_id text not null,
  primary key (venue, market_id, outcome),
  foreign key (venue, market_id) references markets(venue, market_id)
);
