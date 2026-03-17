import sqlite3
import json
import os
from datetime import datetime, timezone
from typing import Dict, Any, Optional

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "events.db"))

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE,
            name TEXT,
            picture TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            last_login TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS preferences (
            user_id TEXT PRIMARY KEY REFERENCES users(id),
            topics TEXT DEFAULT '',
            types TEXT DEFAULT '["All"]',
            locations TEXT DEFAULT '["All"]',
            sponsors TEXT DEFAULT '["All"]',
            perks TEXT DEFAULT '["All"]',
            formats TEXT DEFAULT '["All"]',
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS user_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT REFERENCES users(id),
            event_id INTEGER,
            action TEXT,  -- 'interested', 'calendar_added', 'hidden', 'disliked', 'not_interested'
            title TEXT,
            group_name TEXT,
            topics TEXT,  -- JSON array
            expires_at TEXT,  -- for not_interested
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS dislike_counts (
            user_id TEXT REFERENCES users(id),
            category TEXT,  -- 'topics' or 'sponsors'
            value TEXT,
            count INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, category, value)
        );

        CREATE INDEX IF NOT EXISTS idx_user_actions_user ON user_actions(user_id);
        CREATE INDEX IF NOT EXISTS idx_user_actions_action ON user_actions(user_id, action);
    """)
    conn.commit()
    conn.close()

def get_or_create_user(user_id: str, email: str = None, name: str = None, picture: str = None) -> Dict:
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        conn.execute(
            "INSERT INTO users (id, email, name, picture) VALUES (?, ?, ?, ?)",
            (user_id, email, name, picture)
        )
        conn.execute(
            "INSERT INTO preferences (user_id) VALUES (?)",
            (user_id,)
        )
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    else:
        conn.execute("UPDATE users SET last_login = datetime('now') WHERE id = ?", (user_id,))
        if email:
            conn.execute("UPDATE users SET email = ?, name = ?, picture = ? WHERE id = ?",
                         (email, name, picture, user_id))
        conn.commit()
    result = dict(user)
    conn.close()
    return result

def get_preferences(user_id: str) -> Dict[str, Any]:
    conn = get_db()
    prefs = conn.execute("SELECT * FROM preferences WHERE user_id = ?", (user_id,)).fetchone()
    if not prefs:
        conn.close()
        return _default_prefs()

    # Get action lists
    interested = [r["event_id"] for r in conn.execute(
        "SELECT event_id FROM user_actions WHERE user_id = ? AND action = 'interested'", (user_id,)
    ).fetchall()]

    calendar_added = [r["event_id"] for r in conn.execute(
        "SELECT event_id FROM user_actions WHERE user_id = ? AND action = 'calendar_added'", (user_id,)
    ).fetchall()]

    hidden = [r["event_id"] for r in conn.execute(
        "SELECT event_id FROM user_actions WHERE user_id = ? AND action = 'hidden'", (user_id,)
    ).fetchall()]

    disliked_topics = [r["value"] for r in conn.execute(
        "SELECT value FROM dislike_counts WHERE user_id = ? AND category = 'topics' AND count >= 3",
        (user_id,)
    ).fetchall()]

    disliked_sponsors = [r["value"] for r in conn.execute(
        "SELECT value FROM dislike_counts WHERE user_id = ? AND category = 'sponsors' AND count >= 3",
        (user_id,)
    ).fetchall()]

    not_interested = [{"title": r["title"], "group_name": r["group_name"], "expires_at": r["expires_at"]}
                      for r in conn.execute(
        "SELECT title, group_name, expires_at FROM user_actions WHERE user_id = ? AND action = 'not_interested'",
        (user_id,)
    ).fetchall()]

    conn.close()
    return {
        "topics": prefs["topics"] or "",
        "types": json.loads(prefs["types"]),
        "locations": json.loads(prefs["locations"]),
        "sponsors": json.loads(prefs["sponsors"]),
        "perks": json.loads(prefs["perks"]),
        "formats": json.loads(prefs["formats"]),
        "interested_events": interested,
        "added_to_calendar": calendar_added,
        "hidden_events": hidden,
        "disliked_topics": disliked_topics,
        "disliked_sponsors": disliked_sponsors,
        "not_interested": not_interested,
    }

def update_preferences(user_id: str, updates: Dict) -> Dict:
    conn = get_db()
    # Ensure user exists
    get_or_create_user(user_id)

    fields = []
    values = []
    for key in ["topics", "types", "locations", "sponsors", "perks", "formats"]:
        if key in updates:
            fields.append(f"{key} = ?")
            val = updates[key]
            values.append(json.dumps(val) if isinstance(val, list) else val)

    if fields:
        values.append(user_id)
        conn.execute(
            f"UPDATE preferences SET {', '.join(fields)}, updated_at = datetime('now') WHERE user_id = ?",
            values
        )
        conn.commit()
    conn.close()
    return get_preferences(user_id)

def add_action(user_id: str, event_id: int, action: str, title: str = "", group_name: str = "",
               topics: list = None, expires_at: str = None):
    conn = get_db()
    get_or_create_user(user_id)

    if action in ("interested", "calendar_added", "hidden"):
        existing = conn.execute(
            "SELECT id FROM user_actions WHERE user_id = ? AND event_id = ? AND action = ?",
            (user_id, event_id, action)
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO user_actions (user_id, event_id, action, title, group_name, topics, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, event_id, action, title, group_name, json.dumps(topics or []), expires_at)
            )
    elif action == "not_interested":
        conn.execute(
            "INSERT INTO user_actions (user_id, event_id, action, title, group_name, topics, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, event_id, action, title, group_name, json.dumps(topics or []), expires_at)
        )
    elif action == "disliked":
        # Add to hidden
        existing = conn.execute(
            "SELECT id FROM user_actions WHERE user_id = ? AND event_id = ? AND action = 'hidden'",
            (user_id, event_id)
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO user_actions (user_id, event_id, action, title, group_name, topics) VALUES (?, ?, 'hidden', ?, ?, ?)",
                (user_id, event_id, title, group_name, json.dumps(topics or []))
            )
        # Increment dislike counts
        if group_name:
            conn.execute("""
                INSERT INTO dislike_counts (user_id, category, value, count) VALUES (?, 'sponsors', ?, 1)
                ON CONFLICT(user_id, category, value) DO UPDATE SET count = count + 1
            """, (user_id, group_name))
        for t in (topics or []):
            conn.execute("""
                INSERT INTO dislike_counts (user_id, category, value, count) VALUES (?, 'topics', ?, 1)
                ON CONFLICT(user_id, category, value) DO UPDATE SET count = count + 1
            """, (user_id, t.lower()))

    conn.commit()
    conn.close()

def remove_action(user_id: str, event_id: int, action: str):
    conn = get_db()
    conn.execute(
        "DELETE FROM user_actions WHERE user_id = ? AND event_id = ? AND action = ?",
        (user_id, event_id, action)
    )
    conn.commit()
    conn.close()

def _default_prefs():
    return {
        "topics": "", "types": ["All"], "locations": ["All"], "sponsors": ["All"],
        "perks": ["All"], "formats": ["All"],
        "interested_events": [], "added_to_calendar": [], "hidden_events": [],
        "disliked_topics": [], "disliked_sponsors": [], "not_interested": [],
    }

# Initialize on import
init_db()
