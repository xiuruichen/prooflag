# Public-safety audit

Scope: all 22 commits on every branch (`git log -p --all`, no stashes exist), the current tree (197 tracked files, including the decompressed `studies/e1/inputs/*.json.gz`), and `.gitignore` coverage. Run before the cleanup commits; the commit that adds this file also fixes the working tree.

## Result: ONE leak in history

| # | Severity | Where | What | Status |
|---|---|---|---|---|
| 1 | **HIGH** | Author and committer metadata of all 22 commits (e.g. `61e0bee`, `e0b03c9`, first commit) | A personal Gmail address in `Author:` / `Committer:` | **Cannot be fixed without rewriting history.** Publish via a fresh repository (see below) |
| 2 | LOW | `PLAN.md` line 18 in history (`git log -p`, every commit that touched it) | Windows account name inside a path (`C:\Users\<name>`) | Removed from the working tree. Remains in history |
| 3 | INFO | `tests/` and history | Only `example.org` / `example.com` placeholder addresses in tests | No action |
| 4 | INFO | `studies/e1/inputs/edgar_ipo_check.json.gz`, `tests/fixtures/sec/*.xml` | `webmaster@sec.gov` (SEC's public address in a feed) | No action |

## Clean
- The SEC contact address (`PROOFLAG_CONTACT_EMAIL`) was never committed: no hits in any commit or in the tree.
- No API keys, tokens, passwords or bearer strings (the word `token` appears only in code identifiers).
- Nothing under `data/`, no `*.db`, `*.log`, `.env`, `*.bundle`, binaries. The only compressed files are the study inputs `studies/e1/inputs/*.json.gz` (venue and Federal Register data; 0x… strings in them are public Polymarket market ids, wallet fields were discarded at ingest).
- Largest tracked files: `kalshi_trades.json.gz` 2.5 MB, `ipo_cluster.json.gz` 0.56 MB.

## Recommendation
Publish a **fresh repository containing one squashed snapshot** of the cleaned tree, committed with a no-reply author, instead of making the current repository public. History is not rewritten here. The existing private repository stays untouched. The snapshot loses the commit log, which `docs/dev-history/` partially replaces, and the pre-registration timestamp: `studies/WRITEUP.md` cites the original commit hash and date, and the original private repository must be kept so that claim can be verified (for example by making it public later, or by publishing `git bundle` / `git log` output).

## `.gitignore`
Now covers `.env` (and `.env.*` except `.env.example`), `data/`, `*.db`, `*.db-wal`, `*.db-shm`, `*.sqlite*`, `*.log`, `.uv-cache/`, `model.lock`, and tool caches. Verified with `git check-ignore`.
