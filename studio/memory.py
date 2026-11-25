"""Local long-term memory for DDG bots: SQLite + FTS5 keyword recall. 100% local, zero VRAM, A$0."""

from __future__ import annotations

import re
import sqlite3
import threading
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
_TOKEN_RE = re.compile(r"[A-Za-z0-9']{3,}")
_STOP = {
    "the", "and", "for", "you", "that", "with", "this", "have", "are", "was", "but", "not",
    "what", "when", "where", "how", "can", "could", "would", "should", "please", "about",
    "from", "your", "our", "just", "they", "them", "their", "there", "then", "than", "will",
}


class BotMemory:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS msgs ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT NOT NULL, sender TEXT NOT NULL, "
                "text TEXT NOT NULL, ts TEXT NOT NULL)"
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_msgs_scope ON msgs(scope, id)")
            try:
                con.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS msgs_fts USING fts5(text, content='msgs', content_rowid='id')"
                )
                self.fts = True
            except sqlite3.OperationalError:
                self.fts = False

    def _conn(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.db_path), timeout=10)
        con.row_factory = sqlite3.Row
        return con

    def add(self, scope: str, sender: str, text: str, ts: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        with _LOCK, self._conn() as con:
            cur = con.execute(
                "INSERT INTO msgs(scope, sender, text, ts) VALUES (?,?,?,?)", (scope, sender, text, ts)
            )
            if self.fts:
                con.execute("INSERT INTO msgs_fts(rowid, text) VALUES (?,?)", (cur.lastrowid, text))

    def recall(self, scope: str, query: str, limit: int = 4, skip_recent: int = 6) -> list[dict[str, Any]]:
        """Return older messages in this scope relevant to the query (skips the most recent turns)."""
        words = [w.lower() for w in _TOKEN_RE.findall(query or "") if w.lower() not in _STOP]
        if not words:
            return []
        with _LOCK, self._conn() as con:
            cutoff_row = con.execute(
                "SELECT id FROM msgs WHERE scope=? ORDER BY id DESC LIMIT 1 OFFSET ?", (scope, skip_recent)
            ).fetchone()
            if cutoff_row is None:
                return []
            max_id = int(cutoff_row["id"])
            if self.fts:
                match = " OR ".join(f'"{w}"' for w in words[:8])
                try:
                    rows = con.execute(
                        "SELECT m.sender, m.text, m.ts FROM msgs_fts f JOIN msgs m ON m.id=f.rowid "
                        "WHERE msgs_fts MATCH ? AND m.scope=? AND m.id<=? ORDER BY rank LIMIT ?",
                        (match, scope, max_id, limit),
                    ).fetchall()
                    return [dict(r) for r in rows]
                except sqlite3.OperationalError:
                    pass
            like = " OR ".join("text LIKE ?" for _ in words[:6])
            rows = con.execute(
                f"SELECT sender, text, ts FROM msgs WHERE scope=? AND id<=? AND ({like}) ORDER BY id DESC LIMIT ?",
                (scope, max_id, *[f"%{w}%" for w in words[:6]], limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def format_recall(self, scope: str, query: str) -> str:
        hits = self.recall(scope, query)
        if not hits:
            return ""
        lines = [f"- [{h['ts'][:10]}] {h['sender']}: {h['text'][:240]}" for h in hits]
        return "Relevant older conversation memory (use only if helpful):\n" + "\n".join(lines)
