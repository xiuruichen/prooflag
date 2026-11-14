# Security

Prooflag is a research tool that makes read-only requests to public APIs. It holds no credentials other than a contact email used in the SEC `User-Agent`, which lives in `.env` and is redacted from logs and stored provenance.

To report a vulnerability or an accidental secret in the repository, use GitHub's private vulnerability reporting (Security tab, "Report a vulnerability") rather than a public issue. Expect a best-effort reply; this is not a maintained service.

The code contains no order-placement functionality and must not gain any.
