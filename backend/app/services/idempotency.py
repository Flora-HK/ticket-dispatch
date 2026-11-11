import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, select

from app.core.errors import APIError
from app.models import (
    IDEMPOTENCY_RETENTION,
    IdempotencyRecord,
    get_datetime_utc,
)


@dataclass(frozen=True, slots=True)
class IdempotencyReplay:
    """已完成命令的首次响应快照；重放时不得再次写业务数据或成功审计。"""

    status_code: int
    body: dict[str, Any]


@dataclass(frozen=True, slots=True)
class IdempotencyReservation:
    """当前命令的请求哈希，以及可能命中的首次响应。"""

    request_hash: str
    replay: IdempotencyReplay | None = None


def request_hash(payload: dict[str, Any]) -> str:
    """规范化业务载荷后计算哈希，避免键顺序影响同载荷判定。"""

    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _advisory_lock_id(
    *,
    actor_user_id: uuid.UUID,
    command_scope: str,
    idempotency_key: str,
) -> int:
    """把三元作用域压缩成 PostgreSQL 有符号 BIGINT 锁键。"""

    digest = hashlib.sha256(
        f"{actor_user_id}:{command_scope}:{idempotency_key}".encode()
    ).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


def begin_idempotent_command(
    *,
    session: Session,
    actor_user_id: uuid.UUID,
    command_scope: str,
    idempotency_key: str,
    payload: dict[str, Any],
) -> IdempotencyReservation:
    """串行化同一幂等作用域的并发请求并返回可重放结果。"""

    lock_id = _advisory_lock_id(
        actor_user_id=actor_user_id,
        command_scope=command_scope,
        idempotency_key=idempotency_key,
    )
    session.exec(select(func.pg_advisory_xact_lock(lock_id))).one()

    record = session.exec(
        select(IdempotencyRecord)
        .where(
            IdempotencyRecord.actor_user_id == actor_user_id,
            IdempotencyRecord.command_scope == command_scope,
            IdempotencyRecord.idempotency_key == idempotency_key,
        )
        .with_for_update()
    ).first()
    payload_hash = request_hash(payload)
    now = get_datetime_utc()

    if record is not None and record.expires_at > now:
        if record.request_hash != payload_hash:
            raise APIError(
                status_code=409,
                code="IDEMPOTENCY_KEY_CONFLICT",
                message="The idempotency key was already used for another request.",
            )
        return IdempotencyReservation(
            request_hash=payload_hash,
            replay=IdempotencyReplay(
                status_code=record.response_status,
                body=record.response_body,
            ),
        )

    # 过期记录不再承担重放职责，先删除再允许同一键开启新的七天作用域。
    if record is not None:
        session.delete(record)
        session.flush()
    return IdempotencyReservation(request_hash=payload_hash)


def finish_idempotent_command(
    *,
    session: Session,
    actor_user_id: uuid.UUID,
    command_scope: str,
    idempotency_key: str,
    reservation: IdempotencyReservation,
    response_status: int,
    response_body: dict[str, Any],
    resource_type: str,
    resource_id: uuid.UUID,
) -> None:
    """把首次响应与业务写入放在同一事务中，供七天内重试重放。"""

    created_at: datetime = get_datetime_utc()
    session.add(
        IdempotencyRecord(
            actor_user_id=actor_user_id,
            command_scope=command_scope,
            idempotency_key=idempotency_key,
            request_hash=reservation.request_hash,
            response_status=response_status,
            response_body=response_body,
            resource_type=resource_type,
            resource_id=resource_id,
            created_at=created_at,
            expires_at=created_at + IDEMPOTENCY_RETENTION,
        )
    )
