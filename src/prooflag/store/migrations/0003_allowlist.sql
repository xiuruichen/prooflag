-- S2 follow-up: curated watch allow-list (append-only) and regex candidate review queue.

-- Entries are never edited or deleted. The effective state of (venue, scope, key) is its latest
-- row: action 'allow' = watched, 'revoke' = not watched.
create table watch_allowlist (
  entry_id integer primary key autoincrement,
  action text not null check (action in ('allow', 'revoke')),
  venue text not null,
  scope text not null check (scope in ('market', 'event', 'series')),
  key text not null,            -- market_id, event_id or series_ticker
  reason text not null,
  reviewer text not null,
  added_at text not null,
  source text                   -- e.g. seed file name
);
create index idx_allowlist_lookup on watch_allowlist(venue, scope, key, entry_id);
create trigger watch_allowlist_no_update before update on watch_allowlist
begin select raise(abort, 'append-only table: watch_allowlist'); end;
create trigger watch_allowlist_no_delete before delete on watch_allowlist
begin select raise(abort, 'append-only table: watch_allowlist'); end;

-- Regex matches are never auto-watched; they wait here for review.
create table watch_candidates (
  venue text not null,
  market_id text not null,
  title text,
  tags text not null,           -- comma-separated tag names
  vol24_usd_est real,
  first_seen_at text not null,
  last_seen_at text not null,
  status text not null default 'pending' check (status in ('pending', 'accepted', 'rejected')),
  primary key (venue, market_id)
);
create index idx_candidates_status on watch_candidates(status, vol24_usd_est);

-- The watch set is now derived from the allow-list: reset the regex-derived sticky flags.
update markets set watched = 0;
