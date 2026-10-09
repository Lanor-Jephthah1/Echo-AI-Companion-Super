from contextlib import contextmanager
import os
from typing import Any


class StorageBackend:
    """Backend selection and connection lifecycle for Mongo/Postgres/file storage."""

    def __init__(
        self,
        *,
        data_dir: str,
        chat_log_file: str,
        email_events_file: str,
        shared_links_file: str,
        shared_snapshots_file: str,
    ) -> None:
        self.data_dir = data_dir
        self.chat_log_file = chat_log_file
        self.email_events_file = email_events_file
        self.shared_links_file = shared_links_file
        self.shared_snapshots_file = shared_snapshots_file
        self._db_ready = False
        self._mongo_client: Any = None

    def db_url(self) -> str:
        return (
            os.environ.get("DATABASE_URL", "").strip()
            or os.environ.get("POSTGRES_URL", "").strip()
            or os.environ.get("POSTGRES_PRISMA_URL", "").strip()
        )

    def db_enabled(self) -> bool:
        return bool(self.db_url())

    def mongo_uri(self) -> str:
        return os.environ.get("MONGODB_URI", "").strip().strip('"').strip("'")

    def mongo_enabled(self) -> bool:
        return bool(self.mongo_uri())

    def mongo_db(self):
        if not self.mongo_enabled():
            return None
        try:
            from pymongo import MongoClient
        except Exception as e:
            print(f"[BACKEND_ERROR] pymongo import failed: {e}")
            return None
        if self._mongo_client is None:
            self._mongo_client = MongoClient(self.mongo_uri())
        return self._mongo_client["echo_ai"]

    @contextmanager
    def db_conn(self):
        import psycopg2  # lazy import for local file-only mode

        conn = psycopg2.connect(self.db_url())
        try:
            yield conn
        finally:
            conn.close()

    def db_init(self) -> None:
        if self._db_ready or not self.db_enabled():
            return
        try:
            with self.db_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS echo_threads (
                          client_id TEXT NOT NULL,
                          thread_id TEXT NOT NULL,
                          title TEXT NOT NULL,
                          messages_json TEXT NOT NULL,
                          created_at TEXT NOT NULL,
                          updated_at TEXT NOT NULL,
                          PRIMARY KEY (client_id, thread_id)
                        );
                        """
                    )
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS echo_chat_logs (
                          id BIGSERIAL PRIMARY KEY,
                          timestamp_text TEXT NOT NULL,
                          timestamp_iso TEXT NOT NULL,
                          ip TEXT NOT NULL,
                          client_id TEXT NOT NULL,
                          sentiment TEXT NOT NULL,
                          sentiment_score INTEGER NOT NULL,
                          user_message TEXT NOT NULL,
                          bot_reply TEXT NOT NULL
                        );
                        """
                    )
                    cur.execute(
                        "CREATE INDEX IF NOT EXISTS idx_echo_chat_logs_timestamp_iso ON echo_chat_logs(timestamp_iso DESC);"
                    )
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS echo_email_events (
                          event_key TEXT PRIMARY KEY,
                          kind TEXT NOT NULL,
                          sent_at_iso TEXT NOT NULL,
                          meta_json TEXT NOT NULL
                        );
                        """
                    )
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS echo_shared_links (
                          share_id TEXT PRIMARY KEY,
                          source_client_id TEXT NOT NULL,
                          source_thread_id TEXT NOT NULL,
                          created_at TEXT NOT NULL,
                          updated_at TEXT NOT NULL
                        );
                        """
                    )
                conn.commit()
            self._db_ready = True
        except Exception as e:
            print(f"[BACKEND_ERROR] DB init failed: {e}")

