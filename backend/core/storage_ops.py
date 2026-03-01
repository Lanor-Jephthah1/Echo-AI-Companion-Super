import glob
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from core.storage_backend import StorageBackend


class StorageOps:
    """High-level persistence operations used by chat, sharing, and admin flows."""

    def __init__(
        self,
        *,
        backend: StorageBackend,
        sanitize_client_id: Callable[[Any], str],
        threads_file_for_client: Callable[[Any], str],
        now_utc_iso: Callable[[], str],
        parse_iso_utc: Callable[[Any], datetime],
        parse_any_timestamp: Callable[[Any], datetime],
        format_human_timestamp: Callable[[datetime], str],
        detect_sentiment: Callable[[str], str],
        sentiment_to_score: Callable[[str], int],
    ) -> None:
        self.backend = backend
        self.sanitize_client_id = sanitize_client_id
        self.threads_file_for_client = threads_file_for_client
        self.now_utc_iso = now_utc_iso
        self.parse_iso_utc = parse_iso_utc
        self.parse_any_timestamp = parse_any_timestamp
        self.format_human_timestamp = format_human_timestamp
        self.detect_sentiment = detect_sentiment
        self.sentiment_to_score = sentiment_to_score

    def ensure_data_dir(self, client_id: Optional[str] = None):
        if not os.path.exists(self.backend.data_dir):
            os.makedirs(self.backend.data_dir)
        threads_file = self.threads_file_for_client(client_id)
        if not os.path.exists(threads_file):
            with open(threads_file, "w", encoding="utf-8") as f:
                json.dump([], f)

    def _load_json_map(self, path: str) -> Dict[str, Any]:
        self.ensure_data_dir(None)
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_json_map(self, path: str, data: Dict[str, Any], *, error_label: str) -> None:
        self.ensure_data_dir(None)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception as e:
            print(f"[BACKEND_ERROR] Failed to save {error_label}: {e}")

    def get_shared_snapshot(self, share_id: str) -> Optional[Dict[str, Any]]:
        sid = str(share_id or "").strip()
        if not sid:
            return None
        if self.backend.mongo_enabled():
            db = self.backend.mongo_db()
            if db is not None:
                try:
                    row = db.shared_snapshots.find_one({"share_id": sid}, {"_id": 0, "snapshot": 1})
                    snap = row.get("snapshot") if isinstance(row, dict) else None
                    return snap if isinstance(snap, dict) else None
                except Exception as e:
                    print(f"[BACKEND_ERROR] Failed mongo read shared snapshot: {e}")
        data = self._load_json_map(self.backend.shared_snapshots_file)
        row = data.get(sid)
        if isinstance(row, dict):
            snap = row.get("snapshot")
            return snap if isinstance(snap, dict) else None
        return None

    def put_shared_snapshot(self, share_id: str, snapshot: Dict[str, Any]) -> None:
        sid = str(share_id or "").strip()
        if not sid:
            return
        payload = {
            "share_id": sid,
            "snapshot": snapshot,
            "updated_at": self.now_utc_iso(),
        }
        if self.backend.mongo_enabled():
            db = self.backend.mongo_db()
            if db is not None:
                try:
                    db.shared_snapshots.update_one(
                        {"share_id": sid},
                        {"$set": payload, "$setOnInsert": {"created_at": self.now_utc_iso()}},
                        upsert=True,
                    )
                    return
                except Exception as e:
                    print(f"[BACKEND_ERROR] Failed mongo write shared snapshot: {e}")
        data = self._load_json_map(self.backend.shared_snapshots_file)
        existing = data.get(sid)
        if isinstance(existing, dict) and "created_at" in existing:
            payload["created_at"] = str(existing.get("created_at"))
        else:
            payload["created_at"] = self.now_utc_iso()
        data[sid] = payload
        self._save_json_map(
            self.backend.shared_snapshots_file,
            data,
            error_label="shared snapshots file",
        )

    def get_shared_link(self, share_id: str) -> Optional[Dict[str, Any]]:
        sid = str(share_id or "").strip()
        if not sid:
            return None

        if self.backend.mongo_enabled():
            db = self.backend.mongo_db()
            if db is not None:
                try:
                    row = db.shared_links.find_one({"share_id": sid}, {"_id": 0})
                    return row if isinstance(row, dict) else None
                except Exception as e:
                    print(f"[BACKEND_ERROR] Failed mongo read shared link: {e}")

        if self.backend.db_enabled():
            self.backend.db_init()
            try:
                with self.backend.db_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT share_id, source_client_id, source_thread_id, created_at, updated_at FROM echo_shared_links WHERE share_id = %s",
                            (sid,),
                        )
                        row = cur.fetchone()
                        if row:
                            return {
                                "share_id": str(row[0]),
                                "source_client_id": str(row[1]),
                                "source_thread_id": str(row[2]),
                                "created_at": str(row[3]),
                                "updated_at": str(row[4]),
                            }
            except Exception as e:
                print(f"[BACKEND_ERROR] Failed db read shared link: {e}")

        data = self._load_json_map(self.backend.shared_links_file)
        row = data.get(sid)
        return row if isinstance(row, dict) else None

    def put_shared_link(self, share_id: str, source_client_id: str, source_thread_id: str) -> Dict[str, Any]:
        now_iso = self.now_utc_iso()
        payload = {
            "share_id": share_id,
            "source_client_id": self.sanitize_client_id(source_client_id),
            "source_thread_id": str(source_thread_id),
            "created_at": now_iso,
            "updated_at": now_iso,
        }

        if self.backend.mongo_enabled():
            db = self.backend.mongo_db()
            if db is not None:
                try:
                    db.shared_links.update_one(
                        {"share_id": share_id},
                        {"$set": payload, "$setOnInsert": {"created_at": now_iso}},
                        upsert=True,
                    )
                    return payload
                except Exception as e:
                    print(f"[BACKEND_ERROR] Failed mongo write shared link: {e}")

        if self.backend.db_enabled():
            self.backend.db_init()
            try:
                with self.backend.db_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO echo_shared_links (share_id, source_client_id, source_thread_id, created_at, updated_at)
                            VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT (share_id)
                            DO UPDATE SET source_client_id = EXCLUDED.source_client_id, source_thread_id = EXCLUDED.source_thread_id, updated_at = EXCLUDED.updated_at
                            """,
                            (
                                share_id,
                                payload["source_client_id"],
                                payload["source_thread_id"],
                                payload["created_at"],
                                payload["updated_at"],
                            ),
                        )
                    conn.commit()
                return payload
            except Exception as e:
                print(f"[BACKEND_ERROR] Failed db write shared link: {e}")

        data = self._load_json_map(self.backend.shared_links_file)
        if share_id in data and isinstance(data[share_id], dict):
            payload["created_at"] = str(data[share_id].get("created_at", now_iso))
        data[share_id] = payload
        self._save_json_map(self.backend.shared_links_file, data, error_label="shared links file")
        return payload

    def get_email_event(self, event_key: str) -> Optional[Dict[str, Any]]:
        if self.backend.mongo_enabled():
            db = self.backend.mongo_db()
            if db is not None:
                try:
                    row = db.email_events.find_one({"event_key": event_key}, {"_id": 0})
                    return row if isinstance(row, dict) else None
                except Exception as e:
                    print(f"[BACKEND_ERROR] Failed mongo read email event: {e}")

        if self.backend.db_enabled():
            self.backend.db_init()
            try:
                with self.backend.db_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT event_key, kind, sent_at_iso, meta_json FROM echo_email_events WHERE event_key = %s",
                            (event_key,),
                        )
                        row = cur.fetchone()
                        if row:
                            meta = {}
                            try:
                                meta = json.loads(row[3] or "{}")
                            except Exception:
                                meta = {}
                            return {
                                "event_key": str(row[0]),
                                "kind": str(row[1]),
                                "sent_at_iso": str(row[2]),
                                "meta": meta,
                            }
            except Exception as e:
                print(f"[BACKEND_ERROR] Failed db read email event: {e}")

        data = self._load_json_map(self.backend.email_events_file)
        row = data.get(event_key)
        return row if isinstance(row, dict) else None

    def put_email_event(self, event_key: str, kind: str, meta: Dict[str, Any]) -> None:
        payload = {
            "event_key": event_key,
            "kind": kind,
            "sent_at_iso": self.now_utc_iso(),
            "meta": meta or {},
        }
        if self.backend.mongo_enabled():
            db = self.backend.mongo_db()
            if db is not None:
                try:
                    db.email_events.update_one({"event_key": event_key}, {"$set": payload}, upsert=True)
                    return
                except Exception as e:
                    print(f"[BACKEND_ERROR] Failed mongo write email event: {e}")

        if self.backend.db_enabled():
            self.backend.db_init()
            try:
                with self.backend.db_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO echo_email_events (event_key, kind, sent_at_iso, meta_json)
                            VALUES (%s, %s, %s, %s)
                            ON CONFLICT (event_key)
                            DO UPDATE SET kind = EXCLUDED.kind, sent_at_iso = EXCLUDED.sent_at_iso, meta_json = EXCLUDED.meta_json
                            """,
                            (
                                event_key,
                                kind,
                                payload["sent_at_iso"],
                                json.dumps(payload["meta"], ensure_ascii=False),
                            ),
                        )
                    conn.commit()
                return
            except Exception as e:
                print(f"[BACKEND_ERROR] Failed db write email event: {e}")

        data = self._load_json_map(self.backend.email_events_file)
        data[event_key] = payload
        self._save_json_map(self.backend.email_events_file, data, error_label="email events file")

    def email_event_recent(self, event_key: str, minutes: int) -> bool:
        row = self.get_email_event(event_key)
        if not row:
            return False
        sent = self.parse_iso_utc(row.get("sent_at_iso", ""))
        return (datetime.now(timezone.utc) - sent) < timedelta(minutes=max(1, minutes))

    def list_email_events(self, limit: int = 200) -> List[Dict[str, Any]]:
        n = max(1, min(int(limit), 1000))

        if self.backend.mongo_enabled():
            db = self.backend.mongo_db()
            if db is not None:
                try:
                    rows = list(db.email_events.find({}, {"_id": 0}).sort("sent_at_iso", -1).limit(n))
                    return [r for r in rows if isinstance(r, dict)]
                except Exception as e:
                    print(f"[BACKEND_ERROR] Failed mongo list email events: {e}")

        if self.backend.db_enabled():
            self.backend.db_init()
            try:
                with self.backend.db_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT event_key, kind, sent_at_iso, meta_json FROM echo_email_events ORDER BY sent_at_iso DESC LIMIT %s",
                            (n,),
                        )
                        out: List[Dict[str, Any]] = []
                        for row in cur.fetchall():
                            meta = {}
                            try:
                                meta = json.loads(row[3] or "{}")
                            except Exception:
                                meta = {}
                            out.append(
                                {
                                    "event_key": str(row[0]),
                                    "kind": str(row[1]),
                                    "sent_at_iso": str(row[2]),
                                    "meta": meta,
                                }
                            )
                        return out
            except Exception as e:
                print(f"[BACKEND_ERROR] Failed db list email events: {e}")

        data = self._load_json_map(self.backend.email_events_file)
        rows = [v for v in data.values() if isinstance(v, dict)]
        rows.sort(key=lambda r: str(r.get("sent_at_iso", "")), reverse=True)
        return rows[:n]

    def append_chat_log(
        self,
        *,
        client_ip: str,
        client_id: Optional[str],
        user_message: str,
        bot_reply: str,
        sentiment: str,
        sentiment_score: int,
    ) -> None:
        now_local = datetime.now().astimezone()
        human_ts = self.format_human_timestamp(now_local)

        if self.backend.mongo_enabled():
            db = self.backend.mongo_db()
            if db is not None:
                try:
                    db.chat_logs.insert_one(
                        {
                            "timestamp": human_ts,
                            "timestamp_iso": now_local.isoformat(timespec="seconds"),
                            "ip": client_ip or "unknown",
                            "client_id": self.sanitize_client_id(client_id),
                            "sentiment": sentiment,
                            "sentiment_score": int(sentiment_score),
                            "user_message": user_message,
                            "bot_reply": bot_reply,
                        }
                    )
                    return
                except Exception as e:
                    print(f"[BACKEND_ERROR] Failed to append mongo chat log: {e}")

        if self.backend.db_enabled():
            self.backend.db_init()
            try:
                with self.backend.db_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO echo_chat_logs
                            (timestamp_text, timestamp_iso, ip, client_id, sentiment, sentiment_score, user_message, bot_reply)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                human_ts,
                                now_local.isoformat(timespec="seconds"),
                                client_ip or "unknown",
                                self.sanitize_client_id(client_id),
                                sentiment,
                                int(sentiment_score),
                                user_message,
                                bot_reply,
                            ),
                        )
                    conn.commit()
                return
            except Exception as e:
                print(f"[BACKEND_ERROR] Failed to append db chat log: {e}")

        self.ensure_data_dir(client_id)
        event = {
            "timestamp": human_ts,
            "timestamp_iso": now_local.isoformat(timespec="seconds"),
            "ip": client_ip or "unknown",
            "client_id": self.sanitize_client_id(client_id),
            "sentiment": sentiment,
            "sentiment_score": int(sentiment_score),
            "user_message": user_message,
            "bot_reply": bot_reply,
        }
        try:
            with open(self.backend.chat_log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"[BACKEND_ERROR] Failed to append chat log: {e}")

    def reconstruct_events_from_threads(self, limit: int = 600) -> List[Dict[str, Any]]:
        self.ensure_data_dir(None)
        files = glob.glob(os.path.join(self.backend.data_dir, "threads_*.json"))
        events: List[Dict[str, Any]] = []
        for path in files:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    threads = json.load(f)
            except Exception:
                continue
            client_name = os.path.basename(path).replace("threads_", "").replace(".json", "")
            for t in threads if isinstance(threads, list) else []:
                pending_user = None
                for m in t.get("messages", []):
                    role = m.get("role")
                    if role == "user":
                        pending_user = m
                    elif role == "assistant" and pending_user:
                        ts = pending_user.get("ts") or m.get("ts") or t.get("updated_at") or t.get("created_at")
                        dt = self.parse_any_timestamp(ts)
                        sentiment = self.detect_sentiment(str(pending_user.get("content", "")))
                        score = self.sentiment_to_score(sentiment)
                        events.append(
                            {
                                "timestamp": self.format_human_timestamp(dt),
                                "timestamp_iso": dt.isoformat(timespec="seconds"),
                                "ip": "unknown",
                                "client_id": client_name,
                                "sentiment": sentiment,
                                "sentiment_score": score,
                                "user_message": str(pending_user.get("content", "")),
                                "bot_reply": str(m.get("content", "")),
                            }
                        )
                        pending_user = None
        events.sort(key=lambda x: x.get("timestamp_iso", ""), reverse=True)
        return events[: max(1, min(limit, 3000))]

    def get_chat_logs(self, limit: int = 200) -> List[Dict[str, Any]]:
        n = max(1, min(limit, 3000))
        if self.backend.mongo_enabled():
            db = self.backend.mongo_db()
            if db is not None:
                try:
                    docs = list(db.chat_logs.find({}, {"_id": 0}).sort("timestamp_iso", -1).limit(n))
                    if docs:
                        return docs
                except Exception as e:
                    print(f"[BACKEND_ERROR] Failed to fetch mongo chat logs: {e}")

        if self.backend.db_enabled():
            self.backend.db_init()
            try:
                out: List[Dict[str, Any]] = []
                with self.backend.db_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            SELECT timestamp_text, timestamp_iso, ip, client_id, sentiment, sentiment_score, user_message, bot_reply
                            FROM echo_chat_logs
                            ORDER BY timestamp_iso DESC
                            LIMIT %s
                            """,
                            (n,),
                        )
                        for row in cur.fetchall():
                            out.append(
                                {
                                    "timestamp": row[0],
                                    "timestamp_iso": row[1],
                                    "ip": row[2],
                                    "client_id": row[3],
                                    "sentiment": row[4],
                                    "sentiment_score": int(row[5]),
                                    "user_message": row[6],
                                    "bot_reply": row[7],
                                }
                            )
                return out
            except Exception as e:
                print(f"[BACKEND_ERROR] Failed to fetch db chat logs: {e}")

        self.ensure_data_dir(None)
        rows: List[Dict[str, Any]] = []
        if os.path.exists(self.backend.chat_log_file):
            try:
                with open(self.backend.chat_log_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rows.append(json.loads(line))
                        except Exception:
                            continue
            except Exception as e:
                print(f"[BACKEND_ERROR] Failed to read chat logs: {e}")

        reconstructed = self.reconstruct_events_from_threads(limit=2000)
        merged: Dict[str, Dict[str, Any]] = {}
        for r in rows + reconstructed:
            day_key = (
                str(r.get("timestamp_iso", "")).split("T")[0]
                if r.get("timestamp_iso")
                else str(r.get("timestamp", "")).split(" ")[0]
            )
            key = "|".join(
                [
                    str(r.get("client_id", "")),
                    str(r.get("user_message", "")),
                    str(r.get("bot_reply", "")),
                    day_key,
                ]
            )
            if key not in merged:
                merged[key] = r
                continue

            existing = merged[key]
            existing_ip = str(existing.get("ip", "")).strip().lower()
            current_ip = str(r.get("ip", "")).strip().lower()
            existing_ts = str(existing.get("timestamp_iso", ""))
            current_ts = str(r.get("timestamp_iso", ""))

            if existing_ip in ("", "unknown") and current_ip not in ("", "unknown"):
                merged[key] = r
            elif current_ts > existing_ts:
                merged[key] = r

        out = list(merged.values())
        out.sort(key=lambda x: x.get("timestamp_iso", ""), reverse=True)
        return out[:n]

    def load_threads(self, client_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if self.backend.mongo_enabled():
            db = self.backend.mongo_db()
            if db is not None:
                try:
                    cid = self.sanitize_client_id(client_id)
                    docs = db.threads.find({"client_id": cid}, {"_id": 0}).sort("updated_at", -1)
                    out: List[Dict[str, Any]] = []
                    for d in docs:
                        out.append(
                            {
                                "id": str(d.get("thread_id", "")),
                                "title": str(d.get("title", "New Conversation")),
                                "messages": d.get("messages", []),
                                "created_at": str(d.get("created_at", "")),
                                "updated_at": str(d.get("updated_at", "")),
                            }
                        )
                    return out
                except Exception as e:
                    print(f"[BACKEND_ERROR] Failed to load mongo threads: {e}")

        if self.backend.db_enabled():
            self.backend.db_init()
            try:
                cid = self.sanitize_client_id(client_id)
                out: List[Dict[str, Any]] = []
                with self.backend.db_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            SELECT thread_id, title, messages_json, created_at, updated_at
                            FROM echo_threads
                            WHERE client_id = %s
                            ORDER BY updated_at DESC
                            """,
                            (cid,),
                        )
                        for row in cur.fetchall():
                            try:
                                messages = json.loads(row[2])
                            except Exception:
                                messages = []
                            out.append(
                                {
                                    "id": str(row[0]),
                                    "title": str(row[1]),
                                    "messages": messages,
                                    "created_at": str(row[3]),
                                    "updated_at": str(row[4]),
                                }
                            )
                return out
            except Exception as e:
                print(f"[BACKEND_ERROR] Failed to load db threads: {e}")

        self.ensure_data_dir(client_id)
        threads_file = self.threads_file_for_client(client_id)
        try:
            with open(threads_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[BACKEND_ERROR] Failed to load threads: {e}")
            return []

    def save_threads(self, threads: List[Dict[str, Any]], client_id: Optional[str] = None) -> None:
        if self.backend.mongo_enabled():
            db = self.backend.mongo_db()
            if db is not None:
                try:
                    cid = self.sanitize_client_id(client_id)
                    current_ids = [str(t.get("id", "")) for t in threads]
                    db.threads.delete_many({"client_id": cid, "thread_id": {"$nin": current_ids}})
                    for t in threads:
                        db.threads.update_one(
                            {"client_id": cid, "thread_id": str(t.get("id", ""))},
                            {
                                "$set": {
                                    "client_id": cid,
                                    "thread_id": str(t.get("id", "")),
                                    "title": str(t.get("title", "New Conversation")),
                                    "messages": t.get("messages", []),
                                    "created_at": str(t.get("created_at", "")),
                                    "updated_at": str(t.get("updated_at", "")),
                                }
                            },
                            upsert=True,
                        )
                    return
                except Exception as e:
                    print(f"[BACKEND_ERROR] Failed to save mongo threads: {e}")

        if self.backend.db_enabled():
            self.backend.db_init()
            try:
                cid = self.sanitize_client_id(client_id)
                with self.backend.db_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("DELETE FROM echo_threads WHERE client_id = %s", (cid,))
                        for t in threads:
                            cur.execute(
                                """
                                INSERT INTO echo_threads (client_id, thread_id, title, messages_json, created_at, updated_at)
                                VALUES (%s, %s, %s, %s, %s, %s)
                                """,
                                (
                                    cid,
                                    str(t.get("id", "")),
                                    str(t.get("title", "New Conversation")),
                                    json.dumps(t.get("messages", []), ensure_ascii=False),
                                    str(t.get("created_at", "")),
                                    str(t.get("updated_at", "")),
                                ),
                            )
                    conn.commit()
                return
            except Exception as e:
                print(f"[BACKEND_ERROR] Failed to save db threads: {e}")

        self.ensure_data_dir(client_id)
        threads_file = self.threads_file_for_client(client_id)
        try:
            with open(threads_file, "w", encoding="utf-8") as f:
                json.dump(threads, f, ensure_ascii=False)
        except Exception as e:
            print(f"[BACKEND_ERROR] Failed to save threads: {e}")

