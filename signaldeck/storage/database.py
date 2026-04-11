import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from signaldeck.storage.models import Signal, ActivityEntry

_SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    frequency REAL NOT NULL,
    bandwidth REAL NOT NULL,
    modulation TEXT NOT NULL,
    protocol TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    hit_count INTEGER NOT NULL DEFAULT 1,
    avg_strength REAL NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.0,
    classification_data TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_signals_frequency ON signals(frequency);

CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER NOT NULL,
    timestamp TEXT NOT NULL,
    duration REAL NOT NULL,
    strength REAL NOT NULL,
    decoder_used TEXT,
    result_type TEXT NOT NULL,
    summary TEXT NOT NULL,
    audio_path TEXT,
    raw_result TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (signal_id) REFERENCES signals(id)
);

CREATE INDEX IF NOT EXISTS idx_activity_timestamp ON activity_log(timestamp);

CREATE TABLE IF NOT EXISTS bookmarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    frequency REAL NOT NULL,
    label TEXT NOT NULL,
    modulation TEXT NOT NULL,
    decoder TEXT,
    priority INTEGER NOT NULL DEFAULT 3,
    camp_on_active INTEGER NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recordings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id INTEGER,
    signal_id INTEGER,
    frequency REAL NOT NULL,
    timestamp TEXT NOT NULL,
    duration REAL NOT NULL,
    format TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    transcription TEXT,
    FOREIGN KEY (activity_id) REFERENCES activity_log(id),
    FOREIGN KEY (signal_id) REFERENCES signals(id)
);

CREATE TABLE IF NOT EXISTS learned_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER NOT NULL,
    day_of_week INTEGER NOT NULL,
    hour_start INTEGER NOT NULL,
    hour_end INTEGER NOT NULL,
    avg_activity_minutes REAL NOT NULL DEFAULT 0.0,
    last_updated TEXT NOT NULL,
    FOREIGN KEY (signal_id) REFERENCES signals(id)
);

CREATE TABLE IF NOT EXISTS decoder_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id INTEGER NOT NULL,
    decoder TEXT NOT NULL,
    protocol TEXT NOT NULL,
    result_type TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '{}',
    timestamp TEXT NOT NULL,
    FOREIGN KEY (activity_id) REFERENCES activity_log(id)
);

CREATE TABLE IF NOT EXISTS remember_tokens (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash     TEXT NOT NULL UNIQUE,
    created_at     TEXT NOT NULL,
    last_used_at   TEXT NOT NULL,
    user_agent     TEXT,
    ip_first_seen  TEXT,
    label          TEXT
);

