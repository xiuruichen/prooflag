-- Prooflag schema v1. Timestamps are UTC ISO-8601 text. "append-only" tables reject UPDATE/DELETE.

create table provenance (
  provenance_id integer primary key autoincrement,
  input_hashes_json text not null,
  model_name text,
  model_sha256 text,
  prompt_sha text,
  code_git_sha text not null,
  dirty integer not null check (dirty in (0, 1)),
  created_at text not null
);

create table market_clusters (
  cluster_id text primary key,
  label text,
  rule text,
  created_at text
);

create table markets (
  venue text not null,
  market_id text not null,
  cluster_id text references market_clusters(cluster_id),
  title text,
  rules_text text,
  rules_secondary text,
  resolution_source text,
  close_time_utc text,
  status text,
  raw_json_sha text,
  first_seen_at text not null,
  last_seen_at text not null,
  primary key (venue, market_id)
);
create index idx_markets_status on markets(status);
create index idx_markets_close on markets(close_time_utc);

create table market_versions (
  venue text not null,
  market_id text not null,
  rules_sha text not null,
  rules_text text not null,
  seen_at text not null,
  primary key (venue, market_id, rules_sha),
  foreign key (venue, market_id) references markets(venue, market_id)
);

create table market_tags (
  venue text not null,
  market_id text not null,
  tag text not null,
  reason text not null,
  matched_span text,
  primary key (venue, market_id, tag),
  foreign key (venue, market_id) references markets(venue, market_id)
);

create table price_snapshots (
  venue text not null,
  market_id text not null,
  outcome text not null,
  ts_utc text not null,
  price real,
  volume real,
  open_interest real,
  source text not null check (source in ('snapshot', 'history')),
  primary key (venue, market_id, outcome, ts_utc)
);
create index idx_price_market_ts on price_snapshots(venue, market_id, ts_utc);

create table artifacts (
  sha256 text primary key,
  kind text not null,
  byte_len integer not null,
  path text not null,
  source_url text,
  fetched_at_utc text not null,
  accepted_at_utc text,
  accepted_at_source text,
  normalizer_ver text
);

create table entities (
  entity_id integer primary key autoincrement,
  name text,
  cik text,
  ticker text,
  link_status text not null check (link_status in ('resolved', 'ambiguous', 'unresolved')),
  candidates_json text,
  link_method text
);

create table filings (
  source text not null,
  doc_id text not null,
  cik text,
  form text,
  filed_date text,
  accepted_at_utc text,
  published_at_utc text,
  signing_date text,
  posted_kind text not null check (posted_kind in ('accepted', 'public_inspection', 'published')),
  acceptance_cross_checked integer not null default 0,
  primary_doc_sha text references artifacts(sha256),
  index_sha text,
  primary key (source, doc_id)
);
create index idx_filings_cik_acc on filings(cik, accepted_at_utc);
create index idx_filings_source_form on filings(source, form);

create table rule_specs (
  spec_id integer primary key autoincrement,
  venue text not null,
  market_id text not null,
  rules_sha text not null,
  spec_json text not null,
  valid integer not null check (valid in (0, 1)),
  failed_checks_json text,
  provenance_id integer not null references provenance(provenance_id),
  foreign key (venue, market_id) references markets(venue, market_id)
);
create index idx_specs_market on rule_specs(venue, market_id, spec_id);

create table evaluations (
  eval_id integer primary key autoincrement,
  spec_id integer not null references rule_specs(spec_id),
  source text not null,
  doc_id text not null,
  doc_sha text not null,
  llm_output_sha text,
  decision text not null check (decision in ('yes', 'no', 'unclear')),
  gate_json text not null,
  final_decision text not null check (final_decision in ('yes', 'no', 'unclear')),
  provenance_id integer not null references provenance(provenance_id)
);
create index idx_eval_spec_doc on evaluations(spec_id, source, doc_id);

create table llm_calls (
  call_id integer primary key autoincrement,
  input_sha text not null,
  model_name text not null,
  model_file_sha256 text not null,
  prompt_tmpl_sha text not null,
  params_json text not null,
  output_text text not null,
  output_sha text not null,
  latency_ms integer,
  created_at text not null,
  unique (input_sha, model_file_sha256, prompt_tmpl_sha, params_json)
);

