# Round XLVII：Longstrider promotion repair

日期：2026-08-13。

## Decision

Promotion withdrawn. Longstrider remains `compile-only`: the authoritative
production evidence union does not contain its ID, and the planner has not
accepted promotion.

## Evidence

The authored and compiled IR is source-bound and compiles full. The runtime
consumer is generic `spell.timed_modifier.v1`; the source text does not itself
state non-stacking, so replacement relies only on the authoritative general
typed timed-modifier seam and is separately recorded as such.

Authoritative projection remains `203 production / 35 compile-only / 111 unique
compiled`; no arithmetic delta was used. Behavioral coverage is derived from
named pytest node return codes; unsupported claims remain `false`, yielding
`promotion_decision=withdraw`.

Focused suite: `22 passed`. The compiled Longstrider JSON has one
`evidence_ref` per object. Historical XLIII report was restored byte-for-byte:
SHA-256 `98718564dab7e41bb911b2d10813cb43bf59b422732ec67480b4e362e519c76f`.

No push.
