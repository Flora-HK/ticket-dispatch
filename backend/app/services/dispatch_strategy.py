from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

StrategyCode = Literal["MANUAL", "LEAST_OPEN_TICKET"]


@dataclass(frozen=True, slots=True)
class DispatchCandidateData:
    """策略输入与数据库 Session 解耦，便于纯函数验证排序。"""

    handler_id: UUID
    open_ticket_count: int
    last_assigned_at: datetime | None


@dataclass(frozen=True, slots=True)
class DispatchDecision:
    selected_handler_id: UUID | None
    reason_code: str
    strategy_code: StrategyCode
    strategy_version: str
    ranked_candidates: tuple[DispatchCandidateData, ...]


class DispatchStrategy(Protocol):
    strategy_code: StrategyCode
    strategy_version: str

    def choose(
        self,
        candidates: tuple[DispatchCandidateData, ...],
    ) -> DispatchDecision: ...


class ManualDispatchStrategy:
    strategy_code: StrategyCode = "MANUAL"
    strategy_version = "v1"

    def choose(
        self,
        requested_handler_id: UUID,
        candidates: tuple[DispatchCandidateData, ...],
    ) -> DispatchDecision:
        selected = next(
            (
                item
                for item in candidates
                if item.handler_id == requested_handler_id
            ),
            None,
        )
        return DispatchDecision(
            selected_handler_id=(
                selected.handler_id if selected is not None else None
            ),
            reason_code=(
                "SELECTED" if selected is not None else "HANDLER_NOT_ELIGIBLE"
            ),
            strategy_code=self.strategy_code,
            strategy_version=self.strategy_version,
            ranked_candidates=candidates,
        )


class LeastOpenTicketStrategy:
    strategy_code: StrategyCode = "LEAST_OPEN_TICKET"
    strategy_version = "v1"

    @staticmethod
    def _sort_key(candidate: DispatchCandidateData) -> tuple[object, ...]:
        null_rank = 0 if candidate.last_assigned_at is None else 1
        last_assigned_key = (
            datetime.min.replace(tzinfo=None)
            if candidate.last_assigned_at is None
            else candidate.last_assigned_at
        )
        return (
            candidate.open_ticket_count,
            null_rank,
            last_assigned_key,
            str(candidate.handler_id),
        )

    def choose(
        self,
        candidates: tuple[DispatchCandidateData, ...],
    ) -> DispatchDecision:
        ranked = tuple(sorted(candidates, key=self._sort_key))
        selected = ranked[0].handler_id if ranked else None
        return DispatchDecision(
            selected_handler_id=selected,
            reason_code="SELECTED" if selected is not None else "NO_ELIGIBLE_HANDLER",
            strategy_code=self.strategy_code,
            strategy_version=self.strategy_version,
            ranked_candidates=ranked,
        )
