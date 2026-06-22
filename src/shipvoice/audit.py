from __future__ import annotations

import json
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from .models import AuditRecord


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class AuditStore:
    def __init__(self, root: Path, *, max_records: int = 200, max_per_session: int = 30) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.audit_path = self.root / "session_audit.jsonl"
        self._recent: deque[AuditRecord] = deque(maxlen=max_records)
        self._by_session: dict[str, deque[AuditRecord]] = defaultdict(lambda: deque(maxlen=max_per_session))
        self._lock = Lock()
        self._load_existing()

    def _load_existing(self) -> None:
        if not self.audit_path.exists():
            return
        with self.audit_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                    record = AuditRecord(**payload)
                except (json.JSONDecodeError, TypeError):
                    continue
                self._recent.appendleft(record)
                self._by_session[record.session_id].appendleft(record)

    def append(self, record: AuditRecord) -> None:
        with self._lock:
            self._recent.appendleft(record)
            self._by_session[record.session_id].appendleft(record)
            with self.audit_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")

    def recent_runs(self, limit: int = 20) -> list[dict[str, object]]:
        with self._lock:
            return [record.to_dict() for record in list(self._recent)[:limit]]

    def session_runs(self, session_id: str, limit: int = 20) -> list[dict[str, object]]:
        with self._lock:
            return [record.to_dict() for record in list(self._by_session.get(session_id, []))[:limit]]

    def session_summaries(self, limit: int = 12) -> list[dict[str, object]]:
        summaries: list[dict[str, object]] = []
        with self._lock:
            for session_id, records in self._by_session.items():
                if not records:
                    continue
                latest = records[0]
                summaries.append(
                    {
                        "session_id": session_id,
                        "runs": len(records),
                        "last_run_id": latest.run_id,
                        "last_status": latest.status,
                        "last_question": latest.question,
                        "last_created_at": latest.created_at,
                        "last_gate_label": latest.gate_label,
                        "last_total_ms": latest.metrics.get("total_ms", ""),
                    }
                )
        summaries.sort(key=lambda item: str(item["last_created_at"]), reverse=True)
        return summaries[:limit]

    def total_runs(self) -> int:
        with self._lock:
            return len(self._recent)

    def search_runs(
        self,
        *,
        query: str = "",
        status: str = "",
        gate_label: str = "",
        limit: int = 50,
    ) -> list[dict[str, object]]:
        query = query.strip().lower()
        status = status.strip().lower()
        gate_label = gate_label.strip().lower()
        with self._lock:
            matched: list[dict[str, object]] = []
            for record in self._recent:
                haystack = " ".join(
                    [
                        record.run_id,
                        record.session_id,
                        record.question,
                        record.transcript,
                        record.answer_preview,
                        record.error,
                    ]
                ).lower()
                if query and query not in haystack:
                    continue
                if status and record.status.lower() != status:
                    continue
                if gate_label and str(record.gate_label).lower() != gate_label:
                    continue
                matched.append(record.to_dict())
            return matched[:limit]

    def stats(self) -> dict[str, object]:
        with self._lock:
            records = list(self._recent)
        total = len(records)
        error_runs = sum(1 for item in records if item.status == "error")
        blocked_runs = sum(1 for item in records if item.gate_allowed is False)
        total_ms_values = [
            int(item.metrics.get("total_ms", 0))
            for item in records
            if isinstance(item.metrics, dict) and item.metrics.get("total_ms") not in {"", None}
        ]
        avg_total_ms = round(sum(total_ms_values) / len(total_ms_values), 2) if total_ms_values else 0
        return {
            "total_runs": total,
            "error_runs": error_runs,
            "blocked_runs": blocked_runs,
            "ok_runs": total - error_runs,
            "avg_total_ms": avg_total_ms,
        }
