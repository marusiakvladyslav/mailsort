"""
database.py — модуль роботи з базою даних SQLite.
Зберігає листи та результати класифікації.
"""
import sqlite3
import os
from config import DB_PATH


def get_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Продуктивність: WAL + менш агресивний fsync.
    # У локальному застосунку ризик втрати останньої транзакції при раптовому
    # вимкненні живлення прийнятний, а швидкодія масових вставок зростає у десятки разів.
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-16000")  # 16 МБ кешу сторінок
    except Exception:
        pass
    return conn


def init_db() -> None:
    """Створює таблиці, якщо їх ще немає."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS emails (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                uid         TEXT UNIQUE,
                sender      TEXT,
                subject     TEXT,
                body        TEXT,
                date        TEXT,
                category    TEXT,
                confidence  REAL,
                is_read     INTEGER DEFAULT 0,
                is_starred  INTEGER DEFAULT 0,
                created_at  TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_category ON emails(category);

            CREATE INDEX IF NOT EXISTS idx_date     ON emails(date);
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT ''
            );
            INSERT OR IGNORE INTO settings (key, value) VALUES
                ('imap_host',   'imap.gmail.com'),
                ('imap_port',   '993'),
                ('email_user',  ''),
                ('imap_pass',   ''),
                ('fetch_limit', '0'),
                ('threshold',   '0.30'),
                ('auth_user',     'admin'),
                ('auth_pass',     'admin'),
                ('sync_interval', '300');

            CREATE TABLE IF NOT EXISTS spam_rules (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_type  TEXT NOT NULL,  -- 'domain' або 'keyword'
                value      TEXT NOT NULL UNIQUE,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS user_categories (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL UNIQUE,
                icon       TEXT DEFAULT '📂',
                is_default INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            );
            INSERT OR IGNORE INTO user_categories (name, icon, is_default) VALUES
                ('Новини та розсилки',    'rss',        1),
                ('Moodle',               'layers',     1),
                ('Навчальний процес',     'book-open',  1),
                ('Адміністрація',         'clipboard',  1),
                ('Заходи та події',       'calendar',   1);

            -- Корекції користувача (для активного навчання)
            CREATE TABLE IF NOT EXISTS user_corrections (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                email_id      INTEGER,           -- опціонально, може бути NULL після видалення листа
                subject       TEXT NOT NULL,
                body          TEXT NOT NULL,
                sender        TEXT DEFAULT '',
                old_category  TEXT,              -- що модель видала спочатку
                old_confidence REAL,
                new_category  TEXT NOT NULL,     -- що поставив користувач
                used_in_model INTEGER DEFAULT 0, -- чи вже увійшло у навчання
                created_at    TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_corr_used ON user_corrections(used_in_model);
            CREATE INDEX IF NOT EXISTS idx_corr_cat ON user_corrections(new_category);

            -- Історія версій ML-моделі (для сторінки /ml-quality)
            CREATE TABLE IF NOT EXISTS ml_model_versions (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                model_name    TEXT,              -- 'SVM + char+word' і т.п.
                n_samples     INTEGER,           -- розмір корпусу
                n_corrections INTEGER DEFAULT 0, -- скільки з них корекцій юзера
                f1_weighted   REAL,
                accuracy      REAL,
                trained_at    TEXT DEFAULT (datetime('now'))
            );
        """)


# ─── CRUD ────────────────────────────────────────────────────────

