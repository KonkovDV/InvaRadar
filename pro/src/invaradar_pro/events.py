"""Журнал событий: только добавление, цепочка хешей SHA-256.

Каждое событие хранит хеш предыдущего. Если задним числом поменять хоть один байт —
дату, исполнителя, координату, хеш фото, — проверка цепочки укажет первое испорченное событие.
Фото в журнал не кладутся: туда пишется их SHA-256, сами файлы лежат в хранилище.

В промышленной версии голову цепочки (`checkpoint`) раз в сутки подписывают усиленной
квалифицированной электронной подписью (ГОСТ Р 34.10-2012) или ставят метку времени TSP —
тогда подменить журнал целиком тоже нельзя.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

GENESIS = "0" * 64


def canonical(obj) -> bytes:
    """Детерминированный JSON: сортировка ключей, без пробелов, UTF-8."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Event:
    seq: int
    case_id: str
    type: str
    actor: dict
    at: str
    payload: dict
    prev_hash: str
    hash: str = ""

    def body(self) -> dict:
        d = asdict(self)
        d.pop("hash")
        return d

    def compute_hash(self) -> str:
        return sha256_hex(canonical(self.body()))


class EventLog:
    """Журнал в памяти с необязательной записью в JSONL (одна строка — одно событие)."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self._events: list[Event] = []
        if self.path and self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self._events.append(Event(**json.loads(line)))

    def __len__(self) -> int:
        return len(self._events)

    def __iter__(self):
        return iter(self._events)

    @property
    def head(self) -> str:
        return self._events[-1].hash if self._events else GENESIS

    def append(self, case_id: str, type: str, actor: dict, payload: dict, at: str | None = None) -> Event:
        ev = Event(
            seq=len(self._events),
            case_id=case_id,
            type=type,
            actor=json.loads(canonical(actor)),
            at=at or utcnow_iso(),
            payload=json.loads(canonical(payload)),  # то, что хешируем, совпадает с тем, что прочитаем
            prev_hash=self.head,
        )
        ev = replace(ev, hash=ev.compute_hash())
        self._events.append(ev)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(ev), ensure_ascii=False, sort_keys=True) + "\n")
        return ev

    def events(self, case_id: str | None = None) -> list[Event]:
        return [e for e in self._events if case_id is None or e.case_id == case_id]

    def verify(self) -> tuple[bool, int | None]:
        """(True, None), если цепочка цела; иначе (False, номер первого плохого события)."""
        prev = GENESIS
        for i, e in enumerate(self._events):
            if e.seq != i or e.prev_hash != prev or e.compute_hash() != e.hash:
                return False, i
            prev = e.hash
        return True, None

    def checkpoint(self) -> dict:
        """Голова цепочки для внешней подписи или метки времени."""
        return {"seq": len(self._events) - 1, "head": self.head, "at": utcnow_iso()}

    def merkle(self):
        """Дерево Меркла (RFC 9162) над событиями: листья — канонический JSON события с его хешем."""
        from .merkle import MerkleTree
        return MerkleTree([canonical(asdict(e)) for e in self._events])

    def leaf_bytes(self, seq: int) -> bytes:
        return canonical(asdict(self._events[seq]))