CREATE INDEX IF NOT EXISTS idx_remember_tokens_hash ON remember_tokens(token_hash);
"""


def _dt_to_str(dt: datetime) -> str:
    return dt.isoformat()


def _str_to_dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


class Database:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None
        self._lock: asyncio.Lock | None = None

    async def initialize(self) -> None:
        self._lock = asyncio.Lock()
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        # WAL mode allows concurrent reads while writing
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def commit(self) -> None:
        await self._conn.commit()

    async def list_tables(self) -> list[str]:
        cursor = await self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        rows = await cursor.fetchall()
        return [row["name"] for row in rows]

    async def upsert_signal(self, signal: Signal, *, commit: bool = True) -> int:
        existing = await self.get_signal_by_frequency(signal.frequency, tolerance_hz=1000)
        if existing and existing.id is not None:
            await self._conn.execute(
                """UPDATE signals
                   SET hit_count = hit_count + 1,
                       last_seen = ?,
                       avg_strength = ?,
                       modulation = ?,
                       protocol = COALESCE(?, protocol),
                       confidence = MAX(confidence, ?)
                   WHERE id = ?""",
                (
                    _dt_to_str(signal.last_seen),
                    signal.avg_strength,
                    signal.modulation,
                    signal.protocol,
                    signal.confidence,
                    existing.id,
                ),
            )
            if commit:
                await self._conn.commit()
            return existing.id

        cursor = await self._conn.execute(
            """INSERT INTO signals
               (frequency, bandwidth, modulation, protocol, first_seen, last_seen,
                hit_count, avg_strength, confidence, classification_data)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                signal.frequency,
                signal.bandwidth,
                signal.modulation,
                signal.protocol,
                _dt_to_str(signal.first_seen),
                _dt_to_str(signal.last_seen),
                signal.hit_count,
                signal.avg_strength,
                signal.confidence,
                json.dumps(signal.classification_data),
            ),
        )
        if commit:
            await self._conn.commit()
        return cursor.lastrowid

    async def get_signal_by_id(self, signal_id: int) -> Signal | None:
        cursor = await self._conn.execute(
            "SELECT * FROM signals WHERE id = ?", (signal_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return Signal(
            id=row["id"],
            frequency=row["frequency"],
            bandwidth=row["bandwidth"],
            modulation=row["modulation"],
            protocol=row["protocol"],
            first_seen=_str_to_dt(row["first_seen"]),
            last_seen=_str_to_dt(row["last_seen"]),
            hit_count=row["hit_count"],
            avg_strength=row["avg_strength"],
            confidence=row["confidence"],
            classification_data=json.loads(row["classification_data"]),
        )

    async def get_signal_by_frequency(
        self, frequency: float, tolerance_hz: float = 1000
    ) -> Signal | None:
        cursor = await self._conn.execute(
            "SELECT * FROM signals WHERE ABS(frequency - ?) <= ? LIMIT 1",
            (frequency, tolerance_hz),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return Signal(
            id=row["id"],
            frequency=row["frequency"],
            bandwidth=row["bandwidth"],
            modulation=row["modulation"],
            protocol=row["protocol"],
            first_seen=_str_to_dt(row["first_seen"]),
            last_seen=_str_to_dt(row["last_seen"]),
            hit_count=row["hit_count"],
            avg_strength=row["avg_strength"],
            confidence=row["confidence"],
            classification_data=json.loads(row["classification_data"]),
        )

    async def get_all_signals(self) -> list[Signal]:
        cursor = await self._conn.execute("SELECT * FROM signals ORDER BY frequency")
        rows = await cursor.fetchall()
        return [
            Signal(
                id=row["id"],
                frequency=row["frequency"],
                bandwidth=row["bandwidth"],
                modulation=row["modulation"],
                protocol=row["protocol"],
                first_seen=_str_to_dt(row["first_seen"]),
                last_seen=_str_to_dt(row["last_seen"]),
                hit_count=row["hit_count"],
                avg_strength=row["avg_strength"],
                confidence=row["confidence"],
                classification_data=json.loads(row["classification_data"]),
            )
            for row in rows
        ]

    async def insert_activity(self, entry: ActivityEntry, *, commit: bool = True) -> int:
        cursor = await self._conn.execute(
            """INSERT INTO activity_log
               (signal_id, timestamp, duration, strength, decoder_used,
                result_type, summary, audio_path, raw_result)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.signal_id,
                _dt_to_str(entry.timestamp),
                entry.duration,
                entry.strength,
                entry.decoder_used,
                entry.result_type,
                entry.summary,
                entry.audio_path,
                json.dumps(entry.raw_result),
            ),
        )
        if commit:
            await self._conn.commit()
        return cursor.lastrowid

    async def insert_bookmark(self, bookmark) -> int:
        cursor = await self._conn.execute(
            """INSERT INTO bookmarks (frequency, label, modulation, decoder, priority,
               camp_on_active, notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (bookmark.frequency, bookmark.label, bookmark.modulation, bookmark.decoder,
             bookmark.priority, int(bookmark.camp_on_active), bookmark.notes,
             _dt_to_str(bookmark.created_at)))
        await self._conn.commit()
        return cursor.lastrowid

    async def get_all_bookmarks(self):
        from signaldeck.storage.models import Bookmark
        cursor = await self._conn.execute("SELECT * FROM bookmarks ORDER BY priority DESC, frequency")
        rows = await cursor.fetchall()
        return [Bookmark(id=row["id"], frequency=row["frequency"], label=row["label"],
                modulation=row["modulation"], decoder=row["decoder"], priority=row["priority"],
                camp_on_active=bool(row["camp_on_active"]), notes=row["notes"],
                created_at=_str_to_dt(row["created_at"])) for row in rows]

    async def delete_bookmark(self, bookmark_id: int) -> bool:
        cursor = await self._conn.execute("DELETE FROM bookmarks WHERE id = ?", (bookmark_id,))
        await self._conn.commit()
        return cursor.rowcount > 0

    async def update_bookmark(
        self,
        bookmark_id: int,
        *,
        label: str | None = None,
        modulation: str | None = None,
        decoder: str | None = None,
        priority: int | None = None,
        camp_on_active: bool | None = None,
        notes: str | None = None,
    ) -> bool:
        """Partial update of a bookmark.

        Only fields passed with a non-None value are modified — this
        lets callers do "change just label and priority" without having
        to resend every other field. `notes=""` clears the notes to
        empty string (not null), which is the distinction the spec uses
        to separate "don't touch this field" from "clear this field".

        Returns True if the row existed (and was updated if there were
        any fields to change), False if no such bookmark. An empty
        kwargs call is treated as an existence check.
        """
        updates: list[str] = []
        params: list = []
        if label is not None:
            updates.append("label = ?")
            params.append(label)
        if modulation is not None:
            updates.append("modulation = ?")
            params.append(modulation)
        if decoder is not None:
            updates.append("decoder = ?")
            params.append(decoder)
        if priority is not None:
            updates.append("priority = ?")
            params.append(priority)
        if camp_on_active is not None:
            updates.append("camp_on_active = ?")
            params.append(int(camp_on_active))
        if notes is not None:
            updates.append("notes = ?")
            params.append(notes)

        if not updates:
            # No fields to change — just report whether the row exists.
            cursor = await self._conn.execute(
                "SELECT id FROM bookmarks WHERE id = ?", (bookmark_id,)
            )
            row = await cursor.fetchone()
            return row is not None

        params.append(bookmark_id)
        sql = f"UPDATE bookmarks SET {', '.join(updates)} WHERE id = ?"
        cursor = await self._conn.execute(sql, params)
        await self._conn.commit()
        return cursor.rowcount > 0

    # ---- Remember-me tokens (long-lived session cookies) ----

    async def insert_remember_token(
        self,
        *,
        token_hash: str,
        user_agent: str | None,
        ip_first_seen: str | None,
        label: str | None,
    ) -> int:
        """Insert a new remember-me token row. Returns the new row id."""
        now = datetime.now(timezone.utc).isoformat()
        cursor = await self._conn.execute(
            """INSERT INTO remember_tokens
               (token_hash, created_at, last_used_at, user_agent, ip_first_seen, label)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (token_hash, now, now, user_agent, ip_first_seen, label),
        )
        await self._conn.commit()
        return cursor.lastrowid

    async def get_remember_token_by_hash(self, token_hash: str) -> dict | None:
        """Return the row dict for a given hash, or None if not found."""
        cursor = await self._conn.execute(
            """SELECT id, token_hash, created_at, last_used_at, user_agent, ip_first_seen, label
               FROM remember_tokens WHERE token_hash = ?""",
            (token_hash,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    async def update_remember_token_last_used(self, token_hash: str) -> None:
        """Touch last_used_at for an existing token. No-op if missing."""
        now = datetime.now(timezone.utc).isoformat()
        await self._conn.execute(
            "UPDATE remember_tokens SET last_used_at = ? WHERE token_hash = ?",
            (now, token_hash),
        )
        await self._conn.commit()

    async def list_remember_tokens(self) -> list[dict]:
        """Return all rows MINUS token_hash (never exposed to callers)."""
        cursor = await self._conn.execute(
            """SELECT id, created_at, last_used_at, user_agent, ip_first_seen, label
               FROM remember_tokens
               ORDER BY last_used_at DESC""",
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def rename_remember_token(self, token_id: int, label: str) -> bool:
        """Update a row's label. Returns True on success, False if missing."""
        cursor = await self._conn.execute(
            "UPDATE remember_tokens SET label = ? WHERE id = ?",
            (label, token_id),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    async def revoke_remember_token(self, token_id: int) -> bool:
        """Delete a row. Returns True on success, False if missing."""
        cursor = await self._conn.execute(
            "DELETE FROM remember_tokens WHERE id = ?",
            (token_id,),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    async def get_recent_activity(self, limit: int = 50) -> list[ActivityEntry]:
        cursor = await self._conn.execute(
            "SELECT * FROM activity_log ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [
            ActivityEntry(
                id=row["id"],
                signal_id=row["signal_id"],
                timestamp=_str_to_dt(row["timestamp"]),
                duration=row["duration"],
                strength=row["strength"],
                decoder_used=row["decoder_used"],
                result_type=row["result_type"],
                summary=row["summary"],
                audio_path=row["audio_path"],
                raw_result=json.loads(row["raw_result"]),
            )
            for row in rows
        ]

    async def get_recordings(self, limit: int = 200) -> list[dict]:
        cursor = await self._conn.execute(
            """SELECT *
               FROM recordings
               ORDER BY timestamp DESC
               LIMIT ?""",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": row["id"],
                "activity_id": row["activity_id"],
                "signal_id": row["signal_id"],
                "frequency": row["frequency"],
                "frequency_hz": row["frequency"],
                "frequency_mhz": round(row["frequency"] / 1e6, 4),
                "timestamp": row["timestamp"],
                "duration": row["duration"],
                "format": row["format"],
                "file_path": row["file_path"],
                "file_size": row["file_size"],
                "transcription": row["transcription"],
            }
            for row in rows
        ]

    async def clear_signals(self) -> None:
        async with self._lock:
            await self._conn.execute("DELETE FROM signals")
            await self._conn.commit()

    async def clear_activity(self) -> None:
        async with self._lock:
            await self._conn.execute("DELETE FROM activity_log")
            await self._conn.commit()

    async def clear_bookmarks(self) -> None:
        async with self._lock:
            await self._conn.execute("DELETE FROM bookmarks")
            await self._conn.commit()

    async def clear_recordings(self) -> None:
        async with self._lock:
            await self._conn.execute("DELETE FROM recordings")
            await self._conn.commit()

    async def clear_all(self) -> None:
        async with self._lock:
            for table in ("signals", "activity_log", "bookmarks", "recordings",
                          "decoder_results", "learned_patterns"):
                await self._conn.execute(f"DELETE FROM {table}")
            await self._conn.commit()

    async def get_stats(self) -> dict:
        counts = {}
        for name, table in [("signals", "signals"), ("activity", "activity_log"),
                            ("bookmarks", "bookmarks"), ("recordings", "recordings")]:
            cursor = await self._conn.execute(f"SELECT COUNT(*) FROM {table}")
            row = await cursor.fetchone()
            counts[name] = row[0]
        counts["db_size"] = Path(self._db_path).stat().st_size
        return counts

    async def insert_decoder_result(
        self, activity_id: int, decoder: str, protocol: str,
        result_type: str, content: dict,
    ) -> int:
        cursor = await self._conn.execute(
            """INSERT INTO decoder_results
               (activity_id, decoder, protocol, result_type, content, timestamp)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (activity_id, decoder, protocol, result_type,
             json.dumps(content),
             datetime.now(timezone.utc).isoformat()),
        )
        await self._conn.commit()
        return cursor.lastrowid

    async def get_rds_for_frequency(
        self, frequency_hz: float, tolerance_hz: float = 5000,
    ) -> dict | None:
        cursor = await self._conn.execute(
            """SELECT dr.content FROM decoder_results dr
               JOIN activity_log al ON dr.activity_id = al.id
               JOIN signals s ON al.signal_id = s.id
               WHERE ABS(s.frequency - ?) <= ?
                 AND dr.decoder = 'rds'
               ORDER BY dr.timestamp DESC LIMIT 1""",
            (frequency_hz, tolerance_hz),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return json.loads(row["content"])

    async def get_decoder_results(
        self,
        *,
        signal_id: int | None = None,
        decoder: str | None = None,
        protocol: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        where = []
        params: list[object] = []
        if signal_id is not None:
            where.append("al.signal_id = ?")
            params.append(signal_id)
        if decoder is not None:
            where.append("dr.decoder = ?")
            params.append(decoder)
        if protocol is not None:
            where.append("dr.protocol = ?")
            params.append(protocol)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        params.append(limit)
        cursor = await self._conn.execute(
            f"""SELECT dr.*, al.signal_id
                FROM decoder_results dr
                JOIN activity_log al ON dr.activity_id = al.id
                {where_sql}
                ORDER BY dr.timestamp DESC
                LIMIT ?""",
            params,
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": row["id"],
                "activity_id": row["activity_id"],
                "signal_id": row["signal_id"],
                "decoder": row["decoder"],
                "protocol": row["protocol"],
                "result_type": row["result_type"],
                "timestamp": row["timestamp"],
                "content": json.loads(row["content"]),
            }
            for row in rows
        ]