def save_email(uid: str, sender: str, subject: str,
               body: str, date: str,
               category: str, confidence: float) -> int:
    """Зберігає лист. Якщо вже існує — оновлює категорію."""
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO emails (uid, sender, subject, body, date, category, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(uid) DO UPDATE SET
                category   = excluded.category,
                confidence = excluded.confidence
        """, (uid, sender, subject, body, date, category, confidence))
        row = conn.execute("SELECT id FROM emails WHERE uid=?", (uid,)).fetchone()
        return row["id"]


def save_emails_bulk(rows: list[dict]) -> int:
    """
    Масова вставка (для email_fetcher). Одна транзакція на весь батч
    замість N окремих з'єднань — дає ~100× прискорення при 500+ листах.
    Очікує список dict з ключами: uid, sender, subject, body, date, category, confidence.
    Повертає кількість вставлених/оновлених рядків.
    """
    if not rows:
        return 0
    payload = [
        (r["uid"], r["sender"], r["subject"], r["body"], r["date"],
         r["category"], r["confidence"])
        for r in rows
    ]
    with get_connection() as conn:
        conn.executemany("""
            INSERT INTO emails (uid, sender, subject, body, date, category, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(uid) DO UPDATE SET
                category   = excluded.category,
                confidence = excluded.confidence
        """, payload)
    return len(rows)


def get_emails_by_category(category: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT * FROM emails WHERE category=?
            ORDER BY date DESC
        """, (category,)).fetchall()
    return [dict(r) for r in rows]


def get_email_by_id(email_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM emails WHERE id=?", (email_id,)).fetchone()
    return dict(row) if row else None


def mark_as_read(email_id: int) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE emails SET is_read=1 WHERE id=?", (email_id,))


def get_stats() -> dict:
    """Повертає кількість листів по категоріях та загальну кількість."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT category, COUNT(*) as cnt,
                   SUM(CASE WHEN is_read=0 THEN 1 ELSE 0 END) as unread
            FROM emails GROUP BY category
        """).fetchall()
        total = conn.execute("SELECT COUNT(*) as c FROM emails").fetchone()["c"]
    return {
        "total": total,
        "by_category": [dict(r) for r in rows],
    }


def reclassify_email(email_id: int, new_category: str) -> None:
    """Ручне виправлення категорії користувачем."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE emails SET category=?, confidence=1.0 WHERE id=?",
            (new_category, email_id),
        )


def search_emails(query: str, category: str | None = None) -> list[dict]:
    """Повнотекстовий пошук по темі, відправнику та тілу листа."""
    like = f"%{query}%"
    with get_connection() as conn:
        if category:
            rows = conn.execute("""
                SELECT * FROM emails
                WHERE category=? AND (subject LIKE ? OR sender LIKE ? OR body LIKE ?)
                ORDER BY date DESC LIMIT 200
            """, (category, like, like, like)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM emails
                WHERE subject LIKE ? OR sender LIKE ? OR body LIKE ?
                ORDER BY date DESC LIMIT 200
            """, (like, like, like)).fetchall()
    return [dict(r) for r in rows]


def get_all_emails_for_export(category: str | None = None) -> list[dict]:
    """Повертає листи для CSV-експорту."""
    with get_connection() as conn:
        if category:
            rows = conn.execute(
                "SELECT id,sender,subject,date,category,confidence,is_read FROM emails "
                "WHERE category=? ORDER BY date DESC", (category,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id,sender,subject,date,category,confidence,is_read FROM emails "
                "ORDER BY date DESC"
            ).fetchall()
    return [dict(r) for r in rows]


def get_setting(key: str, default: str = "") -> str:
    with get_connection() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """, (key, value))


# ── Spam rules ────────────────────────────────────────────────────

def get_spam_rules() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM spam_rules ORDER BY rule_type, value"
        ).fetchall()
    return [dict(r) for r in rows]

def add_spam_rule(rule_type: str, value: str) -> bool:
    """Додає правило. Повертає False якщо вже існує."""
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO spam_rules (rule_type, value) VALUES (?, ?)",
                (rule_type, value.lower().strip())
            )
        return True
    except Exception:
        return False

def delete_spam_rule(rule_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM spam_rules WHERE id=?", (rule_id,))


# ── User categories ───────────────────────────────────────────────

def get_all_categories() -> list[dict]:
    """Повертає всі категорії (вбудовані + користувацькі)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM user_categories ORDER BY is_default DESC, name"
        ).fetchall()
    return [dict(r) for r in rows]

def get_category_names() -> list[str]:
    return [r["name"] for r in get_all_categories()]

def add_category(name: str, icon: str = "📂") -> bool:
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO user_categories (name, icon, is_default) VALUES (?, ?, 0)",
                (name.strip(), icon)
            )
        return True
    except Exception:
        return False

