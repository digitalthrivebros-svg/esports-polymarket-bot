"""SQLite persistence layer for match history, signals, trades, and P&L tracking."""

import sqlite3
import logging
from datetime import date, datetime
from typing import Any

from config import DB_PATH

logger = logging.getLogger(__name__)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """Create tables if they do not exist."""
    conn = _connect()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS matches (
                match_id   TEXT PRIMARY KEY,
                teams      TEXT NOT NULL,
                tournament TEXT,
                start_time TEXT,
                format     TEXT,
                status     TEXT DEFAULT 'upcoming'
            );

            CREATE TABLE IF NOT EXISTS signals (
                signal_id      INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id       TEXT NOT NULL,
                timestamp      TEXT NOT NULL DEFAULT (datetime('now')),
                pinnacle_prob  REAL,
                pm_price       REAL,
                edge           REAL,
                source         TEXT,
                FOREIGN KEY (match_id) REFERENCES matches(match_id)
            );

            CREATE TABLE IF NOT EXISTS trades (
                trade_id         INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id        INTEGER,
                token_id         TEXT NOT NULL,
                side             TEXT NOT NULL,
                price            REAL NOT NULL,
                size             REAL NOT NULL,
                order_id         TEXT,
                status           TEXT DEFAULT 'pending',
                fill_price       REAL,
                settlement_price REAL,
                pnl              REAL,
                match_id         TEXT,
                teams            TEXT,
                team_backed      TEXT,
                created_at       TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (signal_id) REFERENCES signals(signal_id)
            );

            CREATE TABLE IF NOT EXISTS daily_pnl (
                date           TEXT PRIMARY KEY,
                realized_pnl   REAL DEFAULT 0,
                unrealized_pnl REAL DEFAULT 0,
                num_trades     INTEGER DEFAULT 0,
                win_rate       REAL DEFAULT 0
            );
            """
        )
        conn.commit()

        # Migrate existing tables: add columns that may not exist yet
        _migrate_add_column(conn, "trades", "settlement_price", "REAL")
        _migrate_add_column(conn, "trades", "match_id", "TEXT")
        _migrate_add_column(conn, "trades", "teams", "TEXT")
        _migrate_add_column(conn, "trades", "team_backed", "TEXT")

        logger.info("Database initialized at %s", DB_PATH)
    finally:
        conn.close()


def _migrate_add_column(conn: sqlite3.Connection, table: str, column: str, col_type: str) -> None:
    """Add a column to a table if it doesn't already exist."""
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists


def log_signal(
    match_id: str,
    pinnacle_prob: float | None,
    pm_price: float | None,
    edge: float | None,
    source: str = "",
) -> int:
    """Insert a pricing signal and return its ID."""
    conn = _connect()
    try:
        cur = conn.execute(
            "INSERT INTO signals (match_id, pinnacle_prob, pm_price, edge, source) "
            "VALUES (?, ?, ?, ?, ?)",
            (match_id, pinnacle_prob, pm_price, edge, source),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]
    finally:
        conn.close()


def log_trade(
    signal_id: int | None,
    token_id: str,
    side: str,
    price: float,
    size: float,
    order_id: str = "",
    status: str = "pending",
    match_id: str = "",
    teams: str = "",
    team_backed: str = "",
) -> int:
    """Record a trade and return its ID."""
    conn = _connect()
    try:
        cur = conn.execute(
            "INSERT INTO trades (signal_id, token_id, side, price, size, order_id, status, match_id, teams, team_backed) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (signal_id, token_id, side, price, size, order_id, status, match_id, teams, team_backed),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]
    finally:
        conn.close()


def update_trade(trade_id: int, **kwargs: Any) -> None:
    """Update fields on an existing trade (e.g. status, fill_price, pnl)."""
    if not kwargs:
        return
    set_clause = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [trade_id]
    conn = _connect()
    try:
        conn.execute(f"UPDATE trades SET {set_clause} WHERE trade_id = ?", values)
        conn.commit()
    finally:
        conn.close()


def log_match(
    match_id: str,
    teams: str,
    tournament: str = "",
    start_time: str = "",
    fmt: str = "",
    status: str = "upcoming",
) -> None:
    """Upsert a match record."""
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO matches (match_id, teams, tournament, start_time, format, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (match_id, teams, tournament, start_time, fmt, status),
        )
        conn.commit()
    finally:
        conn.close()


def get_daily_pnl(day: date | None = None) -> dict[str, Any]:
    """Return P&L summary for a given day (defaults to today)."""
    day = day or date.today()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM daily_pnl WHERE date = ?", (day.isoformat(),)
        ).fetchone()
        if row:
            return dict(row)
        return {
            "date": day.isoformat(),
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "num_trades": 0,
            "win_rate": 0.0,
        }
    finally:
        conn.close()


