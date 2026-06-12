from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from scripts.build_knowledge_index import build_index

from .config import project_path


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class KnowledgeRecord:
    id: str
    title: str
    tags: list[str]
    text: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class KnowledgeStore:
    def __init__(
        self,
        corpus_path: Path | None = None,
        index_path: Path | None = None,
        backup_root: Path | None = None,
    ) -> None:
        self.corpus_path = corpus_path or project_path("data", "knowledge", "ship_safety_corpus.jsonl")
        self.index_path = index_path or project_path("data", "knowledge", "ship_safety_index.json")
        self.backup_root = backup_root or project_path("results", "runtime", "knowledge_backups")
        self._lock = Lock()
        self.records: list[KnowledgeRecord] = []
        self._load()

    def _load(self) -> None:
        records: list[KnowledgeRecord] = []
        with self.corpus_path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                record = self._normalize_record(payload, record_id=str(payload.get("id", "")).strip(), line_no=line_no)
                records.append(record)
        self.records = records

    def _normalize_record(
        self,
        payload: dict[str, Any],
        *,
        record_id: str,
        line_no: int | None = None,
    ) -> KnowledgeRecord:
        title = str(payload.get("title", "")).strip()
        text = str(payload.get("text", "")).strip()
        tags_raw = payload.get("tags", [])
        if isinstance(tags_raw, str):
            tags = [item.strip() for item in tags_raw.split(",") if item.strip()]
        elif isinstance(tags_raw, list):
            tags = [str(item).strip() for item in tags_raw if str(item).strip()]
        else:
            tags = []
        tags = list(dict.fromkeys(tags))
        if not record_id:
            raise ValueError(f"knowledge record missing id at line {line_no or '?'}")
        if not title:
            raise ValueError(f"knowledge record {record_id} missing title")
        if not text:
            raise ValueError(f"knowledge record {record_id} missing text")
        return KnowledgeRecord(id=record_id, title=title, tags=tags, text=text)

    def list_records(self, *, query: str = "", tag: str = "", limit: int = 100) -> list[dict[str, Any]]:
        query = query.strip().lower()
        tag = tag.strip().lower()
        with self._lock:
            matched = []
            for record in self.records:
                joined_tags = " ".join(record.tags).lower()
                haystack = f"{record.id} {record.title} {record.text} {joined_tags}".lower()
                if query and query not in haystack:
                    continue
                if tag and not any(tag == item.lower() for item in record.tags):
                    continue
                matched.append(
                    {
                        "id": record.id,
                        "title": record.title,
                        "tags": record.tags,
                        "text_preview": self._preview(record.text),
                        "char_count": len(record.text),
                    }
                )
            return matched[:limit]

    def get_record(self, record_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._find(record_id)
            return record.to_dict() if record else None

    def upsert(self, payload: dict[str, Any], *, record_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            resolved_id = record_id or str(payload.get("id", "")).strip() or self.next_id()
            record = self._normalize_record(payload, record_id=resolved_id)
            existing_index = self._find_index(resolved_id)
            if existing_index is None:
                self.records.append(record)
                action = "created"
            else:
                self.records[existing_index] = record
                action = "updated"
            self._save_locked()
            index_info = self._rebuild_index_locked()
            return {
                "ok": True,
                "action": action,
                "record": record.to_dict(),
                "index": index_info,
            }

    def delete(self, record_id: str) -> dict[str, Any]:
        with self._lock:
            existing_index = self._find_index(record_id)
            if existing_index is None:
                raise KeyError(record_id)
            removed = self.records.pop(existing_index)
            self._save_locked()
            index_info = self._rebuild_index_locked()
            return {
                "ok": True,
                "deleted": removed.to_dict(),
                "index": index_info,
            }

    def rebuild_index(self) -> dict[str, Any]:
        with self._lock:
            return self._rebuild_index_locked()

    def summary(self) -> dict[str, Any]:
        with self._lock:
            tag_counts: dict[str, int] = {}
            for record in self.records:
                for tag in record.tags:
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1
            top_tags = sorted(tag_counts.items(), key=lambda item: (-item[1], item[0]))[:12]
            index_mtime = self.index_path.stat().st_mtime if self.index_path.exists() else None
            return {
                "record_count": len(self.records),
                "next_id": self.next_id(),
                "top_tags": [{"tag": tag, "count": count} for tag, count in top_tags],
                "index_path": str(self.index_path),
                "index_updated_at": datetime.fromtimestamp(index_mtime, tz=timezone.utc).isoformat()
                if index_mtime
                else "",
            }

    def next_id(self) -> str:
        numeric_ids = []
        for record in self.records:
            if record.id.startswith("KS") and record.id[2:].isdigit():
                numeric_ids.append(int(record.id[2:]))
        next_number = max(numeric_ids, default=0) + 1
        return f"KS{next_number:03d}"

    def _find(self, record_id: str) -> KnowledgeRecord | None:
        for record in self.records:
            if record.id == record_id:
                return record
        return None

    def _find_index(self, record_id: str) -> int | None:
        for index, record in enumerate(self.records):
            if record.id == record_id:
                return index
        return None

    def _save_locked(self) -> None:
        self.backup_root.mkdir(parents=True, exist_ok=True)
        if self.corpus_path.exists():
            backup_name = f"{self.corpus_path.stem}-{utc_now_iso().replace(':', '-')}.jsonl"
            backup_path = self.backup_root / backup_name
            backup_path.write_text(self.corpus_path.read_text(encoding="utf-8"), encoding="utf-8")
        content = "\n".join(json.dumps(record.to_dict(), ensure_ascii=False) for record in self.records) + "\n"
        self.corpus_path.write_text(content, encoding="utf-8")

    def _rebuild_index_locked(self) -> dict[str, Any]:
        docs = [record.to_dict() for record in self.records]
        index = build_index(docs)
        self.index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "document_count": int(index["document_count"]),
            "updated_at": utc_now_iso(),
            "index_path": str(self.index_path),
        }

    def _preview(self, text: str, limit: int = 90) -> str:
        return text if len(text) <= limit else f"{text[:limit]}..."
