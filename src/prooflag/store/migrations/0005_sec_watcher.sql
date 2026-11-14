-- S4: SEC watcher. Acceptance time (authoritative, from EDGAR) and our detection time are separate.
alter table filings add column detected_at_utc text;      -- NULL for history seen at baseline
alter table filings add column source_url text;           -- filing index page
alter table filings add column discovered_via text;       -- 'submissions' | 'atom'
alter table filings add column primary_document text;
alter table filings add column items text;
alter table filings add column date_basis_differs integer; -- filing date != ET date of acceptance
create index idx_filings_detected on filings(detected_at_utc);

-- CIKs whose filings are polled. Append-only; effective state = latest row (allow / revoke).
create table watch_ciks (
  entry_id integer primary key autoincrement,
  action text not null check (action in ('allow', 'revoke')),
  cik text not null,
  name text not null,
  reason text not null,
  reviewer text not null,
  added_at text not null,
  source text
);
create index idx_watch_ciks_cik on watch_ciks(cik, entry_id);
create trigger watch_ciks_no_update before update on watch_ciks
begin select raise(abort, 'append-only table: watch_ciks'); end;
create trigger watch_ciks_no_delete before delete on watch_ciks
begin select raise(abort, 'append-only table: watch_ciks'); end;
