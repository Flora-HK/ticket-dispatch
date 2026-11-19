"""自动与人工派发策略的纯函数测试。"""

import uuid
from datetime import UTC, datetime

from app.services.dispatch_strategy import (
    DispatchCandidateData,
    LeastOpenTicketStrategy,
    ManualDispatchStrategy,
)


def test_least_open_ticket_strategy_uses_all_tie_breakers() -> None:
    candidates = (
        DispatchCandidateData(
            handler_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            open_ticket_count=1,
            last_assigned_at=None,
        ),
        DispatchCandidateData(
            handler_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
            open_ticket_count=0,
            last_assigned_at=datetime(2026, 1, 2, tzinfo=UTC),
        ),
        DispatchCandidateData(
            handler_id=uuid.UUID("00000000-0000-0000-0000-000000000004"),
            open_ticket_count=0,
            last_assigned_at=None,
        ),
        DispatchCandidateData(
            handler_id=uuid.UUID("00000000-0000-0000-0000-000000000003"),
            open_ticket_count=0,
            last_assigned_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        DispatchCandidateData(
            handler_id=uuid.UUID("00000000-0000-0000-0000-000000000005"),
            open_ticket_count=0,
            last_assigned_at=None,
        ),
    )

    decision = LeastOpenTicketStrategy().choose(candidates)

    assert decision.selected_handler_id == uuid.UUID(
        "00000000-0000-0000-0000-000000000004"
    )
    assert [item.handler_id.int for item in decision.ranked_candidates] == [
        4,
        5,
        3,
        2,
        1,
    ]
    assert decision.strategy_code == "LEAST_OPEN_TICKET"
    assert decision.strategy_version == "v1"


def test_least_open_ticket_strategy_returns_stable_empty_result() -> None:
    decision = LeastOpenTicketStrategy().choose(())

    assert decision.selected_handler_id is None
    assert decision.reason_code == "NO_ELIGIBLE_HANDLER"
    assert decision.ranked_candidates == ()


def test_manual_strategy_requires_requested_handler_in_candidates() -> None:
    first = DispatchCandidateData(
        handler_id=uuid.uuid4(),
        open_ticket_count=1,
        last_assigned_at=None,
    )
    second = DispatchCandidateData(
        handler_id=uuid.uuid4(),
        open_ticket_count=0,
        last_assigned_at=None,
    )

    selected = ManualDispatchStrategy().choose(first.handler_id, (first, second))
    missing = ManualDispatchStrategy().choose(uuid.uuid4(), (first, second))

    assert selected.selected_handler_id == first.handler_id
    assert selected.strategy_code == "MANUAL"
    assert missing.selected_handler_id is None
    assert missing.reason_code == "HANDLER_NOT_ELIGIBLE"
