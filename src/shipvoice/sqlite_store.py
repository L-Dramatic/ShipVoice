from __future__ import annotations

import csv
import json
import sqlite3
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from scripts.build_knowledge_index import build_index

from .config import project_path
from .models import AuditRecord


KNOWLEDGE_STATUSES = (
    "draft",
    "in_review",
    "approved",
    "changes_requested",
    "archived",
)

RUN_CASE_STATUSES = (
    "open",
    "investigating",
    "resolved",
    "accepted_risk",
    "ignored",
)

RUN_CASE_SEVERITIES = (
    "low",
    "medium",
    "high",
    "critical",
)

RUN_CASE_TYPES = (
    "normal",
    "safety_gate",
    "error",
    "latency",
    "quality",
    "asr",
    "llm",
    "tts",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class SQLiteAppStore:
    def __init__(
        self,
        db_path: Path | None = None,
        *,
        corpus_path: Path | None = None,
        index_path: Path | None = None,
        audit_log_path: Path | None = None,
        backup_root: Path | None = None,
    ) -> None:
        self.db_path = db_path or project_path("results", "runtime", "shipvoice.db")
        self.corpus_path = corpus_path or project_path("data", "knowledge", "ship_safety_corpus.jsonl")
        self.index_path = index_path or project_path("data", "knowledge", "ship_safety_index.json")
        self.audit_log_path = audit_log_path or project_path("results", "runtime", "session_audit.jsonl")
        self.backup_root = backup_root or project_path("results", "runtime", "knowledge_backups")
        self._lock = Lock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._bootstrap_if_needed()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS knowledge_records (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    text TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'approved',
                    owner TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT '',
                    review_notes TEXT NOT NULL DEFAULT '',
                    last_reviewer TEXT NOT NULL DEFAULT '',
                    last_reviewed_at TEXT NOT NULL DEFAULT '',
                    current_version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS knowledge_versions (
                    record_id TEXT NOT NULL,
                    version_no INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    change_note TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    PRIMARY KEY (record_id, version_no)
                );

                CREATE TABLE IF NOT EXISTS run_audits (
                    run_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    question TEXT NOT NULL,
                    transcript TEXT NOT NULL,
                    gate_label TEXT NOT NULL,
                    gate_allowed INTEGER,
                    answer_preview TEXT NOT NULL,
                    providers_json TEXT NOT NULL,
                    metrics_json TEXT NOT NULL,
                    error TEXT NOT NULL,
                    evidence_titles_json TEXT NOT NULL,
                    audio_name TEXT NOT NULL,
                    case_status TEXT NOT NULL DEFAULT 'resolved',
                    case_severity TEXT NOT NULL DEFAULT 'low',
                    case_type TEXT NOT NULL DEFAULT 'normal',
                    case_owner TEXT NOT NULL DEFAULT '',
                    case_note TEXT NOT NULL DEFAULT '',
                    case_reviewer TEXT NOT NULL DEFAULT '',
                    case_reviewed_at TEXT NOT NULL DEFAULT '',
                    case_updated_at TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS evaluation_datasets (
                    dataset_name TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    row_count INTEGER NOT NULL,
                    imported_at TEXT NOT NULL,
                    summary_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS evaluation_rows (
                    dataset_name TEXT NOT NULL,
                    row_key TEXT NOT NULL,
                    row_index INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (dataset_name, row_key)
                );

                CREATE TABLE IF NOT EXISTS admin_jobs (
                    job_id TEXT PRIMARY KEY,
                    job_type TEXT NOT NULL,
                    label TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    error TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL
                );
                """
            )
            self._ensure_knowledge_schema(conn)
            self._ensure_run_case_schema(conn)

    def _ensure_knowledge_schema(self, conn: sqlite3.Connection) -> None:
        columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(knowledge_records)").fetchall()}
        required_columns = {
            "status": "TEXT NOT NULL DEFAULT 'approved'",
            "owner": "TEXT NOT NULL DEFAULT ''",
            "source": "TEXT NOT NULL DEFAULT ''",
            "review_notes": "TEXT NOT NULL DEFAULT ''",
            "last_reviewer": "TEXT NOT NULL DEFAULT ''",
            "last_reviewed_at": "TEXT NOT NULL DEFAULT ''",
            "current_version": "INTEGER NOT NULL DEFAULT 1",
        }
        for column_name, column_spec in required_columns.items():
            if column_name not in columns:
                conn.execute(f"ALTER TABLE knowledge_records ADD COLUMN {column_name} {column_spec}")
        conn.execute("UPDATE knowledge_records SET status = COALESCE(NULLIF(status, ''), 'approved')")
        conn.execute("UPDATE knowledge_records SET owner = COALESCE(owner, '')")
        conn.execute("UPDATE knowledge_records SET source = COALESCE(source, '')")
        conn.execute("UPDATE knowledge_records SET review_notes = COALESCE(review_notes, '')")
        conn.execute("UPDATE knowledge_records SET last_reviewer = COALESCE(last_reviewer, '')")
        conn.execute("UPDATE knowledge_records SET last_reviewed_at = COALESCE(last_reviewed_at, '')")
        conn.execute("UPDATE knowledge_records SET current_version = COALESCE(current_version, 1)")
        conn.commit()

    def _ensure_run_case_schema(self, conn: sqlite3.Connection) -> None:
        columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(run_audits)").fetchall()}
        required_columns = {
            "case_status": "TEXT NOT NULL DEFAULT 'resolved'",
            "case_severity": "TEXT NOT NULL DEFAULT 'low'",
            "case_type": "TEXT NOT NULL DEFAULT 'normal'",
            "case_owner": "TEXT NOT NULL DEFAULT ''",
            "case_note": "TEXT NOT NULL DEFAULT ''",
            "case_reviewer": "TEXT NOT NULL DEFAULT ''",
            "case_reviewed_at": "TEXT NOT NULL DEFAULT ''",
            "case_updated_at": "TEXT NOT NULL DEFAULT ''",
        }
        for column_name, column_spec in required_columns.items():
            if column_name not in columns:
                conn.execute(f"ALTER TABLE run_audits ADD COLUMN {column_name} {column_spec}")
        rows = conn.execute("SELECT * FROM run_audits").fetchall()
        for row in rows:
            inferred = self._infer_run_case_fields(row)
            conn.execute(
                """
                UPDATE run_audits
                SET case_status = CASE WHEN COALESCE(case_updated_at, '') = '' THEN ? ELSE COALESCE(NULLIF(case_status, ''), ?) END,
                    case_severity = CASE WHEN COALESCE(case_updated_at, '') = '' THEN ? ELSE COALESCE(NULLIF(case_severity, ''), ?) END,
                    case_type = CASE WHEN COALESCE(case_updated_at, '') = '' THEN ? ELSE COALESCE(NULLIF(case_type, ''), ?) END,
                    case_owner = COALESCE(case_owner, ''),
                    case_note = COALESCE(case_note, ''),
                    case_reviewer = COALESCE(case_reviewer, ''),
                    case_reviewed_at = COALESCE(case_reviewed_at, ''),
                    case_updated_at = COALESCE(NULLIF(case_updated_at, ''), ?)
                WHERE run_id = ?
                """,
                (
                    inferred["case_status"],
                    inferred["case_status"],
                    inferred["case_severity"],
                    inferred["case_severity"],
                    inferred["case_type"],
                    inferred["case_type"],
                    utc_now_iso(),
                    row["run_id"],
                ),
            )
        conn.commit()

    def _bootstrap_if_needed(self) -> None:
        with self._lock:
            with self._connect() as conn:
                knowledge_count = int(conn.execute("SELECT COUNT(*) FROM knowledge_records").fetchone()[0])
                if knowledge_count == 0 and self.corpus_path.exists():
                    self._import_corpus_locked(conn)
                    knowledge_count = int(conn.execute("SELECT COUNT(*) FROM knowledge_records").fetchone()[0])
                if knowledge_count > 0:
                    self._backfill_knowledge_versions_locked(conn)
                audit_count = int(conn.execute("SELECT COUNT(*) FROM run_audits").fetchone()[0])
                if audit_count == 0 and self.audit_log_path.exists():
                    self._import_audit_log_locked(conn)
                evaluation_count = int(conn.execute("SELECT COUNT(*) FROM evaluation_datasets").fetchone()[0])
                if evaluation_count == 0:
                    self._import_evaluation_datasets_locked(conn)
                conn.commit()

    def _import_corpus_locked(self, conn: sqlite3.Connection) -> None:
        now = utc_now_iso()
        with self.corpus_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                item = json.loads(line)
                conn.execute(
                    """
                    INSERT OR REPLACE INTO knowledge_records (
                        id, title, tags_json, text, status, owner, source, review_notes,
                        last_reviewer, last_reviewed_at, current_version, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(item["id"]).strip(),
                        str(item["title"]).strip(),
                        json.dumps(item.get("tags", []), ensure_ascii=False),
                        str(item["text"]).strip(),
                        "approved",
                        "",
                        "bootstrap_corpus",
                        "",
                        "system",
                        now,
                        1,
                        now,
                        now,
                    ),
                )

    def _import_audit_log_locked(self, conn: sqlite3.Connection) -> None:
        with self.audit_log_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                    record = AuditRecord(**payload)
                except (json.JSONDecodeError, TypeError):
                    continue
                self._insert_audit_locked(conn, record)

    def _import_evaluation_datasets_locked(self, conn: sqlite3.Connection) -> None:
        for spec in self._evaluation_specs():
            dataset = self._load_evaluation_source(spec)
            if dataset is None:
                continue
            self._replace_evaluation_dataset_locked(
                conn,
                dataset_name=spec["dataset_name"],
                display_name=spec["display_name"],
                source_path=dataset["source_path"],
                rows=dataset["rows"],
                summary=dataset["summary"],
            )

    def _backfill_knowledge_versions_locked(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            """
            SELECT *
            FROM knowledge_records
            ORDER BY id
            """
        ).fetchall()
        for row in rows:
            existing_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM knowledge_versions WHERE record_id = ?",
                    (row["id"],),
                ).fetchone()[0]
            )
            if existing_count > 0:
                continue
            snapshot = self._row_to_knowledge_dict(row)
            self._append_knowledge_version_locked(
                conn,
                record_id=str(row["id"]),
                version_no=int(snapshot.get("current_version", 1) or 1),
                action="bootstrap_import",
                actor="system",
                change_note="Initial knowledge import",
                snapshot=snapshot,
            )

    def list_knowledge(self, *, query: str = "", tag: str = "", status: str = "", limit: int = 100) -> list[dict[str, Any]]:
        query = query.strip().lower()
        tag = tag.strip().lower()
        status = status.strip().lower()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM knowledge_records
                ORDER BY
                    CASE status
                        WHEN 'in_review' THEN 0
                        WHEN 'changes_requested' THEN 1
                        WHEN 'draft' THEN 2
                        WHEN 'approved' THEN 3
                        ELSE 4
                    END,
                    updated_at DESC,
                    id ASC
                """
            ).fetchall()
        matched: list[dict[str, Any]] = []
        for row in rows:
            item = self._row_to_knowledge_dict(row)
            joined_tags = " ".join(item["tags"]).lower()
            haystack = f"{item['id']} {item['title']} {item['text']} {joined_tags} {item['owner']} {item['source']}".lower()
            if query and query not in haystack:
                continue
            if tag and not any(tag == str(tag_item).lower() for tag_item in item["tags"]):
                continue
            if status and status != item["status"]:
                continue
            matched.append(
                {
                    "id": item["id"],
                    "title": item["title"],
                    "tags": item["tags"],
                    "status": item["status"],
                    "owner": item["owner"],
                    "source": item["source"],
                    "current_version": item["current_version"],
                    "updated_at": item["updated_at"],
                    "text_preview": self._preview(str(item["text"])),
                    "char_count": len(str(item["text"])),
                }
            )
        return matched[:limit]

    def get_knowledge(self, record_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM knowledge_records WHERE id = ?",
                (record_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_knowledge_dict(row)

    def list_knowledge_versions(self, record_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT record_id, version_no, action, actor, change_note, created_at, snapshot_json
                FROM knowledge_versions
                WHERE record_id = ?
                ORDER BY version_no DESC
                LIMIT ?
                """,
                (record_id, limit),
            ).fetchall()
        return [
            {
                "record_id": row["record_id"],
                "version_no": int(row["version_no"]),
                "action": row["action"],
                "actor": row["actor"],
                "change_note": row["change_note"],
                "created_at": row["created_at"],
                "snapshot": json.loads(row["snapshot_json"] or "{}"),
            }
            for row in rows
        ]

    def upsert_knowledge(self, payload: dict[str, Any], *, record_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            resolved_id = record_id or str(payload.get("id", "")).strip() or self.next_knowledge_id()
            title = str(payload.get("title", "")).strip()
            text = str(payload.get("text", "")).strip()
            tags = self._normalize_tags(payload.get("tags", []))
            owner = str(payload.get("owner", "")).strip()
            source = str(payload.get("source", "")).strip()
            reviewer = str(payload.get("reviewer", "")).strip()
            review_notes = str(payload.get("review_notes", "")).strip()
            change_note = str(payload.get("change_note", "")).strip()
            if not title:
                raise ValueError("knowledge title is required")
            if not text:
                raise ValueError("knowledge text is required")

            now = utc_now_iso()
            with self._connect() as conn:
                existing_row = conn.execute("SELECT * FROM knowledge_records WHERE id = ?", (resolved_id,)).fetchone()
                existing = self._row_to_knowledge_dict(existing_row) if existing_row is not None else None
                resolved_status = self._validate_knowledge_status(
                    str(payload.get("status", existing["status"] if existing else "draft")).strip().lower() or "draft"
                )
                created_at = existing["created_at"] if existing else now
                current_version = (int(existing["current_version"]) + 1) if existing else 1
                last_reviewer = existing["last_reviewer"] if existing else ""
                last_reviewed_at = existing["last_reviewed_at"] if existing else ""
                if reviewer:
                    last_reviewer = reviewer
                if reviewer or review_notes or resolved_status in {"in_review", "approved", "changes_requested", "archived"}:
                    last_reviewed_at = now

                record = {
                    "id": resolved_id,
                    "title": title,
                    "tags": tags,
                    "text": text,
                    "status": resolved_status,
                    "owner": owner,
                    "source": source,
                    "review_notes": review_notes,
                    "last_reviewer": last_reviewer,
                    "last_reviewed_at": last_reviewed_at,
                    "current_version": current_version,
                    "created_at": created_at,
                    "updated_at": now,
                }
                conn.execute(
                    """
                    INSERT OR REPLACE INTO knowledge_records (
                        id, title, tags_json, text, status, owner, source, review_notes,
                        last_reviewer, last_reviewed_at, current_version, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record["id"],
                        record["title"],
                        json.dumps(record["tags"], ensure_ascii=False),
                        record["text"],
                        record["status"],
                        record["owner"],
                        record["source"],
                        record["review_notes"],
                        record["last_reviewer"],
                        record["last_reviewed_at"],
                        record["current_version"],
                        record["created_at"],
                        record["updated_at"],
                    ),
                )
                action = "created" if existing is None else ("status_changed" if existing["status"] != resolved_status else "updated")
                actor = reviewer or owner or "admin"
                note = change_note or self._default_change_note(action=action, status=resolved_status)
                self._append_knowledge_version_locked(
                    conn,
                    record_id=resolved_id,
                    version_no=current_version,
                    action=action,
                    actor=actor,
                    change_note=note,
                    snapshot=record,
                )
                conn.commit()
            index_info = self.sync_knowledge_files()
            return {
                "ok": True,
                "action": action,
                "record": record,
                "history": self.list_knowledge_versions(resolved_id, limit=12),
                "index": index_info,
            }

    def delete_knowledge(self, record_id: str) -> dict[str, Any]:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM knowledge_records WHERE id = ?", (record_id,)).fetchone()
                if row is None:
                    raise KeyError(record_id)
                record = self._row_to_knowledge_dict(row)
                self._append_knowledge_version_locked(
                    conn,
                    record_id=record_id,
                    version_no=int(record["current_version"]) + 1,
                    action="deleted",
                    actor=record["owner"] or record["last_reviewer"] or "admin",
                    change_note="Knowledge record deleted",
                    snapshot={**record, "deleted": True, "updated_at": utc_now_iso()},
                )
                conn.execute("DELETE FROM knowledge_records WHERE id = ?", (record_id,))
                conn.commit()
            index_info = self.sync_knowledge_files()
            return {
                "ok": True,
                "deleted": record,
                "index": index_info,
            }

    def knowledge_summary(self) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, tags_json, status
                FROM knowledge_records
                ORDER BY id
                """
            ).fetchall()
        tag_counter: Counter[str] = Counter()
        status_counter: Counter[str] = Counter()
        for row in rows:
            tag_counter.update(json.loads(row["tags_json"]))
            status_counter.update([str(row["status"] or "draft")])
        index_mtime = self.index_path.stat().st_mtime if self.index_path.exists() else None
        approved_count = int(status_counter.get("approved", 0))
        return {
            "record_count": len(rows),
            "approved_count": approved_count,
            "pending_review_count": int(status_counter.get("in_review", 0) + status_counter.get("changes_requested", 0)),
            "draft_count": int(status_counter.get("draft", 0)),
            "archived_count": int(status_counter.get("archived", 0)),
            "status_counts": {status_name: int(status_counter.get(status_name, 0)) for status_name in KNOWLEDGE_STATUSES},
            "next_id": self.next_knowledge_id(),
            "top_tags": [{"tag": tag, "count": count} for tag, count in tag_counter.most_common(12)],
            "index_path": str(self.index_path),
            "index_updated_at": datetime.fromtimestamp(index_mtime, tz=timezone.utc).isoformat() if index_mtime else "",
            "db_path": str(self.db_path),
        }

    def reload_evaluations(self) -> dict[str, Any]:
        with self._lock:
            with self._connect() as conn:
                conn.execute("DELETE FROM evaluation_rows")
                conn.execute("DELETE FROM evaluation_datasets")
                self._import_evaluation_datasets_locked(conn)
                conn.commit()
        datasets = self.list_evaluation_datasets()
        return {
            "dataset_count": len(datasets),
            "datasets": datasets,
            "updated_at": utc_now_iso(),
        }

    def next_knowledge_id(self) -> str:
        with self._connect() as conn:
            rows = conn.execute("SELECT id FROM knowledge_records").fetchall()
        numeric_ids = [int(str(row["id"])[2:]) for row in rows if str(row["id"]).startswith("KS") and str(row["id"])[2:].isdigit()]
        return f"KS{max(numeric_ids, default=0) + 1:03d}"

    def sync_knowledge_files(self) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, title, tags_json, text, status
                FROM knowledge_records
                ORDER BY id
                """
            ).fetchall()
        approved_docs = [
            {
                "id": row["id"],
                "title": row["title"],
                "tags": json.loads(row["tags_json"]),
                "text": row["text"],
            }
            for row in rows
            if str(row["status"] or "draft") == "approved"
        ]
        self.backup_root.mkdir(parents=True, exist_ok=True)
        if self.corpus_path.exists():
            backup_name = f"{self.corpus_path.stem}-{utc_now_iso().replace(':', '-')}.jsonl"
            backup_path = self.backup_root / backup_name
            backup_path.write_text(self.corpus_path.read_text(encoding="utf-8"), encoding="utf-8")
        corpus_text = "\n".join(json.dumps(item, ensure_ascii=False) for item in approved_docs)
        if corpus_text:
            corpus_text += "\n"
        self.corpus_path.write_text(corpus_text, encoding="utf-8")
        index = build_index(approved_docs)
        self.index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "document_count": len(approved_docs),
            "approved_count": len(approved_docs),
            "total_records": len(rows),
            "index_path": str(self.index_path),
            "updated_at": utc_now_iso(),
        }

    def _row_to_knowledge_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "title": row["title"],
            "tags": json.loads(row["tags_json"] or "[]"),
            "text": row["text"],
            "status": str(row["status"] or "draft"),
            "owner": str(row["owner"] or ""),
            "source": str(row["source"] or ""),
            "review_notes": str(row["review_notes"] or ""),
            "last_reviewer": str(row["last_reviewer"] or ""),
            "last_reviewed_at": str(row["last_reviewed_at"] or ""),
            "current_version": int(row["current_version"] or 1),
            "created_at": str(row["created_at"] or ""),
            "updated_at": str(row["updated_at"] or ""),
        }

    def _validate_knowledge_status(self, status: str) -> str:
        normalized = status.strip().lower() or "draft"
        if normalized not in KNOWLEDGE_STATUSES:
            raise ValueError(f"unsupported knowledge status: {status}")
        return normalized

    def _default_change_note(self, *, action: str, status: str) -> str:
        if action == "created":
            return f"Knowledge record created as {status}"
        if action == "status_changed":
            return f"Knowledge status updated to {status}"
        if action == "deleted":
            return "Knowledge record deleted"
        return "Knowledge content updated"

    def _append_knowledge_version_locked(
        self,
        conn: sqlite3.Connection,
        *,
        record_id: str,
        version_no: int,
        action: str,
        actor: str,
        change_note: str,
        snapshot: dict[str, Any],
    ) -> None:
        conn.execute(
            """
            INSERT OR REPLACE INTO knowledge_versions (
                record_id, version_no, action, actor, change_note, created_at, snapshot_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record_id,
                int(version_no),
                action,
                actor,
                change_note,
                utc_now_iso(),
                json.dumps(snapshot, ensure_ascii=False),
            ),
        )

    def insert_audit(self, record: AuditRecord) -> None:
        with self._lock:
            with self._connect() as conn:
                self._insert_audit_locked(conn, record)
                conn.commit()
            with self.audit_log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")

    def _insert_audit_locked(self, conn: sqlite3.Connection, record: AuditRecord) -> None:
        inferred_case = self._infer_run_case_fields(
            {
                "status": record.status,
                "gate_allowed": None if record.gate_allowed is None else int(bool(record.gate_allowed)),
                "gate_label": record.gate_label,
                "metrics_json": json.dumps(record.metrics, ensure_ascii=False),
                "error": record.error,
            }
        )
        existing = conn.execute(
            "SELECT case_status, case_severity, case_type, case_owner, case_note, case_reviewer, case_reviewed_at, case_updated_at FROM run_audits WHERE run_id = ?",
            (record.run_id,),
        ).fetchone()
        case_status = existing["case_status"] if existing and existing["case_status"] else inferred_case["case_status"]
        case_severity = existing["case_severity"] if existing and existing["case_severity"] else inferred_case["case_severity"]
        case_type = existing["case_type"] if existing and existing["case_type"] else inferred_case["case_type"]
        case_owner = existing["case_owner"] if existing else ""
        case_note = existing["case_note"] if existing else ""
        case_reviewer = existing["case_reviewer"] if existing else ""
        case_reviewed_at = existing["case_reviewed_at"] if existing else ""
        case_updated_at = existing["case_updated_at"] if existing and existing["case_updated_at"] else utc_now_iso()
        conn.execute(
            """
            INSERT OR REPLACE INTO run_audits (
                run_id, session_id, status, created_at, mode, question, transcript,
                gate_label, gate_allowed, answer_preview, providers_json, metrics_json,
                error, evidence_titles_json, audio_name, case_status, case_severity,
                case_type, case_owner, case_note, case_reviewer, case_reviewed_at,
                case_updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.run_id,
                record.session_id,
                record.status,
                record.created_at,
                record.mode,
                record.question,
                record.transcript,
                record.gate_label,
                None if record.gate_allowed is None else int(bool(record.gate_allowed)),
                record.answer_preview,
                json.dumps(record.providers, ensure_ascii=False),
                json.dumps(record.metrics, ensure_ascii=False),
                record.error,
                json.dumps(record.evidence_titles, ensure_ascii=False),
                record.audio_name,
                case_status,
                case_severity,
                case_type,
                case_owner,
                case_note,
                case_reviewer,
                case_reviewed_at,
                case_updated_at,
            ),
        )

    def recent_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.search_runs(limit=limit)

    def session_runs(self, session_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM run_audits
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        return [self._row_to_audit_dict(row) for row in rows]

    def session_summaries(self, limit: int = 12) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT session_id, COUNT(*) AS runs, MAX(created_at) AS last_created_at
                FROM run_audits
                GROUP BY session_id
                ORDER BY last_created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            results: list[dict[str, Any]] = []
            for row in rows:
                latest = conn.execute(
                    """
                    SELECT run_id, status, question, gate_label, metrics_json
                    FROM run_audits
                    WHERE session_id = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (row["session_id"],),
                ).fetchone()
                metrics = json.loads(latest["metrics_json"]) if latest and latest["metrics_json"] else {}
                results.append(
                    {
                        "session_id": row["session_id"],
                        "runs": int(row["runs"]),
                        "last_run_id": latest["run_id"] if latest else "",
                        "last_status": latest["status"] if latest else "",
                        "last_question": latest["question"] if latest else "",
                        "last_created_at": row["last_created_at"],
                        "last_gate_label": latest["gate_label"] if latest else "",
                        "last_total_ms": metrics.get("total_ms", ""),
                    }
                )
        return results

    def search_runs(
        self,
        *,
        query: str = "",
        status: str = "",
        gate_label: str = "",
        case_status: str = "",
        case_severity: str = "",
        case_type: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if gate_label:
            clauses.append("gate_label = ?")
            params.append(gate_label)
        if case_status:
            clauses.append("case_status = ?")
            params.append(self._validate_run_case_status(case_status))
        if case_severity:
            clauses.append("case_severity = ?")
            params.append(self._validate_run_case_severity(case_severity))
        if case_type:
            clauses.append("case_type = ?")
            params.append(self._validate_run_case_type(case_type))
        sql = "SELECT * FROM run_audits"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        query = query.strip().lower()
        items = [self._row_to_audit_dict(row) for row in rows]
        if not query:
            return items
        matched: list[dict[str, Any]] = []
        for item in items:
            haystack = " ".join(
                [
                    str(item.get("run_id", "")),
                    str(item.get("session_id", "")),
                    str(item.get("question", "")),
                    str(item.get("transcript", "")),
                    str(item.get("answer_preview", "")),
                    str(item.get("error", "")),
                    str(item.get("case_owner", "")),
                    str(item.get("case_note", "")),
                    str(item.get("case_type", "")),
                ]
            ).lower()
            if query in haystack:
                matched.append(item)
        return matched

    def update_run_case(self, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM run_audits WHERE run_id = ?", (run_id,)).fetchone()
                if row is None:
                    raise KeyError(run_id)
                case_status = self._validate_run_case_status(str(payload.get("case_status", row["case_status"])).strip())
                case_severity = self._validate_run_case_severity(str(payload.get("case_severity", row["case_severity"])).strip())
                case_type = self._validate_run_case_type(str(payload.get("case_type", row["case_type"])).strip())
                case_owner = str(payload.get("case_owner", row["case_owner"] or "")).strip()
                case_note = str(payload.get("case_note", row["case_note"] or "")).strip()
                case_reviewer = str(payload.get("case_reviewer", row["case_reviewer"] or "")).strip()
                now = utc_now_iso()
                case_reviewed_at = str(row["case_reviewed_at"] or "")
                if case_reviewer or case_status in {"resolved", "accepted_risk", "ignored"}:
                    case_reviewed_at = now
                conn.execute(
                    """
                    UPDATE run_audits
                    SET case_status = ?,
                        case_severity = ?,
                        case_type = ?,
                        case_owner = ?,
                        case_note = ?,
                        case_reviewer = ?,
                        case_reviewed_at = ?,
                        case_updated_at = ?
                    WHERE run_id = ?
                    """,
                    (
                        case_status,
                        case_severity,
                        case_type,
                        case_owner,
                        case_note,
                        case_reviewer,
                        case_reviewed_at,
                        now,
                        run_id,
                    ),
                )
                updated_row = conn.execute("SELECT * FROM run_audits WHERE run_id = ?", (run_id,)).fetchone()
                self._rewrite_audit_log_locked(conn)
                conn.commit()
        return self._row_to_audit_dict(updated_row)

    def cleanup_runs(
        self,
        *,
        query: str = "",
        delete_smoke: bool = False,
        delete_mojibake: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute("SELECT * FROM run_audits ORDER BY created_at DESC").fetchall()
                items = [self._row_to_audit_dict(row) for row in rows]
                to_delete = [
                    item
                    for item in items
                    if self._should_delete_run(
                        item,
                        query=query,
                        delete_smoke=delete_smoke,
                        delete_mojibake=delete_mojibake,
                    )
                ]
                for item in to_delete:
                    conn.execute("DELETE FROM run_audits WHERE run_id = ?", (item["run_id"],))
                self._rewrite_audit_log_locked(conn)
                conn.commit()
        return {
            "deleted_count": len(to_delete),
            "deleted_run_ids": [item["run_id"] for item in to_delete[:20]],
            "deleted_sessions": sorted({item["session_id"] for item in to_delete})[:20],
            "updated_at": utc_now_iso(),
        }

    def audit_stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            counts = conn.execute(
                """
                SELECT
                    COUNT(*) AS total_runs,
                    SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS error_runs,
                    SUM(CASE WHEN gate_allowed = 0 THEN 1 ELSE 0 END) AS blocked_runs,
                    SUM(CASE WHEN case_status IN ('open', 'investigating') THEN 1 ELSE 0 END) AS open_cases,
                    SUM(CASE WHEN case_severity IN ('high', 'critical') AND case_status NOT IN ('resolved', 'ignored') THEN 1 ELSE 0 END) AS high_priority_cases,
                    AVG(CASE
                        WHEN json_extract(metrics_json, '$.total_ms') IS NOT NULL
                        THEN CAST(json_extract(metrics_json, '$.total_ms') AS REAL)
                    END) AS avg_total_ms
                FROM run_audits
                """
            ).fetchone()
        total_runs = int(counts["total_runs"] or 0)
        error_runs = int(counts["error_runs"] or 0)
        blocked_runs = int(counts["blocked_runs"] or 0)
        return {
            "total_runs": total_runs,
            "error_runs": error_runs,
            "blocked_runs": blocked_runs,
            "ok_runs": total_runs - error_runs,
            "open_cases": int(counts["open_cases"] or 0),
            "high_priority_cases": int(counts["high_priority_cases"] or 0),
            "avg_total_ms": round(float(counts["avg_total_ms"] or 0), 2),
        }

    def list_evaluation_datasets(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT dataset_name, display_name, source_path, row_count, imported_at, summary_json
                FROM evaluation_datasets
                ORDER BY dataset_name
                """
            ).fetchall()
        datasets: list[dict[str, Any]] = []
        for row in rows:
            summary = json.loads(row["summary_json"] or "{}")
            datasets.append(
                {
                    "dataset_name": row["dataset_name"],
                    "display_name": row["display_name"],
                    "source_path": row["source_path"],
                    "row_count": int(row["row_count"]),
                    "imported_at": row["imported_at"],
                    "summary": summary,
                }
            )
        return datasets

    def get_evaluation_dataset(
        self,
        dataset_name: str,
        *,
        query: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            dataset_row = conn.execute(
                """
                SELECT dataset_name, display_name, source_path, row_count, imported_at, summary_json
                FROM evaluation_datasets
                WHERE dataset_name = ?
                """,
                (dataset_name,),
            ).fetchone()
            if dataset_row is None:
                return None
            rows = conn.execute(
                """
                SELECT row_key, row_index, payload_json
                FROM evaluation_rows
                WHERE dataset_name = ?
                ORDER BY row_index ASC
                LIMIT ? OFFSET ?
                """,
                (dataset_name, limit, offset),
            ).fetchall()
        items = [
            {
                "row_key": row["row_key"],
                "row_index": int(row["row_index"]),
                "payload": json.loads(row["payload_json"] or "{}"),
            }
            for row in rows
        ]
        query = query.strip().lower()
        if query:
            filtered: list[dict[str, Any]] = []
            for item in items:
                haystack = json.dumps(item["payload"], ensure_ascii=False).lower()
                if query in haystack:
                    filtered.append(item)
            items = filtered
        return {
            "dataset_name": dataset_row["dataset_name"],
            "display_name": dataset_row["display_name"],
            "source_path": dataset_row["source_path"],
            "row_count": int(dataset_row["row_count"]),
            "imported_at": dataset_row["imported_at"],
            "summary": json.loads(dataset_row["summary_json"] or "{}"),
            "rows": items,
        }

    def evaluation_overview(self) -> dict[str, Any]:
        datasets = {item["dataset_name"]: item for item in self.list_evaluation_datasets()}
        return {
            "datasets": list(datasets.values()),
            "safety": datasets.get("safety_gate_eval", {}).get("summary", {}),
            "asr": datasets.get("asr_eval", {}).get("summary", {}),
            "multiturn": datasets.get("multiturn_eval", {}).get("summary", {}),
            "latency": datasets.get("latency_metrics", {}).get("summary", {}),
            "real_chain": datasets.get("real_chain_samples", {}).get("summary", {}),
        }

    def create_admin_job(
        self,
        *,
        job_id: str,
        job_type: str,
        label: str,
        payload: dict[str, Any] | None = None,
        status: str = "queued",
    ) -> dict[str, Any]:
        now = utc_now_iso()
        record = {
            "job_id": job_id,
            "job_type": job_type,
            "label": label,
            "status": status,
            "progress": 0,
            "payload": payload or {},
            "result": {},
            "error": "",
            "created_at": now,
            "started_at": "",
            "updated_at": now,
            "completed_at": "",
        }
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO admin_jobs (
                        job_id, job_type, label, status, progress, payload_json,
                        result_json, error, created_at, started_at, updated_at, completed_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record["job_id"],
                        record["job_type"],
                        record["label"],
                        record["status"],
                        record["progress"],
                        json.dumps(record["payload"], ensure_ascii=False),
                        json.dumps(record["result"], ensure_ascii=False),
                        record["error"],
                        record["created_at"],
                        record["started_at"],
                        record["updated_at"],
                        record["completed_at"],
                    ),
                )
                conn.commit()
        return record

    def update_admin_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        progress: int | None = None,
        started_at: str | None = None,
        completed_at: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        current = self.get_admin_job(job_id)
        if current is None:
            raise KeyError(job_id)
        updated = {
            **current,
            "status": status or current["status"],
            "progress": current["progress"] if progress is None else max(0, min(100, int(progress))),
            "started_at": current["started_at"] if started_at is None else started_at,
            "completed_at": current["completed_at"] if completed_at is None else completed_at,
            "result": current["result"] if result is None else result,
            "error": current["error"] if error is None else error,
            "updated_at": utc_now_iso(),
        }
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE admin_jobs
                    SET status = ?, progress = ?, result_json = ?, error = ?,
                        started_at = ?, updated_at = ?, completed_at = ?
                    WHERE job_id = ?
                    """,
                    (
                        updated["status"],
                        updated["progress"],
                        json.dumps(updated["result"], ensure_ascii=False),
                        updated["error"],
                        updated["started_at"],
                        updated["updated_at"],
                        updated["completed_at"],
                        job_id,
                    ),
                )
                conn.commit()
        return updated

    def list_admin_jobs(self, *, job_type: str = "", limit: int = 20) -> list[dict[str, Any]]:
        sql = """
            SELECT job_id, job_type, label, status, progress, payload_json,
                   result_json, error, created_at, started_at, updated_at, completed_at
            FROM admin_jobs
        """
        params: list[Any] = []
        if job_type.strip():
            sql += " WHERE job_type = ?"
            params.append(job_type.strip())
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_admin_job(row) for row in rows]

    def get_admin_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT job_id, job_type, label, status, progress, payload_json,
                       result_json, error, created_at, started_at, updated_at, completed_at
                FROM admin_jobs
                WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_admin_job(row)

    def admin_job_summary(self, *, job_type: str = "") -> dict[str, Any]:
        jobs = self.list_admin_jobs(job_type=job_type, limit=10)
        active = next((item for item in jobs if item["status"] in {"queued", "running"}), None)
        latest = jobs[0] if jobs else None
        return {
            "total_jobs": len(jobs),
            "active_jobs": sum(1 for item in jobs if item["status"] in {"queued", "running"}),
            "latest_job": latest,
            "active_job": active,
        }

    def _row_to_admin_job(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "job_id": row["job_id"],
            "job_type": row["job_type"],
            "label": row["label"],
            "status": row["status"],
            "progress": int(row["progress"] or 0),
            "payload": json.loads(row["payload_json"] or "{}"),
            "result": json.loads(row["result_json"] or "{}"),
            "error": row["error"],
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "updated_at": row["updated_at"],
            "completed_at": row["completed_at"],
        }

    def _row_to_audit_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        gate_allowed = row["gate_allowed"]
        return {
            "run_id": row["run_id"],
            "session_id": row["session_id"],
            "status": row["status"],
            "created_at": row["created_at"],
            "mode": row["mode"],
            "question": row["question"],
            "transcript": row["transcript"],
            "gate_label": row["gate_label"],
            "gate_allowed": None if gate_allowed is None else bool(gate_allowed),
            "answer_preview": row["answer_preview"],
            "providers": json.loads(row["providers_json"] or "{}"),
            "metrics": json.loads(row["metrics_json"] or "{}"),
            "error": row["error"],
            "evidence_titles": json.loads(row["evidence_titles_json"] or "[]"),
            "audio_name": row["audio_name"],
            "case_status": row["case_status"],
            "case_severity": row["case_severity"],
            "case_type": row["case_type"],
            "case_owner": row["case_owner"],
            "case_note": row["case_note"],
            "case_reviewer": row["case_reviewer"],
            "case_reviewed_at": row["case_reviewed_at"],
            "case_updated_at": row["case_updated_at"],
        }

    def _audit_record_payload(self, item: dict[str, Any]) -> dict[str, Any]:
        keys = [
            "run_id",
            "session_id",
            "status",
            "created_at",
            "mode",
            "question",
            "transcript",
            "gate_label",
            "gate_allowed",
            "answer_preview",
            "providers",
            "metrics",
            "error",
            "evidence_titles",
            "audio_name",
        ]
        return {key: item.get(key) for key in keys}

    def _normalize_tags(self, raw: Any) -> list[str]:
        if isinstance(raw, str):
            items = [item.strip() for item in raw.split(",")]
        elif isinstance(raw, list):
            items = [str(item).strip() for item in raw]
        else:
            items = []
        return list(dict.fromkeys([item for item in items if item]))

    def _preview(self, text: str, limit: int = 90) -> str:
        return text if len(text) <= limit else f"{text[:limit]}..."

    def _rewrite_audit_log_locked(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute("SELECT * FROM run_audits ORDER BY created_at ASC").fetchall()
        with self.audit_log_path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(self._audit_record_payload(self._row_to_audit_dict(row)), ensure_ascii=False) + "\n")

    def _should_delete_run(
        self,
        item: dict[str, Any],
        *,
        query: str,
        delete_smoke: bool,
        delete_mojibake: bool,
    ) -> bool:
        if query:
            haystack = self._audit_match_haystack(item)
            if query.strip().lower() in haystack:
                return True
        if delete_smoke:
            smoke_fields = [
                str(item.get("session_id", "")),
                str(item.get("audio_name", "")),
            ]
            if any("smoke" in value.lower() for value in smoke_fields):
                return True
        if delete_mojibake:
            if self._looks_like_mojibake(str(item.get("question", ""))) or self._looks_like_mojibake(str(item.get("transcript", ""))):
                return True
        return False

    def _audit_match_haystack(self, item: dict[str, Any]) -> str:
        return " ".join(
            [
                str(item.get("run_id", "")),
                str(item.get("session_id", "")),
                str(item.get("question", "")),
                str(item.get("transcript", "")),
                str(item.get("answer_preview", "")),
                str(item.get("error", "")),
                str(item.get("case_owner", "")),
                str(item.get("case_note", "")),
                str(item.get("case_type", "")),
            ]
        ).lower()

    def _validate_run_case_status(self, status: str) -> str:
        normalized = status.strip().lower() or "open"
        if normalized not in RUN_CASE_STATUSES:
            raise ValueError(f"unsupported run case status: {status}")
        return normalized

    def _validate_run_case_severity(self, severity: str) -> str:
        normalized = severity.strip().lower() or "low"
        if normalized not in RUN_CASE_SEVERITIES:
            raise ValueError(f"unsupported run case severity: {severity}")
        return normalized

    def _validate_run_case_type(self, case_type: str) -> str:
        normalized = case_type.strip().lower() or "normal"
        if normalized not in RUN_CASE_TYPES:
            raise ValueError(f"unsupported run case type: {case_type}")
        return normalized

    def _infer_run_case_fields(self, row_or_payload: Any) -> dict[str, str]:
        status = str(self._row_value(row_or_payload, "status", "") or "")
        gate_allowed = self._row_value(row_or_payload, "gate_allowed", None)
        gate_label = str(self._row_value(row_or_payload, "gate_label", "") or "")
        error = str(self._row_value(row_or_payload, "error", "") or "")
        metrics = self._decode_json_field(self._row_value(row_or_payload, "metrics_json", "{}"), default={})
        total_ms = self._numeric_metric(metrics, "total_ms")
        first_audio_ms = self._numeric_metric(metrics, "first_audio_ms")

        if status == "error" or error:
            return {"case_status": "open", "case_severity": "high", "case_type": "error"}
        if gate_allowed == 0 or gate_allowed is False:
            return {"case_status": "open", "case_severity": "medium", "case_type": "safety_gate"}
        if total_ms >= 12000 or first_audio_ms >= 5000:
            return {"case_status": "open", "case_severity": "medium", "case_type": "latency"}
        if gate_label and gate_label not in {"domain_safe", "safe", "allowed"}:
            return {"case_status": "investigating", "case_severity": "low", "case_type": "quality"}
        return {"case_status": "resolved", "case_severity": "low", "case_type": "normal"}

    def _row_value(self, row_or_payload: Any, key: str, default: Any = None) -> Any:
        if isinstance(row_or_payload, dict):
            return row_or_payload.get(key, default)
        try:
            return row_or_payload[key]
        except (IndexError, KeyError, TypeError):
            return default

    def _decode_json_field(self, raw: Any, *, default: Any) -> Any:
        if isinstance(raw, (dict, list)):
            return raw
        try:
            return json.loads(str(raw or ""))
        except json.JSONDecodeError:
            return default

    def _numeric_metric(self, metrics: dict[str, Any], key: str) -> float:
        try:
            return float(metrics.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    def _looks_like_mojibake(self, text: str) -> bool:
        compact = "".join(ch for ch in text if not ch.isspace())
        if not compact:
            return False
        if "�" in compact:
            return True
        if len(compact) >= 6 and compact.count("?") / len(compact) >= 0.5:
            return True
        return False

    def _replace_evaluation_dataset_locked(
        self,
        conn: sqlite3.Connection,
        *,
        dataset_name: str,
        display_name: str,
        source_path: str,
        rows: list[dict[str, Any]],
        summary: dict[str, Any],
    ) -> None:
        imported_at = utc_now_iso()
        conn.execute("DELETE FROM evaluation_rows WHERE dataset_name = ?", (dataset_name,))
        conn.execute(
            """
            INSERT OR REPLACE INTO evaluation_datasets (
                dataset_name, display_name, source_path, row_count, imported_at, summary_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                dataset_name,
                display_name,
                source_path,
                len(rows),
                imported_at,
                json.dumps(summary, ensure_ascii=False),
            ),
        )
        for row_index, payload in enumerate(rows, start=1):
            row_key = self._evaluation_row_key(dataset_name, payload, row_index)
            conn.execute(
                """
                INSERT OR REPLACE INTO evaluation_rows (dataset_name, row_key, row_index, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (dataset_name, row_key, row_index, json.dumps(payload, ensure_ascii=False)),
            )

    def _evaluation_specs(self) -> list[dict[str, str]]:
        return [
            {
                "dataset_name": "safety_gate_eval",
                "display_name": "Safety Gate Evaluation",
                "type": "csv",
                "rows_path": str(project_path("results", "safety_gate_eval.csv")),
                "summary_path": str(project_path("results", "safety_gate_eval_summary.json")),
            },
            {
                "dataset_name": "asr_eval",
                "display_name": "ASR Evaluation",
                "type": "csv",
                "rows_path": str(project_path("results", "asr_eval.csv")),
                "summary_path": str(project_path("results", "asr_eval_summary.json")),
            },
            {
                "dataset_name": "multiturn_eval",
                "display_name": "Multi-turn Evaluation",
                "type": "csv",
                "rows_path": str(project_path("results", "multiturn_eval.csv")),
                "summary_path": str(project_path("results", "multiturn_eval_summary.json")),
            },
            {
                "dataset_name": "latency_metrics",
                "display_name": "Latency Metrics",
                "type": "csv",
                "rows_path": str(project_path("results", "latency_metrics.csv")),
                "summary_path": "",
            },
            {
                "dataset_name": "real_chain_samples",
                "display_name": "Real Chain Samples",
                "type": "summary_samples",
                "rows_path": str(project_path("results", "remote_real_chain_20260612_chattts_48359", "summary.json")),
                "summary_path": str(project_path("results", "remote_real_chain_20260612_chattts_48359", "summary.json")),
            },
        ]

    def _load_evaluation_source(self, spec: dict[str, str]) -> dict[str, Any] | None:
        rows_path = Path(spec["rows_path"])
        if not rows_path.exists():
            return None
        summary_path = Path(spec["summary_path"]) if spec.get("summary_path") else None
        summary = self._read_json(summary_path) if summary_path else {}
        if spec["type"] == "csv":
            rows = self._read_csv(rows_path)
            if not summary:
                summary = self._summarize_csv_dataset(spec["dataset_name"], rows)
        elif spec["type"] == "summary_samples":
            payload = self._read_json(rows_path)
            rows = list(payload.get("samples", []))
            summary = payload
        else:
            rows = []
        return {
            "source_path": str(rows_path),
            "rows": rows,
            "summary": summary,
        }

    def _read_csv(self, path: Path) -> list[dict[str, Any]]:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]

    def _read_json(self, path: Path | None) -> dict[str, Any]:
        if path is None or not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _summarize_csv_dataset(self, dataset_name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        if dataset_name == "latency_metrics":
            first_audio = [float(row["first_audio_ms"]) for row in rows if row.get("first_audio_ms")]
            total = [float(row["total_ms"]) for row in rows if row.get("total_ms")]
            by_mode = Counter(row.get("mode", "") for row in rows)
            return {
                "rows": len(rows),
                "avg_first_audio_ms": round(sum(first_audio) / len(first_audio), 2) if first_audio else 0,
                "avg_total_ms": round(sum(total) / len(total), 2) if total else 0,
                "modes": dict(by_mode),
            }
        return {"rows": len(rows)}

    def _evaluation_row_key(self, dataset_name: str, payload: dict[str, Any], row_index: int) -> str:
        for key in ["id", "turn_id", "dialog_id", "question_id", "sample_id", "run_id"]:
            value = str(payload.get(key, "")).strip()
            if value:
                return value if key != "dialog_id" or not payload.get("turn_id") else f"{value}:{payload.get('turn_id')}"
        return f"{dataset_name}:{row_index}"
