# db.py
import sqlite3
from pathlib import Path
from datetime import datetime


DB_PATH = Path("instance") / "app.db"

ROLES = ("student", "lecturer", "staff")

def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db() -> None:
    conn = get_connection()
    cur = conn.cursor()






    # מי שמורשים להירשם (ת"ז + שם מלא + role)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS allowed_users (
        national_id TEXT PRIMARY KEY,
        full_name   TEXT NOT NULL,
        role        TEXT NOT NULL CHECK(role IN ('student','lecturer','staff'))
    );
    """)

    # משתמשים שנרשמו בפועל (ת"ז + role + password)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        national_id TEXT UNIQUE NOT NULL,
        role        TEXT NOT NULL CHECK(role IN ('student','lecturer','staff')),
        password    TEXT NOT NULL,
        created_at  TEXT DEFAULT (datetime('now'))
    );
    """)

    # rooms (חדש)
    cur.execute("""
       CREATE TABLE IF NOT EXISTS rooms (
           id        INTEGER PRIMARY KEY AUTOINCREMENT,
           code      TEXT UNIQUE NOT NULL,   -- למשל "203" / "ספריה 100"
           name      TEXT,                   -- אופציונלי
           is_active INTEGER NOT NULL DEFAULT 1
       );
       """)



    # --- MIGRATION: להוסיף שדות פרטים לחדרים (rooms) אם לא קיימים ---
    cur.execute("PRAGMA table_info(rooms)")
    rooms_cols = [row[1] for row in cur.fetchall()]

    if "room_type" not in rooms_cols:
        cur.execute("ALTER TABLE rooms ADD COLUMN room_type TEXT NOT NULL DEFAULT 'regular'")  # regular/computers/lab

    if "description" not in rooms_cols:
        cur.execute("ALTER TABLE rooms ADD COLUMN description TEXT NOT NULL DEFAULT ''")

    if "has_projector" not in rooms_cols:
        cur.execute("ALTER TABLE rooms ADD COLUMN has_projector INTEGER NOT NULL DEFAULT 1")   # 1/0

    if "seats" not in rooms_cols:
        cur.execute("ALTER TABLE rooms ADD COLUMN seats INTEGER")

    if "computer_stations" not in rooms_cols:
        cur.execute("ALTER TABLE rooms ADD COLUMN computer_stations INTEGER")


    # מערכת שבועית (לימודים קבועים בכיתה לפי יום בשבוע)
    # weekday: 0=Sunday ... 6=Saturday (כמו strftime('%w') ב-SQL)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS weekly_schedule (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        room_code TEXT NOT NULL,       -- זה חייב להתאים ל-rooms.code
        weekday INTEGER NOT NULL CHECK(weekday BETWEEN 0 AND 6),
        start_time TEXT NOT NULL,      -- 'HH:MM'
        end_time TEXT NOT NULL,        -- 'HH:MM'
        title TEXT                      -- אופציונלי: שם קורס/שיעור
    );
    """)

    # אינדקס לשיפור ביצועים
    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_weekly_schedule_room_weekday
    ON weekly_schedule (room_code, weekday);
    """)

    # דוחות תקלות (כולל מה שה-AI החזיר)
    # דוחות תקלות (כולל מה שה-AI החזיר)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reporter_national_id TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('student','lecturer')),
        room TEXT NOT NULL,
        category_user TEXT NOT NULL,
        description TEXT NOT NULL,
        ai_category TEXT,
        severity TEXT CHECK(severity IN ('low','medium','high')),
        status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','in_progress','done')),
        created_at TEXT DEFAULT (datetime('now'))
    );
    """)
    # --- MIGRATION: אם טבלת reports כבר קיימת מגרסה ישנה בלי room, נוסיף את העמודה ---
    cur.execute("PRAGMA table_info(reports)")
    reports_cols = [row[1] for row in cur.fetchall()]  # row[1] = column name

    if "room" not in reports_cols:
        cur.execute("ALTER TABLE reports ADD COLUMN room TEXT NOT NULL DEFAULT ''")

    # --- MIGRATION: שדות דירוג/AI ---
    cur.execute("PRAGMA table_info(reports)")
    reports_cols = [row[1] for row in cur.fetchall()]

    if "severity_rank" not in reports_cols:
        cur.execute("ALTER TABLE reports ADD COLUMN severity_rank INTEGER")

    if "ai_confidence" not in reports_cols:
        cur.execute("ALTER TABLE reports ADD COLUMN ai_confidence REAL")

    if "ai_rationale" not in reports_cols:
        cur.execute("ALTER TABLE reports ADD COLUMN ai_rationale TEXT")

    # הזמנות כיתות (מי הזמין, איזה כיתה, ומתי)
    # שימי לב: FK זה לא "אבטחה" — זה עקביות נתונים. אבל כדי לא להסתבך, נשאיר בלי FK.
    cur.execute("""
    CREATE TABLE IF NOT EXISTS reservations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_national_id TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('student','lecturer')),
        room TEXT NOT NULL,
        date TEXT NOT NULL,           -- 'YYYY-MM-DD'
        start_time TEXT NOT NULL,     -- 'HH:MM'
        end_time TEXT NOT NULL,       -- 'HH:MM'
        status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','cancelled')),
        created_at TEXT DEFAULT (datetime('now'))
    );
    """)

    conn.commit()
    conn.close()

# -------------------------
# Rooms helpers
# -------------------------
def seed_rooms_if_empty() -> None:
    """
    ממלא טבלת rooms פעם אחת אם היא ריקה.
    הקודים חייבים להתאים ל-weekly_schedule.
    """

    # ✅ שמות הכיתות הרשמיים במערכת
    default_rooms = [
        ("לגסי 101", "לגסי 101"),
        ("ספרא 102", "ספרא 102"),
        ("שמעון 201", "שמעון 201"),
        ("איינשטיין 203", "איינשטיין 203"),
        ("קציר 305", "קציר 305"),
        ("ספריה 100", "ספריה"),
        ("מעבדת מחשבים", "מעבדת מחשבים"),
    ]

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) AS cnt FROM rooms")
    cnt = cur.fetchone()["cnt"]

    if cnt == 0:
        for code, name in default_rooms:
            cur.execute(
                "INSERT OR IGNORE INTO rooms (code, name) VALUES (?, ?)",
                (code, name)
            )
        conn.commit()

    conn.close()


def room_exists(room_text: str) -> bool:
    """
    מחזיר True אם הכיתה קיימת ופעילה בטבלת rooms.
    מאפשר התאמה לפי code או לפי name (כדי לתמוך במה שהמשתמש מקליד).
    """
    if room_text is None:
        return False

    # ניקוי בסיסי: רווחים בתחילה/סוף + איחוד רווחים כפולים
    room_norm = " ".join(room_text.strip().split())
    if not room_norm:
        return False

    conn = get_connection()
    row = conn.execute("""
        SELECT 1
        FROM rooms
        WHERE is_active = 1
          AND (code = ? OR name = ?)
        LIMIT 1
    """, (room_norm, room_norm)).fetchone()
    conn.close()

    return row is not None




def get_all_reports():
    """
    מחזיר דיווחים מאוחדים:
    אם יש כמה דיווחים באותה כיתה + אותה קטגוריה בתוך שעה -> יוצג אחד,
    עם שדה report_count שמספר כמה דיווחים אוחדו.
    """
    conn = get_connection()

    rows = conn.execute("""
        WITH grouped AS (
          SELECT
            room,
            category_user,
            -- חלון שעה: נחתוך את created_at לשעה (YYYY-MM-DD HH)
           strftime('%Y-%m-%d %H', datetime(created_at, '+2 hours')) AS hour_bucket,


            MIN(id) AS min_id,
            MAX(id) AS last_id,
            COUNT(*) AS report_count,

            MIN(COALESCE(severity_rank, 999)) AS min_severity_rank,
            MAX(created_at) AS last_created_at
          FROM reports
          WHERE status != 'done'
          GROUP BY room, category_user, hour_bucket
        )
        SELECT
          r.id,
          r.reporter_national_id,
          r.role,
          r.room,
          r.category_user,
          r.description,
          r.ai_category,
          r.severity,
          r.severity_rank,
          r.ai_confidence,
          r.ai_rationale,
          r.status,
          r.created_at,
          g.report_count
        FROM grouped g
        JOIN reports r ON r.id = g.last_id
        ORDER BY
          COALESCE(r.severity_rank, g.min_severity_rank, 999) ASC,
          datetime(g.last_created_at) DESC,
          r.id DESC
    """).fetchall()

    conn.close()
    return rows


# -------------------------
# Helpers for AUTH (MVP)
# -------------------------

def is_allowed_user(national_id: str, role: str) -> bool:
    if role not in ROLES:
        return False
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM allowed_users WHERE national_id=? AND role=?",
        (national_id, role),
    )
    ok = cur.fetchone() is not None
    conn.close()
    return ok

def user_exists(national_id: str) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM users WHERE national_id=?", (national_id,))
    exists = cur.fetchone() is not None
    conn.close()
    return exists

def create_user(national_id: str, role: str, password: str) -> None:
    """
    MVP: password נשמר טקסט. בעתיד: לשמור hash.
    """
    if role not in ROLES:
        raise ValueError("Invalid role")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (national_id, role, password) VALUES (?, ?, ?)",
        (national_id, role, password),
    )
    conn.commit()
    conn.close()

def authenticate(national_id: str, role: str, password: str) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM users WHERE national_id=? AND role=? AND password=?",
        (national_id, role, password),
    )
    ok = cur.fetchone() is not None
    conn.close()
    return ok

def get_full_name(national_id: str, role: str) -> str | None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT full_name FROM allowed_users WHERE national_id=? AND role=?",
        (national_id, role),
    )
    row = cur.fetchone()
    conn.close()
    return row["full_name"] if row else None

#<!!!-----reports-----------------------------


def create_report(
    reporter_national_id: str,
    role: str,
    room: str,
    category_user: str,
    description: str,
    severity_rank: int | None = None,
    ai_confidence: float | None = None,
    ai_rationale: str | None = None
) -> None:
    if role not in ("student", "lecturer"):
        raise ValueError("Invalid reporter role")

    conn = get_connection()
    conn.execute("""
        INSERT INTO reports (
            reporter_national_id, role, room, category_user, description,
            ai_category, severity, status,
            severity_rank, ai_confidence, ai_rationale
        )
        VALUES (?, ?, ?, ?, ?, NULL, NULL, 'open', ?, ?, ?)
    """, (reporter_national_id, role, room, category_user, description,
          severity_rank, ai_confidence, ai_rationale))
    conn.commit()
    conn.close()


def get_reports_by_reporter(reporter_national_id: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, reporter_national_id, role, room, category_user, description,
               ai_category, severity, status, created_at
        FROM reports
        WHERE reporter_national_id = ?
        ORDER BY id DESC
    """, (reporter_national_id,))
    rows = cur.fetchall()
    conn.close()
    return rows