def get_open_positions() -> list[dict[str, Any]]:
    """Return all trades that are not yet settled."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM trades WHERE status IN ('pending', 'filled') ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_daily_pnl(
    day: date | None = None,
    realized_pnl: float = 0.0,
    unrealized_pnl: float = 0.0,
    num_trades: int = 0,
    win_rate: float = 0.0,
) -> None:
    """Upsert daily P&L record."""
    day = day or date.today()
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO daily_pnl (date, realized_pnl, unrealized_pnl, num_trades, win_rate) "
            "VALUES (?, ?, ?, ?, ?)",
            (day.isoformat(), realized_pnl, unrealized_pnl, num_trades, win_rate),
        )
        conn.commit()
    finally:
        conn.close()


def get_unsettled_trades() -> list[dict[str, Any]]:
    """Return all trades with status 'open' or 'filled' (awaiting settlement)."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM trades WHERE status IN ('open', 'filled', 'pending') ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_trade_history(days: int = 30) -> list[dict[str, Any]]:
    """Return all settled trades with P&L from the last N days."""
    conn = _connect()
    try:
        cutoff = datetime.now().isoformat()[:10]  # today
        rows = conn.execute(
            "SELECT * FROM trades WHERE status IN ('won', 'lost', 'settled') "
            "AND created_at >= date(?, '-' || ? || ' days') "
            "ORDER BY created_at DESC",
            (cutoff, days),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_performance_summary() -> dict[str, Any]:
    """Return all-time performance stats: total P&L, win rate, ROI, avg edge, num trades, best/worst trade."""
    conn = _connect()
    try:
        row = conn.execute(
            """
            SELECT
                COUNT(*) as num_trades,
                COALESCE(SUM(pnl), 0) as total_pnl,
                COALESCE(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), 0) as wins,
                COALESCE(SUM(size), 0) as total_wagered,
                COALESCE(MAX(pnl), 0) as best_trade,
                COALESCE(MIN(pnl), 0) as worst_trade
            FROM trades
            WHERE status IN ('won', 'lost', 'settled')
            """
        ).fetchone()

        if not row or row["num_trades"] == 0:
            return {
                "num_trades": 0, "total_pnl": 0.0, "win_rate": 0.0,
                "roi": 0.0, "avg_edge": 0.0, "best_trade": 0.0, "worst_trade": 0.0,
            }

        d = dict(row)
        d["win_rate"] = d["wins"] / d["num_trades"] if d["num_trades"] else 0.0
        d["roi"] = d["total_pnl"] / d["total_wagered"] if d["total_wagered"] else 0.0

        # Avg edge from signals linked to settled trades
        edge_row = conn.execute(
            """
            SELECT COALESCE(AVG(s.edge), 0) as avg_edge
            FROM trades t
            JOIN signals s ON t.signal_id = s.signal_id
            WHERE t.status IN ('won', 'lost', 'settled')
            """
        ).fetchone()
        d["avg_edge"] = edge_row["avg_edge"] if edge_row else 0.0

        return d
    finally:
        conn.close()
