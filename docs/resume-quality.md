# Resume completeness and final-PDF verification

The default application resume must contain two substantively full, readable pages of supported career evidence. The quality system combines editorial review with a deterministic audit of the actual final PDF. Neither a two-page count nor a reviewer saying a sparse layout improves scanability is sufficient.

## Evidence and authoring contract

Read the full relevant canonical career record, not only the condensed profile. Later explicit user corrections take priority, followed by canonical interview notes, reconciliation decisions, the preserved primary resume, and historical tailored resumes. User-confirmed facts need no independent third-party proof. An uncertain metric restricts that metric while supported leadership actions, responsibilities, decisions, scope, and qualitative outcomes remain usable.

The private content brief includes selected evidence and an evidence reserve with source references, relevance, important compressed context, and specific omission reasons. Author the complete hiring argument before making space-related cuts. Relevant expansion and natural reflow precede cuts; cuts for space require demonstrated rendered overflow. Preserve readable typography and normal spacing. Word counts, bullet counts, and template slots are planning aids, not ceilings. If the full record and real expansion trials expose a fact required to finish, ask precisely for that fact and keep the packet incomplete until resolved.

The operative authoring instructions are [Prepare application](../skills/prepare-application/SKILL.md), [tailoring](../skills/prepare-application/references/tailoring.md), and [page completeness](../skills/prepare-application/references/page-completeness.md).

## Auditable layout contract

| Property | Supported rule |
| --- | --- |
| PDF geometry | Exactly two portrait US Letter pages, 612 by 792 points |
| Body boundaries | Fixed 41.75-point top/bottom boundaries; 36-point horizontal safety bounds |
| Unused page height | Top, bottom, and largest internal body-text gap each at most 38.1 points on each page |
| Bottom position | Final substantive text reaches at least 712.15 points from the top of each page |
| Body type | At least 10 points, median no larger than 14 points, with a separate first-page identity allowance |
| Footer/page number | Excluded from body fullness |
| Freshness | Exact final PDF hash and deterministic measurement must match the quality receipt |

The fixed bounds prevent a caller from declaring larger source-document margins to make an underfilled PDF pass. The threshold measures unused body height, not a percentage of white pixels. Increasing type or spacing, adding filler, or inflating a skills list remains an editorial failure even if measurements pass. Unsupported geometry or extraction failure requires a supported audit implementation before delivery; there is no unchecked override.

## Producer and integration

Use the bundled PDF runtime, or install the optional `pdf` dependency group with `pip install '.[pdf]'`. Run:

```text
python3 scripts/measure_resume_layout.py --pdf <final-resume.pdf> --output <working/receipts/resume_layout.json>
```

The command returns 0 for a passing layout, 1 for a measured quality failure, and 2 for a measurement/dependency error. Insert its entire generated object under `resume_layout` in the existing quality receipt. It binds the policy, schema, actual page count, per-page observations, pass/failure result, and SHA-256 to the rendered PDF.

The packet API requires workspace context when advancing through `quality_checked`, remeasures the real artifact, and rejects a mismatched receipt. Final delivery remeasures again, including resumed packets whose earlier quality stage used older code. Setting every Boolean quality flag to true or using `QualityReceipt.all_passed(...)` cannot establish layout approval. Do not manually construct measurements to match an expected result.

Legacy packets whose original quality receipt predates the `resume_layout` field have a [same-version recovery command](../skills/prepare-application/references/local-delivery-and-optional-export.md#recover-a-legacy-packet-on-the-same-version). It adds an immutable `layout_revalidated` receipt bound to the original complete editorial approval and unchanged final-PDF hashes. It does not advance the stage, change canonical status, approve new content, or waive missing review evidence. Final delivery checks this supplemental measurement against the current PDF independently.

The private final editorial review separately binds the authoring document, final PDF, posting, canonical sources, selected/omitted decisions, and expansion history to paths/hashes. Re-render and review after any content or layout change. The cover letter keeps its existing separate one-page and quality requirements.

## Failure that motivated this change

A prior packet batch contained two-page resumes with about one-third of each usable page left empty. The private measurements flagged the gaps, but review approved them with a generic scanability rationale and treated unspecified additional claims as unverified. The old Boolean receipt accepted that approval. The new instructions require claim-level source review and expansion trials; the final-PDF audit blocks the measured underfill independently of reviewer flags.