def update_report_status(report_id: int, new_status: str) -> None:
    if new_status not in ("open", "in_progress", "done"):
        raise ValueError("Invalid status")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        UPDATE reports
        SET status = ?
        WHERE id = ?
    """, (new_status, report_id))
    conn.commit()
    conn.close()


def mark_report_group_done_by_id(report_id: int) -> int:
    """
    מסמן כ-done את כל הדיווחים באותה קבוצה של report_id:
    room + category_user + אותה שעה (YYYY-MM-DD HH)
    מחזיר כמה שורות עודכנו.
    """
    conn = get_connection()
    cur = conn.cursor()

    # מפתח הקבוצה של הדיווח שעליו לחצו
    row = cur.execute("""
        SELECT
            room,
            category_user,
            strftime('%Y-%m-%d %H', datetime(created_at, '+2 hours')) AS hour_bucket

        FROM reports
        WHERE id = ?
    """, (report_id,)).fetchone()

    if row is None:
        conn.close()
        return 0

    room = row["room"]
    category_user = row["category_user"]
    hour_bucket = row["hour_bucket"]

    # סוגרים את כל הדיווחים בקבוצה
    cur.execute("""
        UPDATE reports
        SET status = 'done'
        WHERE status != 'done'
          AND room = ?
          AND category_user = ?
          AND strftime('%Y-%m-%d %H', datetime(created_at, '+2 hours')) = ?

    """, (room, category_user, hour_bucket))

    conn.commit()
    n = cur.rowcount
    conn.close()
    return n



def get_report_by_id(report_id: int):
    conn = get_connection()
    row = conn.execute("""
        SELECT id, reporter_national_id, role, room, category_user, description,
               ai_category, severity, status, created_at
        FROM reports
        WHERE id = ?
    """, (report_id,)).fetchone()
    conn.close()
    return row




########תהילה########
########תהילה########

def get_available_rooms(date: str, start_time: str, end_time: str):
    """
    מחזיר rooms (מטבלת rooms) שלא תפוסים בטווח הזמן.
    """
    conn = get_connection()

    # כל החדרים הפעילים
    all_rooms = conn.execute("""
        SELECT code
        FROM rooms
        WHERE is_active = 1
        ORDER BY code
    """).fetchall()
    all_codes = [r["code"] for r in all_rooms]

    # חדרים תפוסים בטווח
    taken_rows = conn.execute("""
        SELECT DISTINCT room
        FROM reservations
        WHERE date = ?
          AND status != 'cancelled'
          AND (? < end_time AND ? > start_time)
    """, (date, start_time, end_time)).fetchall()
    taken = {r["room"] for r in taken_rows}

    conn.close()

    # זמינים = הכל - תפוסים
    return [code for code in all_codes if code not in taken]

def create_reservation(user_id, role, room, date, start_time, end_time):
    """מוסיף הזמנה חדשה לטבלה"""

    # ✅ בדיקה פשוטה כדי למנוע הזמנה עם role לא חוקי
    if role not in ("student", "lecturer"):
        print(f"שגיאה: role לא חוקי להזמנה: {role}")
        return False

    conn = get_connection()
    try:
        query = """
            INSERT INTO reservations (user_national_id, role, room, date, start_time, end_time, status)
            VALUES (?, ?, ?, ?, ?, ?, 'active')
        """
        conn.execute(query, (user_id, role, room, date, start_time, end_time))
        conn.commit()
        return True
    except Exception as e:
        print(f"שגיאה בשמירת הזמנה: {e}")
        return False
    finally:
        conn.close()


def get_user_reservations(user_id):
    """שולף את כל ההזמנות של המרצה/סטודנט המחובר"""
    conn = get_connection()
    query = "SELECT * FROM reservations WHERE user_national_id = ? ORDER BY date DESC"
    rows = conn.execute(query, (user_id,)).fetchall()
    conn.close()
    return rows


def cancel_reservation(res_id, user_id):
    """מעדכן סטטוס של הזמנה ל'מבוטל'"""
    conn = get_connection()
    try:
        # אנחנו מוודאים שה-user_id תואם כדי שרק בעל ההזמנה יוכל לבטל אותה
        query = "UPDATE reservations SET status = 'cancelled' WHERE id = ? AND user_national_id = ?"
        conn.execute(query, (res_id, user_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"שגיאה בביטול: {e}")
        return False
    finally:
        conn.close()






######תהיךה

def get_detailed_available_rooms(date_str: str, start_t: str, end_t: str):
    """
    מחזיר רשימת חדרים פנויים לפי:
    1) מערכת שבועית weekly_schedule (לימודים קבועים)
    2) שריונים בפועל reservations

    מחזיר גם פרטי כיתה:
    room_type, description, has_projector, seats, computer_stations
    """

    # ✅ weekday בצורה בטוחה: Sunday=0 ... Saturday=6
    # Python weekday(): Monday=0 ... Sunday=6
    py_wd = datetime.strptime(date_str, "%Y-%m-%d").weekday()  # Mon=0..Sun=6
    weekday = (py_wd + 1) % 7                                 # Sun=0..Sat=6

    conn = get_connection()

    rows = conn.execute("""
        SELECT
            r.code,
            r.name,
            r.room_type,
            r.description,
            r.has_projector,
            r.seats,
            r.computer_stations
        FROM rooms r
        WHERE r.is_active = 1

          -- לא תפוס בגלל מערכת שבועית (לימודים)
          AND r.code NOT IN (
              SELECT ws.room_code
              FROM weekly_schedule ws
              WHERE ws.weekday = ?
                AND (? < ws.end_time AND ? > ws.start_time)
          )

          -- לא תפוס בגלל שריון קיים
          AND r.code NOT IN (
              SELECT DISTINCT room
              FROM reservations
              WHERE date = ?
                AND status != 'cancelled'
                AND (? < end_time AND ? > start_time)
          )

        ORDER BY r.code
    """, (weekday, start_t, end_t,
          date_str, start_t, end_t)).fetchall()

    conn.close()
    return rows


######תהילה######

def get_room_free_blocks(date_str: str, req_start: str, req_end: str):
    """
    מחזיר חלונות פנויים *מקסימליים* לכל כיתה בתוך הטווח שביקש המרצה.
    הפנוי מחושב לפי:
    - weekly_schedule (לימודים)
    - reservations (שריונים פעילים)

    מחזיר גם פרטי כיתה:
    room_type, description, has_projector, seats, computer_stations
    """

    def to_min(t: str) -> int:
        h, m = t.split(":")
        return int(h) * 60 + int(m)

    def to_hhmm(x: int) -> str:
        h = x // 60
        m = x % 60
        return f"{h:02d}:{m:02d}"

    # שעות פעילות מכללה
    OPEN_MIN = 8 * 60
    CLOSE_MIN = 20 * 60

    rs = max(to_min(req_start), OPEN_MIN)
    re = min(to_min(req_end), CLOSE_MIN)
    if re <= rs:
        return []

    conn = get_connection()

    # 1) כל הכיתות הפעילות + פרטים
    rooms = conn.execute("""
        SELECT
            code, name,
            room_type, description, has_projector, seats, computer_stations
        FROM rooms
        WHERE is_active = 1
        ORDER BY code
    """).fetchall()

    # 2) יום בשבוע לפי SQLite: 0=Sunday ... 6=Saturday
    weekday = conn.execute(
        "SELECT CAST(strftime('%w', ?) AS INTEGER) AS wd",
        (date_str,)
    ).fetchone()["wd"]

    result = []

    for room in rooms:
        code = room["code"]
        name = room["name"] or code

        # 3) להביא כל "הזמנים התפוסים" של הכיתה (מערכת שבועית + שריונים)
        busy_rows = conn.execute("""
            SELECT start_time, end_time FROM weekly_schedule
            WHERE room_code = ?
              AND weekday = ?
              AND (? < end_time AND ? > start_time)

            UNION ALL

            SELECT start_time, end_time FROM reservations
            WHERE room = ?
              AND date = ?
              AND status != 'cancelled'
              AND (? < end_time AND ? > start_time)
        """, (code, weekday, req_start, req_end,
              code, date_str, req_start, req_end)).fetchall()

        busy = []
        for b in busy_rows:
            bs = max(to_min(b["start_time"]), rs)
            be = min(to_min(b["end_time"]), re)
            if be > bs:
                busy.append((bs, be))

        # 4) מיזוג חפיפות
        busy.sort()
        merged = []
        for s, e in busy:
            if not merged or s > merged[-1][1]:
                merged.append([s, e])
            else:
                merged[-1][1] = max(merged[-1][1], e)

        # 5) היפוך -> פנוי מקסימלי בתוך [rs,re]
        free = []
        cur = rs
        for s, e in merged:
            if s > cur:
                free.append((cur, s))
            cur = max(cur, e)
        if cur < re:
            free.append((cur, re))

        # 6) להוסיף לרשימה: כל חלון פנוי מקסימלי + פרטים
        for fs, fe in free:
            if fe > fs:
                result.append({
                    "code": code,
                    "name": name,
                    "free_start": to_hhmm(fs),
                    "free_end": to_hhmm(fe),
                    "date": date_str,

                    "room_type": room["room_type"],
                    "description": room["description"],
                    "has_projector": room["has_projector"],
                    "seats": room["seats"],
                    "computer_stations": room["computer_stations"],
                })

    conn.close()
    return result


def is_room_available(date_str: str, room_code: str, start_t: str, end_t: str) -> bool:
    """
    מחזיר True אם הכיתה פנויה בטווח:
    - לא מתנגש עם weekly_schedule
    - לא מתנגש עם reservations פעילים
    - וגם בתוך שעות פתיחה 08:00-20:00
    """

    def to_min(t: str) -> int:
        h, m = t.split(":")
        return int(h) * 60 + int(m)

    OPEN_MIN = 8 * 60
    CLOSE_MIN = 20 * 60

    s = to_min(start_t)
    e = to_min(end_t)

    if e <= s:
        return False
    if s < OPEN_MIN or e > CLOSE_MIN:
        return False

    conn = get_connection()

    weekday = conn.execute(
        "SELECT CAST(strftime('%w', ?) AS INTEGER) AS wd",
        (date_str,)
    ).fetchone()["wd"]

    row = conn.execute("""
        SELECT 1
        WHERE EXISTS (
            SELECT 1 FROM weekly_schedule
            WHERE room_code = ?
              AND weekday = ?
              AND (? < end_time AND ? > start_time)
        )
        OR EXISTS (
            SELECT 1 FROM reservations
            WHERE room = ?
              AND date = ?
              AND status != 'cancelled'
              AND (? < end_time AND ? > start_time)
        )
    """, (room_code, weekday, start_t, end_t,
          room_code, date_str, start_t, end_t)).fetchone()

    conn.close()

    # אם מצאנו התנגשות => לא פנוי
    return row is None



