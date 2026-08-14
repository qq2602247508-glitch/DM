# Round LX：Fog Cloud compile-only retention audit

日期：2026-08-14

## Decision

Round LX performs an honest retention audit with no promotion. The candidate is
derived from the current authoritative 26 compile-only IDs, excluding the
already deep-reviewed Sacred Flame and Skywrite IDs. The derived candidate is:

`core-phb-2024:spell:9b29fbb72177f058bf1448ef`（Fog Cloud／云雾术）

Its canonical authored source is bound by content ID, source record ID,
source fingerprint, source checksum, and the single Batch-II authored duplicate.

## Evidence

The source requires all of the following:

- a persistent 20-foot-radius obscuring cloud;
- early termination when strong wind disperses it;
- radius growth for each slot level above first level;
- concentration for up to one hour.

The compiled runtime currently exposes only the concentration block. The
registered consumer is `spell_economy.concentration.v1`; no generic consumer
currently persists the area, consumes environmental termination, or applies
radius scaling. Promotion would therefore be source-incomplete.

## Projection

Authoritative loader-derived projection is unchanged:

`209 production / 26 compile-only / 111 unique compiled`

Set delta is empty: no production ID was added, no compile-only ID was removed,
and the unique compiled set is unchanged.

## Reproduction

The validator is `scripts/validate-round-LX-retention-audit.py`; the report is
`reports/round-LX-retention-audit-2026-08-14.json`. The focused tests assert
dynamic selection, source binding, positive blockers, exact set delta, protected
hashes, and byte-identical report reconstruction.
