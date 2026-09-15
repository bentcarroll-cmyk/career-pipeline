# Two substantively full resume pages

Use the available two pages for relevant, supported evidence at the approved readable typography and normal margins. The one-page cover letter has separate layout requirements. Fullness measures usable body space, excluding margins and page numbers; it is not an ink-coverage quota.

## Render and measure before cutting

1. Begin with natural text flow. Remove premature manual page breaks and blank paragraphs. Keep a role heading with its first substantive paragraph, not the whole multi-bullet role. A role can continue between complete bullets; follow the verified ATS's continuation rules.
2. Render at the approved typography within the supported PDF geometry: portrait US Letter (612 by 792 points), with fixed 41.75-point top/bottom body boundaries and 36-point horizontal safety bounds. The audit reads actual PDF text positions against these fixed bounds; a caller cannot enlarge margins to hide available capacity. Footer/page-number text does not count as body content. Other geometry requires supported measurement implementation before delivery.
3. Both pages must have no more than **38.1 points (about 0.53 inches)** of unused writable top or bottom height and no internal body-text gap above that threshold. With the fixed body floor at 750.25 points, the final substantive body text must reach at least 712.15 points from the top. A full first page does not compensate for a sparse second page. Resolve failed or unsupported measurements before approval.

This is a blocking default delivery condition. Generic claims about scanability, brevity, aesthetics, role boundaries, or unavailable evidence cannot waive it. A reviewer `pass`, `page_space: true`, or an all-passed helper does not override measured failure. Even below the threshold, include a worthwhile supported addition when it improves the hiring case and fits.

## Expand and reflow

For each flagged page, work through the evidence reserve from [tailoring](tailoring.md):

1. Restore the strongest relevant omission or meaningful context to a compressed accomplishment. Explain the user's decision, leadership action, adoption mechanism, scope, or supported result. Preserve qualifiers and accurate attribution.
2. Correct forced breaks and keep settings, then reflow the entire document in chronology. Avoid simply appending older work to page 2 or moving the same gap between pages.
3. Render again and measure both pages. Record the addition, expansion, or movement, its source, the actual effect on fit, and whether retained. If the strongest addition overflows, try concise wording or the next useful candidate. Use actual paragraph and heading costs, not a guessed line budget.
4. If the draft exceeds two pages, improve flow and remove repetition before cutting the weakest evidence. Render again after cuts; stop trimming when useful capacity returns.

Preserve readable type and ordinary spacing. The supported audit requires body text of at least 10 points and median body type no larger than 14 points, with an allowance for the first-page identity. Increasing fonts, leading, paragraph spacing, or margins to disguise underfill does not satisfy this gate even when a numeric font limit permits it. Neither does adding filler, repeating metrics, inflating skills lists, or pushing an isolated line toward the footer. Do not shrink approved body type to pack in more content. The evidence and reflow must do the work.

## When a fact is genuinely missing

First retrieve the full relevant canonical sources and use already-confirmed facts or narrower supported wording. Only then ask a targeted question identifying the exact missing contribution, scope, outcome, or qualifier needed. Do not ask the user to reconfirm facts already established. Keep the packet incomplete if those answers are necessary to produce a full, supported resume; report the specific gap and retain the draft while other work continues. The user can explicitly change the requested document scope, but neither the author nor reviewer may silently lower the default gate.

## Retain the final evidence

Keep under `working/` the source coverage and evidence reserve, actual rendered trial measurements, revision history, final page renders, and the final editorial review. Bind the quality evidence to the exact final resume PDF, authoring document, posting, and career-source hashes. Any content or layout edit invalidates the previous artifact review.

Immediately before delivery, measure the actual final PDF again and check its hash against the approved quality evidence. A narrative explanation or historical receipt cannot replace fresh measurement. Use the deterministic packet audit described in [quality gates](quality-gates.md); finalization must reject missing, stale, or failing measurements even when every Boolean quality flag is true.