def delete_category(name: str) -> tuple[bool, str]:
    """Видаляє тільки користувацькі категорії. is_default=1 — захищені."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT is_default FROM user_categories WHERE name=?", (name,)
        ).fetchone()
        if not row:
            return False, "Категорію не знайдено"
        if row["is_default"] == 1:
            return False, "Вбудовані категорії не можна видаляти"
        # Листи з цієї категорії → Невизначено
        conn.execute(
            "UPDATE emails SET category='Невизначено' WHERE category=?", (name,)
        )
        conn.execute("DELETE FROM user_categories WHERE name=?", (name,))
    return True, "OK"

def update_category_icon(name: str, icon: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE user_categories SET icon=? WHERE name=?", (icon, name)
        )


# ── Starred emails ────────────────────────────────────────────────

def toggle_starred(email_id: int) -> bool:
    """Перемикає зірочку. Повертає новий стан (True = зірочка є)."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT is_starred FROM emails WHERE id=?", (email_id,)
        ).fetchone()
        if not row:
            return False
        new_val = 0 if row["is_starred"] else 1
        conn.execute(
            "UPDATE emails SET is_starred=? WHERE id=?", (new_val, email_id)
        )
    return bool(new_val)


def get_starred_emails() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM emails WHERE is_starred=1 ORDER BY date DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_starred_count() -> int:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM emails WHERE is_starred=1"
        ).fetchone()
    return row["c"]




# ── Міграція категорій ────────────────────────────────────────────

OLD_TO_NEW_CATEGORIES = {
    "Актуальні новини":      "Новини та розсилки",
    "Наукова діяльність":    "Заходи та події",
    "Освітня діяльність":    "Навчальний процес",
    "Міжнародна діяльність": "Заходи та події",
    "Приймальна комісія":    "Адміністрація",
    "До обговорення":        "Адміністрація",
    "Вакансії":              "Адміністрація",
    "Фінанси та стипендії":  "Невизначено",
}

def migrate_categories() -> int:
    """
    Мігрує старі категорії до нових.
    Викликається один раз при старті app.py.
    Повертає кількість оновлених листів.
    """
    total = 0
    with get_connection() as conn:
        # Видаляємо старі вбудовані категорії
        old_names = list(OLD_TO_NEW_CATEGORIES.keys())
        for old in old_names:
            conn.execute(
                "DELETE FROM user_categories WHERE name=? AND is_default=1", (old,)
            )
        # Додаємо нові вбудовані категорії
        new_cats = [
            ("Новини та розсилки",   "rss",       1),
            ("Moodle",               "layers",    1),
            ("Навчальний процес",    "book-open", 1),
            ("Адміністрація",        "clipboard", 1),
            ("Заходи та події",      "calendar",  1),
        ]
        for name, icon, is_def in new_cats:
            conn.execute(
                "INSERT OR IGNORE INTO user_categories (name, icon, is_default) VALUES (?,?,?)",
                (name, icon, is_def)
            )
        # Переносимо листи
        for old, new in OLD_TO_NEW_CATEGORIES.items():
            result = conn.execute(
                "UPDATE emails SET category=? WHERE category=?", (new, old)
            )
            total += result.rowcount
    return total




def reclassify_by_sender_rules() -> int:
    """
    Перекласифікує вже збережені листи за правилами відправника.
    Використовує CATEGORY_SENDER_LIKE для широкого пошуку по полю sender.
    Повертає кількість оновлених листів.
    """
    try:
        from config import CATEGORY_SENDERS, CATEGORY_SENDER_LIKE
    except ImportError:
        return 0

    total = 0
    with get_connection() as conn:
        # 1. Точні патерни (рядок LIKE %pattern%)
        for pattern, category in CATEGORY_SENDERS.items():
            result = conn.execute(
                "UPDATE emails SET category=?, confidence=0.99 "
                "WHERE LOWER(sender) LIKE ? AND category != ?",
                (category, f"%{pattern.lower()}%", category)
            )
            if result.rowcount > 0:
                print(f"[reclassify] '{pattern}' → {category}: {result.rowcount} листів")
            total += result.rowcount

        # 2. Широкі LIKE-патерни з CATEGORY_SENDER_LIKE
        for category, patterns in CATEGORY_SENDER_LIKE.items():
            for like_pattern in patterns:
                result = conn.execute(
                    "UPDATE emails SET category=?, confidence=0.99 "
                    "WHERE LOWER(sender) LIKE ? AND category != ?",
                    (category, like_pattern.lower(), category)
                )
                if result.rowcount > 0:
                    print(f"[reclassify] LIKE '{like_pattern}' → {category}: {result.rowcount} листів")
                total += result.rowcount

    return total