create table signals (
  signal_id integer primary key autoincrement,
  type text not null check (type in ('evidence_gap', 'deadline_risk', 'ambiguity')),
  venue text not null,
  market_id text not null,
  eval_id integer references evaluations(eval_id),
  spec_id integer references rule_specs(spec_id),
  source text,
  doc_id text,
  rules_sha text not null,
  dedupe_key text not null unique,
  variant text,
  shadow integer not null default 0 check (shadow in (0, 1)),
  price_at_signal real,
  status text not null,
  created_at text not null
);
create index idx_signals_type_market on signals(type, venue, market_id);

create table signal_events (
  event_id integer primary key autoincrement,
  signal_id integer references signals(signal_id),
  ts text not null,
  event text not null,
  reason text
);

create table outcomes (
  signal_id integer not null references signals(signal_id),
  horizon text not null check (horizon in ('1h', '6h', 'settle')),
  price real,
  resolved_value text,
  recorded_at text not null,
  primary key (signal_id, horizon)
);

create table reviews (
  signal_id integer not null references signals(signal_id),
  reviewer text not null,
  ts text not null,
  label text not null check (label in ('correct', 'incorrect', 'ambiguous')),
  note text,
  primary key (signal_id, reviewer, ts)
);

create table poll_log (
  id integer primary key autoincrement,
  source text not null,
  ts text not null,
  ok integer not null,
  latency_ms integer,
  items integer,
  err text
);

create table labels_raw (
  label_id integer primary key autoincrement,
  item_kind text not null check (item_kind in ('rule', 'pair')),
  item_id text not null,
  labeler text not null,
  persona text,
  model text not null,
  value_json text not null,
  spans_json text not null,
  reason text,
  spans_valid integer not null check (spans_valid in (0, 1)),
  provenance_id integer not null references provenance(provenance_id),
  created_at text not null
);
create index idx_labels_item on labels_raw(item_kind, item_id);

create table label_consensus (
  consensus_id integer primary key autoincrement,
  item_kind text not null check (item_kind in ('rule', 'pair')),
  item_id text not null,
  status text not null check (status in ('ai_consensus', 'ai_adjudicated', 'contested')),
  value_json text not null,
  agreement_pattern text not null,
  adjudication_notes text,
  split text check (split in ('dev', 'test')),
  provenance_id integer not null references provenance(provenance_id),
  created_at text not null
);
create index idx_consensus_item on label_consensus(item_kind, item_id);

-- Append-only enforcement.
create trigger market_versions_no_update before update on market_versions
begin select raise(abort, 'append-only table: market_versions'); end;
create trigger market_versions_no_delete before delete on market_versions
begin select raise(abort, 'append-only table: market_versions'); end;

create trigger price_snapshots_no_update before update on price_snapshots
begin select raise(abort, 'append-only table: price_snapshots'); end;
create trigger price_snapshots_no_delete before delete on price_snapshots
begin select raise(abort, 'append-only table: price_snapshots'); end;

create trigger artifacts_no_update before update on artifacts
begin select raise(abort, 'append-only table: artifacts'); end;
create trigger artifacts_no_delete before delete on artifacts
begin select raise(abort, 'append-only table: artifacts'); end;

create trigger rule_specs_no_update before update on rule_specs
begin select raise(abort, 'append-only table: rule_specs'); end;
create trigger rule_specs_no_delete before delete on rule_specs
begin select raise(abort, 'append-only table: rule_specs'); end;

create trigger evaluations_no_update before update on evaluations
begin select raise(abort, 'append-only table: evaluations'); end;
create trigger evaluations_no_delete before delete on evaluations
begin select raise(abort, 'append-only table: evaluations'); end;

create trigger llm_calls_no_update before update on llm_calls
begin select raise(abort, 'append-only table: llm_calls'); end;
create trigger llm_calls_no_delete before delete on llm_calls
begin select raise(abort, 'append-only table: llm_calls'); end;

create trigger signal_events_no_update before update on signal_events
begin select raise(abort, 'append-only table: signal_events'); end;
create trigger signal_events_no_delete before delete on signal_events
begin select raise(abort, 'append-only table: signal_events'); end;

create trigger provenance_no_update before update on provenance
begin select raise(abort, 'append-only table: provenance'); end;
create trigger provenance_no_delete before delete on provenance
begin select raise(abort, 'append-only table: provenance'); end;

create trigger labels_raw_no_update before update on labels_raw
begin select raise(abort, 'append-only table: labels_raw'); end;
create trigger labels_raw_no_delete before delete on labels_raw
begin select raise(abort, 'append-only table: labels_raw'); end;

create trigger label_consensus_no_update before update on label_consensus
begin select raise(abort, 'append-only table: label_consensus'); end;
create trigger label_consensus_no_delete before delete on label_consensus
begin select raise(abort, 'append-only table: label_consensus'); end;
