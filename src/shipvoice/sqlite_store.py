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
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
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
                    audio_name TEXT NOT NULL
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

    def _bootstrap_if_needed(self) -> None:
        with self._lock:
            with self._connect() as conn:
                knowledge_count = int(conn.execute("SELECT COUNT(*) FROM knowledge_records").fetchone()[0])
                if knowledge_count == 0 and self.corpus_path.exists():
                    self._import_corpus_locked(conn)
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
                    INSERT OR REPLACE INTO knowledge_records (id, title, tags_json, text, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(item["id"]).strip(),
                        str(item["title"]).strip(),
                        json.dumps(item.get("tags", []), ensure_ascii=False),
                        str(item["text"]).strip(),
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

    def list_knowledge(self, *, query: str = "", tag: str = "", limit: int = 100) -> list[dict[str, Any]]:
        query = query.strip().lower()
        tag = tag.strip().lower()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, title, tags_json, text
                FROM knowledge_records
                ORDER BY id
                """
            ).fetchall()
        matched: list[dict[str, Any]] = []
        for row in rows:
            tags = json.loads(row["tags_json"])
            joined_tags = " ".join(tags).lower()
            haystack = f"{row['id']} {row['title']} {row['text']} {joined_tags}".lower()
            if query and query not in haystack:
                continue
            if tag and not any(tag == str(item).lower() for item in tags):
                continue
            matched.append(
                {
                    "id": row["id"],
                    "title": row["title"],
                    "tags": tags,
                    "text_preview": self._preview(str(row["text"])),
                    "char_count": len(str(row["text"])),
                }
            )
        return matched[:limit]

    def get_knowledge(self, record_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, title, tags_json, text FROM knowledge_records WHERE id = ?",
                (record_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "title": row["title"],
            "tags": json.loads(row["tags_json"]),
            "text": row["text"],
        }

    def upsert_knowledge(self, payload: dict[str, Any], *, record_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            resolved_id = record_id or str(payload.get("id", "")).strip() or self.next_knowledge_id()
            title = str(payload.get("title", "")).strip()
            text = str(payload.get("text", "")).strip()
            tags = self._normalize_tags(payload.get("tags", []))
            if not title:
                raise ValueError("knowledge title is required")
            if not text:
                raise ValueError("knowledge text is required")

            now = utc_now_iso()
            with self._connect() as conn:
                existing = conn.execute("SELECT 1 FROM knowledge_records WHERE id = ?", (resolved_id,)).fetchone()
                created_at = now
                if existing:
                    created_at_row = conn.execute(
                        "SELECT created_at FROM knowledge_records WHERE id = ?",
                        (resolved_id,),
                    ).fetchone()
                    created_at = str(created_at_row["created_at"]) if created_at_row else now
                conn.execute(
                    """
                    INSERT OR REPLACE INTO knowledge_records (id, title, tags_json, text, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (resolved_id, title, json.dumps(tags, ensure_ascii=False), text, created_at, now),
                )
                conn.commit()
            action = "created" if existing is None else "updated"
            index_info = self.sync_knowledge_files()
            return {
                "ok": True,
                "action": action,
                "record": {"id": resolved_id, "title": title, "tags": tags, "text": text},
                "index": index_info,
            }

    def delete_knowledge(self, record_id: str) -> dict[str, Any]:
        with self._lock:
            record = self.get_knowledge(record_id)
            if record is None:
                raise KeyError(record_id)
            with self._connect() as conn:
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
            rows = conn.execute("SELECT id, tags_json FROM knowledge_records ORDER BY id").fetchall()
        tag_counter: Counter[str] = Counter()
        for row in rows:
            tag_counter.update(json.loads(row["tags_json"]))
        index_mtime = self.index_path.stat().st_mtime if self.index_path.exists() else None
        return {
            "record_count": len(rows),
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
                "SELECT id, title, tags_json, text FROM knowledge_records ORDER BY id"
            ).fetchall()
        docs = [
            {
                "id": row["id"],
                "title": row["title"],
                "tags": json.loads(row["tags_json"]),
                "text": row["text"],
            }
            for row in rows
        ]
        self.backup_root.mkdir(parents=True, exist_ok=True)
        if self.corpus_path.exists():
            backup_name = f"{self.corpus_path.stem}-{utc_now_iso().replace(':', '-')}.jsonl"
            backup_path = self.backup_root / backup_name
            backup_path.write_text(self.corpus_path.read_text(encoding="utf-8"), encoding="utf-8")
        corpus_text = "\n".join(json.dumps(item, ensure_ascii=False) for item in docs) + "\n"
        self.corpus_path.write_text(corpus_text, encoding="utf-8")
        index = build_index(docs)
        self.index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "document_count": len(docs),
            "index_path": str(self.index_path),
            "updated_at": utc_now_iso(),
        }

    def insert_audit(self, record: AuditRecord) -> None:
        with self._lock:
            with self._connect() as conn:
                self._insert_audit_locked(conn, record)
                conn.commit()
            with self.audit_log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")

    def _insert_audit_locked(self, conn: sqlite3.Connection, record: AuditRecord) -> None:
        conn.execute(
            """
            INSERT OR REPLACE INTO run_audits (
                run_id, session_id, status, created_at, mode, question, transcript,
                gate_label, gate_allowed, answer_preview, providers_json, metrics_json,
                error, evidence_titles_json, audio_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ]
            ).lower()
            if query in haystack:
                matched.append(item)
        return matched

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
        }

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
                handle.write(json.dumps(self._row_to_audit_dict(row), ensure_ascii=False) + "\n")

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
            ]
        ).lower()

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
