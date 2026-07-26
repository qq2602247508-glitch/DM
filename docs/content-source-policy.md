# Content source and provenance policy

This project can create a **local-only generated corpus** from an explicit Git
snapshot, local checkout, or bounded fallback access to
`https://5echm.kagangtuya.top/`. Generated checkouts, HTML, Markdown, JSON,
manifests, and reports are ignored by Git and must not be committed, published,
or redistributed.

The target is a WinCHM static site. Its introduction links to repositories in
the `DND5eChm` organization. Repository declarations differ:

- `DND5eChm/5echm_web` uses branch `pages` and is a site-equivalent UTF-8 HTML
  snapshot, but the repository has no separately
  declared license (`unknown` is recorded).
- `DND5eChm/DND5e_chm` uses branch `main`, declares GPL-3.0, and is the
  explicitly selected production source.
- `DND5eChm/SRD5.2Chm` uses branch `main` and declares CC-BY-4.0.

No repository license is assumed to cover every underlying official or
third-party text. Every normalized record retains repository URL, exact commit
SHA, requested branch/ref, checkout-relative path, declared/unknown license,
mapped canonical website URL, source book, edition, officiality, legacy status,
checksum, parser/schema version, and warnings.

## Preferred snapshot workflow

- Repository download/update is an explicit CLI operation. The application
  never clones or updates content during startup.
- Clone uses a single branch, shallow history, and blob filtering where the
  server supports it. The two main/web repositories are roughly 281–290 MB and
  must not be fetched merely for a smoke test.
- `SRD5.2Chm` (roughly 12 MB), an existing checkout, or the synthetic fixture is
  preferred for small validation. Full production ingestion uses the explicitly
  cloned `DND5e_chm/main` snapshot. Generic `import-local` supports other
  authorized checkouts.
- A run is pinned to an exact 40-character commit SHA. Updates create a new
  explicitly selected snapshot/run; they are never silently substituted.

## Website fallback boundary

- The default allow-list contains only the exact host
  `5echm.kagangtuya.top`. Only HTTP and HTTPS are accepted.
- Credentials, non-default ports, path traversal, executable/data schemes,
  off-host redirects, and oversized responses are rejected.
- Every live command fetches and evaluates `/robots.txt` before content.
  `404` means that no policy was published at that location; it is recorded and
  is not treated as a general license. Any other fetch error, malformed redirect,
  explicit disallow, `401`, or `403` fails closed.
- Defaults are one request at a time, at least one second between requests,
  finite retries, finite response sizes, and a finite page limit.
- Placeholder navigation links such as `href="#"` are discovery records but are
  never fetched.
- Offline fixture mode does not access the network and is the normal development
  and test path.

## Classification boundary

The corpus mixes 2014, 2024, 2025, Legacy, supplements, and third-party content.
Classification uses explicit markers with deterministic evidence precedence:
entity title and filename, immediate semantic category/navigation parent, then
broad book/path ancestors. Equal-strength conflicting evidence produces
`unknown`; body prose is never used to guess a type. The pipeline never labels
the whole source as current official rules. Structured fields are extracted
only from visible source evidence and remain null with warnings when absent.

Source HTML is untrusted data. Scripts, styles, embedded commands, and UI noise
are discarded and never executed. Phase 2 performs no embedding, vector
indexing, RAG answering, or database import.
