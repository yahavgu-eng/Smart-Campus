# seed.py
from db import get_connection, init_db

ALLOWED = [
    ("123456789", "שילת כהן", "student"),
    ("111111111", "סטודנט דמו", "student"),
    ("987654321", "ד״ר לוי", "lecturer"),
    ("222222222", "מרצה דמו", "lecturer"),
    ("555555555", "אלי תחזוקה", "staff"),
    ("666666666", "תחזוקה דמו", "staff"),
]

USERS = [
    ("123456789", "student", "123"),
    #("111111111", "student", "123"),  דמו
    ("987654321", "lecturer", "123"),
    #("222222222", "lecturer", "123"),דמו
    ("555555555", "staff", "123"),
    #("666666666", "staff", "123"), דמו
]
# ✅ כיתות במערכת (חייב להתאים ל-rooms.code)
ROOMS = [
    # code, name, room_type, description, has_projector, seats, computer_stations
    ("לגסי 101", "לגסי 101", "regular", "50 כיסאות", 1, 50, None),
    ("ספרא 102", "ספרא 102", "regular", "45 כיסאות", 1, 45, None),
    ("שמעון 201", "שמעון 201", "lab", "מעבדה: עמדות ניסוי", 0, 30, None),
    ("איינשטיין 203", "איינשטיין 203", "regular", "60 כיסאות", 1, 60, None),
    ("קציר 305", "קציר 305", "computers", "כיתת מחשבים", 1, None, 28),
]

# =========================================================
# ✅ מערכת שבועית (לימודים קבועים)
# weekday: 0=Sunday ... 6=Saturday
# room_code חייב להתאים בדיוק ל-rooms.code
# =========================================================
WEEKLY_SCHEDULE = [
    ("לגסי 101", 0, "08:00", "10:00", "חדו״א"),
    ("לגסי 101", 0, "10:00", "12:00", "מבוא לתכנות"),

    ("ספרא 102", 1, "09:00", "11:00", "לוגיקה"),
    ("ספרא 102", 3, "12:00", "14:00", "מבני נתונים"),

    ("שמעון 201", 2, "08:00", "12:00", "מעבדה"),
    ("איינשטיין 203", 4, "10:00", "13:00", "תרגול"),

    ("קציר 305", 0, "14:00", "16:00", "פרויקט"),
    ("קציר 305", 2, "14:00", "16:00", "פרויקט"),
]


def seed_all() -> None:
    init_db()
    conn = get_connection()
    cur = conn.cursor()

    # 1️⃣ allowed_users
    cur.executemany("""
        INSERT OR IGNORE INTO allowed_users (national_id, full_name, role)
        VALUES (?, ?, ?);
    """, ALLOWED)

    # 2️⃣ users
    cur.executemany("""
        INSERT OR IGNORE INTO users (national_id, role, password)
        VALUES (?, ?, ?);
    """, USERS)

    cur.execute("DELETE FROM rooms")
    # 3️⃣ rooms (עם עדכון פרטים)
    for code, name, room_type, desc, has_proj, seats, comps in ROOMS:
        # אם לא קיים – ליצור בסיסי
        cur.execute("INSERT OR IGNORE INTO rooms (code, name) VALUES (?, ?)", (code, name))

        # תמיד לעדכן פרטים (גם אם כבר היה קיים)
        cur.execute("""
            UPDATE rooms
            SET room_type = ?, description = ?, has_projector = ?, seats = ?, computer_stations = ?
            WHERE code = ?
        """, (room_type, desc, int(has_proj), seats, comps, code))

    # 4️⃣ weekly_schedule
    cur.execute("DELETE FROM weekly_schedule")

    cur.executemany("""
        INSERT INTO weekly_schedule (room_code, weekday, start_time, end_time, title)
        VALUES (?, ?, ?, ?, ?);
    """, WEEKLY_SCHEDULE)

    conn.commit()
    conn.close()

if __name__ == "__main__":
    seed_all()
    print("Seed done ✅")