def deduplicate_emails() -> int:
    """
    Видаляє дублікати листів — залишає тільки найновіший запис з кожним uid.
    Повертає кількість видалених рядків.
    """
    with get_connection() as conn:
        result = conn.execute("""
            DELETE FROM emails
            WHERE id NOT IN (
                SELECT MAX(id) FROM emails GROUP BY uid
            )
        """)
        return result.rowcount

# ── Видалення листів ──────────────────────────────────────────────

def delete_email(email_id: int) -> None:
    """Видаляє один лист з БД."""
    with get_connection() as conn:
        conn.execute("DELETE FROM emails WHERE id=?", (email_id,))


def delete_demo_emails() -> int:
    """Видаляє всі демо-листи (uid починається з 'demo_')."""
    with get_connection() as conn:
        cnt = conn.execute(
            "SELECT COUNT(*) FROM emails WHERE uid LIKE 'demo_%'"
        ).fetchone()[0]
        conn.execute("DELETE FROM emails WHERE uid LIKE 'demo_%'")
    return cnt


def delete_all_emails() -> int:
    """Видаляє всі листи з БД."""
    with get_connection() as conn:
        cnt = conn.execute("SELECT COUNT(*) FROM emails").fetchone()[0]
        conn.execute("DELETE FROM emails")
    return cnt


# ═══ Активне навчання: корекції користувача ════════════════════════

def add_user_correction(email_id, subject: str, body: str, sender: str,
                        old_category: str, old_confidence: float,
                        new_category: str) -> int:
    """
    Зберігає факт ручного перекласифікування як приклад для майбутнього
    перенавчання моделі. Якщо для цього листа корекція вже існує — оновлюється.
    """
    with get_connection() as conn:
        if email_id is not None:
            existing = conn.execute(
                "SELECT id FROM user_corrections WHERE email_id=?", (email_id,)
            ).fetchone()
            if existing:
                conn.execute("""
                    UPDATE user_corrections
                       SET new_category=?, old_category=?, old_confidence=?,
                           used_in_model=0, created_at=datetime('now')
                     WHERE id=?
                """, (new_category, old_category, old_confidence, existing["id"]))
                return existing["id"]
        cur = conn.execute("""
            INSERT INTO user_corrections
                (email_id, subject, body, sender,
                 old_category, old_confidence, new_category)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (email_id, subject, body, sender,
              old_category, old_confidence, new_category))
        return cur.lastrowid


def get_pending_corrections(limit: int = 10000) -> list[dict]:
    """Корекції, які ще не ввійшли до навченої моделі."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT * FROM user_corrections
             WHERE used_in_model=0
             ORDER BY created_at DESC
             LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_all_corrections() -> list[dict]:
    """Усі корекції (для передавання в train())."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM user_corrections ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def mark_corrections_as_used() -> int:
    """Після успішного train() позначаємо всі pending як використані."""
    with get_connection() as conn:
        cnt = conn.execute(
            "SELECT COUNT(*) FROM user_corrections WHERE used_in_model=0"
        ).fetchone()[0]
        conn.execute("UPDATE user_corrections SET used_in_model=1 WHERE used_in_model=0")
    return cnt


def get_corrections_stats() -> dict:
    """Зведення для сторінки /ml-quality."""
    with get_connection() as conn:
        total   = conn.execute("SELECT COUNT(*) FROM user_corrections").fetchone()[0]
        pending = conn.execute(
            "SELECT COUNT(*) FROM user_corrections WHERE used_in_model=0"
        ).fetchone()[0]
        by_cat = conn.execute("""
            SELECT new_category, COUNT(*) AS cnt
              FROM user_corrections
             GROUP BY new_category
             ORDER BY cnt DESC
        """).fetchall()
    return {
        "total":   total,
        "pending": pending,
        "by_category": [dict(r) for r in by_cat],
    }


# ═══ Історія версій ML-моделі ══════════════════════════════════════

def log_model_version(model_name: str, n_samples: int,
                      n_corrections: int, f1_weighted: float,
                      accuracy: float) -> int:
    with get_connection() as conn:
        cur = conn.execute("""
            INSERT INTO ml_model_versions
                (model_name, n_samples, n_corrections, f1_weighted, accuracy)
            VALUES (?, ?, ?, ?, ?)
        """, (model_name, n_samples, n_corrections, f1_weighted, accuracy))
        return cur.lastrowid


def get_model_versions(limit: int = 30) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT * FROM ml_model_versions
             ORDER BY trained_at DESC
             LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]
