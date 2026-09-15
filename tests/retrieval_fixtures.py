"""Real provider captures for legacy tests that assert completed checkpoints."""
from dataclasses import replace

from career_pipeline import retrieval, review_queue
from career_pipeline.checkpoints import SourceResult


def board_scope(workspace, source, records, now, *, run_id=None):
    scope = retrieval.register_scope(workspace, run_id=run_id or now, source=source,
        provider="greenhouse", query={"board": "example", "employer": "Example Cooperative"}, now=now)
    return retrieval.capture_response(workspace, scope["scope_id"],
        {"jobs": records, "meta": {"total": len(records)}}, now=now)


def completed_board_result(workspace, source, record_id, now, *, cursor=None):
    scope = board_scope(workspace, source, [{"id": record_id, "title": "Operations " + record_id,
        "absolute_url": "https://example.test/jobs/" + record_id,
        "location": {"name": "Remote US"}, "content": "Lead operations and customer workflows."}], now)
    for row in review_queue.next_items(workspace, now=now):
        review_queue.record_decision(workspace, row["review_id"], {"status": "non_match",
            "rationale": "The documented specialist requirements do not match the approved profile.",
            "evidence": [row["posting_url"]]}, expected_revision=row["revision"],
            expected_context=row["expected_context"], now=now)
    return SourceResult(True, now, (record_id,), cursor, tuple(scope["intake_ids"]), (scope["scope_id"],))


def captured_reviewed_item(workspace, item, now):
    candidate = item.candidate
    scope = board_scope(workspace, candidate.source, [{"id": candidate.source_record_id,
        "title": candidate.title, "requisition_id": candidate.requisition_id,
        "absolute_url": candidate.posting_url, "location": {"name": candidate.location},
        "content": item.posting_markdown}], now)
    row = review_queue.next_items(workspace, now=now)[0]
    item = replace(item, candidate=replace(candidate, raw_field_hash=row["raw_field_hash"]))
    review_queue.record_decision(workspace, row["review_id"], {"status": "qualifying",
        "rationale": "The documented operations responsibilities match the approved profile evidence.",
        "evidence": [row["posting_url"]]}, expected_revision=row["revision"],
        expected_context=row["expected_context"], now=now)
    return item, scope
