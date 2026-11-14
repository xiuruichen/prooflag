-- S3: entity linking. Each distinct query (name or ticker) is recorded once with its status.
alter table entities add column query text;
alter table entities add column updated_at text;
create unique index idx_entities_query on entities(query);
create index idx_entities_status on entities(link_status);

-- Reviewed aliases (e.g. former names) that override the SEC file. Append-only; the effective
-- state of an alias is its latest row (allow / revoke).
create table entity_aliases (
  alias_id integer primary key autoincrement,
  action text not null check (action in ('allow', 'revoke')),
  alias_norm text not null,
  alias_raw text not null,
  cik text not null,
  name text not null,
  reason text not null,
  reviewer text not null,
  added_at text not null,
  source text
);
create index idx_entity_aliases_norm on entity_aliases(alias_norm, alias_id);
create trigger entity_aliases_no_update before update on entity_aliases
begin select raise(abort, 'append-only table: entity_aliases'); end;
create trigger entity_aliases_no_delete before delete on entity_aliases
begin select raise(abort, 'append-only table: entity_aliases'); end;
