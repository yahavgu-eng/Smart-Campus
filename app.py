from flask import Flask, render_template, request, redirect, url_for, session, flash, abort
import db

from dotenv import load_dotenv

import os
from openai import OpenAI
import json
from datetime import date, datetime, timezone

from zoneinfo import ZoneInfo  # Python 3.9+

load_dotenv()
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# ------------------- AI TRIAGE -------------------


CATEGORY_TO_RANK = {
    "מקרן": 1,
    "מחשב": 2,
    "תאורה": 3,
    "מיזוג": 4,
    "אחר": 5
}

_JSON_SCHEMA = {
    "name": "fault_triage",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "severity_rank": {"type": "integer", "minimum": 1, "maximum": 5},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "rationale": {"type": "string", "maxLength": 220}
        },
        "required": ["severity_rank", "confidence", "rationale"]
    }
}

def ai_triage(category_user: str, room: str, description: str) -> dict:
    # fallback: לפי הבחירה מה-dropdown
    fallback_rank = CATEGORY_TO_RANK.get(category_user, 5)

    prompt = f"""
את סוכנת טריאז' לתקלות בכיתות.
סולם חומרה (1 הכי חמור, 5 הכי פחות חמור) לפי קטגוריה:
מקרן=1, מחשב=2, תאורה=3, מיזוג=4, אחר=5.

כללים:
- ברירת מחדל: דירוג לפי הקטגוריה שנבחרה.
- מותר לשנות לכל היותר בדרגה אחת (±1) אם התיאור מצביע על השפעה חריגה.
- לעולם לא לצאת מהטווח 1..5.

דיווח:
קטגוריה: {category_user}
כיתה: {room}
תיאור: {description}

החזירי JSON בלבד.
""".strip()

    try:
        resp = client.responses.create(
            model="gpt-4.1-mini",
            input=prompt,
            temperature=0,
            timeout=15,
            text={"format": {"type": "json_schema", "json_schema": _JSON_SCHEMA}},
        )

        data = json.loads(resp.output_text)

        rank = int(data.get("severity_rank", fallback_rank))
        if rank < 1 or rank > 5:
            rank = fallback_rank

        conf = float(data.get("confidence", 0.5))
        if conf < 0 or conf > 1:
            conf = 0.5

        rationale = str(data.get("rationale", "")).strip()
        if not rationale:
            rationale = "סווג לפי הקטגוריה שנבחרה."

        return {"severity_rank": rank, "confidence": conf, "rationale": rationale}

    except Exception as e:
        print("AI triage failed:", e)
        return {"severity_rank": fallback_rank, "confidence": 0.0, "rationale": "סווג אוטומטית לפי הקטגוריה (fallback)."}



app = Flask(__name__)
app.secret_key = "dev-secret-key"
db.init_db()
#db.seed_rooms_if_empty()

from db import (
    is_allowed_user,
    user_exists,
    create_user,
    authenticate,
    get_full_name,
)

IL_TZ = ZoneInfo("Asia/Jerusalem")

def _parse_sqlite_dt(s: str) -> datetime | None:
    """
    SQLite datetime('now') מחזיר 'YYYY-MM-DD HH:MM:SS' (UTC).
    נהפוך אותו ל-aware UTC ואז נמיר לישראל.
    """
    if not s:
        return None
    try:
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None

@app.template_filter("localdt")
def localdt_filter(value, fmt="%d-%m-%Y %H:%M"):
    """
    שימוש: {{ some_dt_string|localdt }}
    """
    # אם זה כבר datetime
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(IL_TZ).strftime(fmt)

    # אם זה string כמו מה-DB
    dt = _parse_sqlite_dt(str(value))
    if not dt:
        return value  # fallback: תציגי כמו שזה
    return dt.astimezone(IL_TZ).strftime(fmt)







# =========================================================
# ENTRY / LANDING (מסך בחירת תפקיד)  ✅ חדש
# =========================================================
@app.get("/entry")
def entry():
    # אם כבר מחוברת -> ישר לבית לפי role
    role = session.get("role")
    if role == "student":
        return redirect(url_for("home_student"))
    if role == "lecturer":
        return redirect(url_for("home_lecturer"))
    if role == "staff":
        return redirect(url_for("home_staff"))
    return render_template("entry.html")

# =========================================================
# HEALTHCHECK
# =========================================================
@app.get("/")
def healthcheck():
    # אם מחוברת - נשלח לבית לפי role (של B)
    role = session.get("role")
    if role == "student":
        return redirect(url_for("home_student"))
    if role == "lecturer":
        return redirect(url_for("home_lecturer"))
    if role == "staff":
        return redirect(url_for("home_staff"))

    # אם לא מחוברת -> אפשר או OK או להפנות ל-entry
    # אם את רוצה שהבית יהיה דף הכניסה - תשני לשורה הזו:
    return redirect(url_for("entry"))
    # אם את חייבת להשאיר healthcheck כ-OK:
    return "OK"

#Yahav Gueta
# =========================================================
# TEAM A: AUTH
# Routes: /login /register /logout
# =========================================================
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        role_prefill = request.args.get("role")
        return render_template("register.html", role_prefill=role_prefill)

    national_id = request.form.get("national_id", "").strip()
    role = request.form.get("role", "").strip()
    password = request.form.get("password", "").strip()

    if not national_id or not role or not password:
        return render_template("register.html", error="חסרים פרטים", role_prefill=role)

    if not is_allowed_user(national_id, role):
        return render_template("register.html", error="הת״ז/תפקיד לא מורשים להירשם", role_prefill=role)

    if user_exists(national_id):
        return render_template("register.html", error="המשתמש כבר קיים. לך להתחבר.", role_prefill=role)

    create_user(national_id, role, password)

    session["national_id"] = national_id
    session["role"] = role
    session["full_name"] = get_full_name(national_id, role) or ""

    return redirect(url_for("healthcheck"))


@app.route("/login", methods=["GET", "POST"])
def login():
    # prefill role מה-URL (למשל /login?role=student)
    if request.method == "GET":
        role_prefill = request.args.get("role")
        return render_template("login.html",  role_prefill=role_prefill)



    # POST
    national_id = request.form.get("national_id", "").strip()
    role = request.form.get("role", "").strip()
    password = request.form.get("password", "").strip()

    if not national_id or not role or not password:
        return render_template("login.html", error="חסרים פרטים", role_prefill=role)

    if not authenticate(national_id, role, password):
        return render_template("login.html", error="פרטים שגויים", role_prefill=role)

    session["national_id"] = national_id
    session["role"] = role
    session["full_name"] = get_full_name(national_id, role) or ""

    return redirect(url_for("healthcheck"))


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("entry"))



# Helpers (guards)
# -------------------------

def require_login():
    return "national_id" in session and "role" in session

def require_roles(*roles):
    return require_login() and session.get("role") in roles



#Ofir Ovadia
# -------------------------

# Home pages (UI + Navigation)
# -------------------------

@app.route("/home/student")
def home_student():
    if not require_roles("student"):
        return redirect(url_for("entry"))

    user_id = session.get("national_id")

    my_taken = db.get_user_reservations(user_id)          # שריונים
    my_reports = db.get_reports_by_reporter(user_id)      # דיווחים

    return render_template(
        "home_student.html",
        user_name=session.get("full_name", ""),
        role="סטודנט",
        taken=my_taken,
        reports=my_reports
    )



@app.route("/home/lecturer")
def home_lecturer():
    if not require_roles("lecturer"):
        return redirect(url_for("entry"))

    user_id = session.get("national_id")

    my_taken = db.get_user_reservations(user_id)
    my_reports = db.get_reports_by_reporter(user_id)

    return render_template(
        "home_lecturer.html",
        user_name=session.get("full_name", ""),
        role="מרצה",
        taken=my_taken,
        reports=my_reports
    )


#@app.route("/home/staff")
#def home_staff():
   # if not require_roles("staff"):
        #return redirect(url_for("entry"))
   # return render_template(
        #"home_staff.html",
        #user_name=session.get("full_name", ""),
        #role="צוות תחזוקה"
   # )
@app.route("/home/staff")
def home_staff():
    if not require_roles("staff"):
        return redirect(url_for("entry"))

    reports = db.get_all_reports()  # מביא את כל הדיווחים

    return render_template(
        "home_staff.html",
        user_name=session.get("full_name", ""),
        role="צוות תחזוקה",
        reports=reports
    )



###############תהילה
@app.route("/reservations/lecturer", methods=["GET", "POST"])
def lecturer_reservations():
    if not require_roles("lecturer"):
        return redirect(url_for("entry"))

    searched = False
    error_msg = None

    if request.method == "POST":
        searched = True
        date_selected = request.form.get("date")
        start_time = request.form.get("start_time")
        end_time = request.form.get("end_time")

        if not date_selected or not start_time or not end_time:
            error_msg = "נא למלא תאריך ושעות."
            return render_template("lecturer_reservations.html", searched=searched, error_msg=error_msg)

        if end_time <= start_time:
            error_msg = "טווח שעות לא תקין: שעת סיום חייבת להיות אחרי שעת התחלה."
            return render_template("lecturer_reservations.html", searched=searched, error_msg=error_msg)

        try:
            from db import get_room_free_blocks
            free_blocks = get_room_free_blocks(date_selected, start_time, end_time)

            return render_template(
                "search_results.html",
                free_blocks=free_blocks,
                today_date=date_selected  # רק לתצוגה (שם משתנה כבר קיים אצלך)
            )

        except Exception as e:
            print("DB Error:", e)
            error_msg = "אירעה שגיאה בבסיס הנתונים."
            return render_template("lecturer_reservations.html", searched=searched, error_msg=error_msg)

    return render_template("lecturer_reservations.html", searched=searched, error_msg=error_msg)



@app.route("/reservations/book", methods=["POST"])
def book_room():
    if "national_id" not in session:
        return redirect(url_for("entry"))

    # שליפת הנתונים מהטופס (Hidden inputs)
    room = request.form.get("room")
    date_selected = request.form.get("date")
    start_time = request.form.get("start_time")
    end_time = request.form.get("end_time")

    user_id = session.get("national_id")
    role = session.get("role")  # role של המשתמש המחובר

    # ✅ חסימה בשרת: סטודנט יכול לשריין רק פעם אחת להיום
    if role == "student":
        conn = db.get_connection()
        row = conn.execute("""
            SELECT 1
            FROM reservations
            WHERE user_national_id = ?
              AND role = 'student'
              AND date = ?
              AND status = 'active'
            LIMIT 1
        """, (user_id, date_selected)).fetchone()
        conn.close()

        if row:
            flash("כבר יש לך שריון פעיל להיום. בטל אותו לפני יצירת שריון חדש.")
            return redirect(url_for("entry"))

    # ✅ בדיקה בסיסית לטווח שעות
    if not room or not date_selected or not start_time or not end_time:
        return "חסרים פרטים להזמנה", 400

    if end_time <= start_time:
        return "טווח שעות לא תקין", 400

    from db import create_reservation
    success = create_reservation(user_id, role, room, date_selected, start_time, end_time)

    if success:
        flash("השריון בוצע בהצלחה ✅ אנא בטל אותו במידה והנך לא מתכוון להגיע.")
        return redirect(url_for("entry"))

    return "שגיאה בביצוע ההזמנה", 400



######תהיהל######





####

@app.route("/reservations/student", methods=["GET", "POST"])
def student_reservations():
    if "national_id" not in session:
        return redirect(url_for("entry"))

    searched = False

    # YYYY-MM-DD (ל-DB)
    today_date = date.today().strftime('%Y-%m-%d')
    # DD-MM-YYYY (לתצוגה)
    today_date_display = date.today().strftime('%d-%m-%Y')

    if request.method == "POST":
        searched = True
        start_time = request.form.get("start_time")
        end_time = request.form.get("end_time")

        if not start_time or not end_time:
            flash("נא לבחור שעת התחלה ושעת סיום.")
            return render_template(
                "student_reservations.html",
                today_date=today_date,
                today_date_display=today_date_display,
                searched=searched
            )

        if end_time <= start_time:
            flash("טווח שעות לא תקין: שעת סיום חייבת להיות אחרי שעת התחלה.")
            return render_template(
                "student_reservations.html",
                today_date=today_date,
                today_date_display=today_date_display,
                searched=searched
            )

        from db import get_detailed_available_rooms

        try:
            def to_minutes(t: str) -> int:
                h, m = t.split(":")
                return int(h) * 60 + int(m)

            def to_hhmm(total_min: int) -> str:
                h = total_min // 60
                m = total_min % 60
                return f"{h:02d}:{m:02d}"

            start_min = to_minutes(start_time)
            end_min = to_minutes(end_time)

            # ✅ שעות פתיחה/סגירה
            OPEN_MIN = 8 * 60     # 08:00
            CLOSE_MIN = 20 * 60   # 20:00

            # אם המשתמש בחר התחלה לפני 08:00 – נרים ל-08:00
            if start_min < OPEN_MIN:
                start_min = OPEN_MIN

            # אם המשתמש בחר סוף אחרי 20:00 – נחתוך ל-20:00
            if end_min > CLOSE_MIN:
                end_min = CLOSE_MIN

            # אם אחרי החיתוך אין בכלל טווח
            if end_min <= start_min:
                flash("אפשר לשריין רק בין 08:00 ל-20:00. אנא בחר טווח שעות תקין.")
                return render_template(
                    "student_reservations.html",
                    today_date=today_date,
                    today_date_display=today_date_display,
                    searched=searched
                )

            # בניית סלוטים של שעתיים בתוך הטווח
            slots = []
            cur = start_min

            while cur + 120 <= end_min:
                slot_start = to_hhmm(cur)
                slot_end = to_hhmm(cur + 120)

                rooms_for_slot = get_detailed_available_rooms(today_date, slot_start, slot_end)

                if rooms_for_slot and len(rooms_for_slot) > 0:
                    slots.append({
                        "start": slot_start,
                        "end": slot_end,
                        "rooms": rooms_for_slot
                    })

                cur += 120

            return render_template(
                "search_results.html",
                slots=slots,
                today_date=today_date,
                today_date_display=today_date_display  # ✅ זה השינוי החשוב
            )

        except Exception as e:
            print(f"SQL Error: {e}")
            return f"יש בעיה בבסיס הנתונים: {e}", 500

    return render_template(
        "student_reservations.html",
        today_date=today_date,
        today_date_display=today_date_display,
        searched=searched
    )



@app.route("/reservations/cancel/<int:res_id>", methods=["POST"])
def cancel_reservation_route(res_id):
    if "national_id" not in session:
        return redirect(url_for("entry"))

    user_id = session.get("national_id")

    ok = db.cancel_reservation(res_id, user_id)
    if ok:
        flash("השריון בוטל")
    else:
        flash("ביטול נכשל")

    # חוזר למסך הראשי של המשתמש (entry כבר יודע להפנות לפי role)
    return redirect(url_for("entry"))









# -------------------------
# Reports (student/lecturer)
# -------------------------

@app.route("/reports/new", methods=["GET", "POST"])
def reports_new():

    if request.method == "POST":
        room = request.form.get("room", "").strip()
        category_user = request.form.get("category_user", "").strip()
        description = request.form.get("description", "").strip()

        if not room or not category_user or not description:
            flash("נא למלא כיתה, קטגוריה ותיאור")
            return render_template("report_new.html")

        # ✅ בדיקה חדשה: הכיתה חייבת להיות קיימת במערכת (rooms)
        # מאחדים רווחים כפולים כדי לתפוס הקלדה כמו "ספרא   102"
        room_norm = " ".join(room.split())
        if not db.room_exists(room_norm):
            flash("הכיתה שהוזנה לא קיימת במערכת. נא לתקן את שם הכיתה.")
            return render_template("report_new.html")

        reporter_national_id = session.get("national_id", "TEMP_USER")
        role = session.get("role", "student")

        # fallback: דירוג לפי הבחירה מה-dropdown
        severity_rank = CATEGORY_TO_RANK.get(category_user, 5)
        ai_confidence = 0.0
        ai_rationale = "סווג לפי הקטגוריה שנבחרה (fallback)."

        try:
            triage = ai_triage(category_user, room_norm, description)
            severity_rank = triage["severity_rank"]
            ai_confidence = triage["confidence"]
            ai_rationale = triage["rationale"]
        except Exception as e:
            print("AI triage failed (route):", e)

        db.create_report(
            reporter_national_id=reporter_national_id,
            role=role,
            room=room_norm,
            category_user=category_user,
            description=description,
            severity_rank=severity_rank,
            ai_confidence=ai_confidence,
            ai_rationale=ai_rationale
        )

        flash("הדיווח נשלח בהצלחה ✅")
        return redirect(url_for("entry"))

    return render_template("report_new.html")


#  >!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!_________________________________<

# -------------------------
# Maintenance portal (staff)
# -------------------------
@app.route("/maintenance/reports")
def maintenance_reports():
    if not require_roles("staff"):
        return redirect(url_for("entry"))

    reports = db.get_all_reports()
    return render_template("maintenance_reports.html", reports=reports)


@app.route("/maintenance/reports/<int:report_id>")
def maintenance_report_details(report_id):
    if not require_roles("staff"):
        return redirect(url_for("entry"))

    report = db.get_report_by_id(report_id)
    if report is None:
        abort(404)

    return render_template("maintenance_report_details.html", report=report)

'''
@app.route("/maintenance/reports/<int:report_id>/status", methods=["POST"])
def maintenance_report_update_status(report_id):
    if not require_roles("staff"):
        return redirect(url_for("entry"))

    new_status = request.form.get("status", "done").strip()
    try:
        db.update_report_status(report_id, new_status)
        flash("סומן כטופל ✅")
    except Exception as e:
        print("update status failed:", e)
        flash("עדכון סטטוס נכשל")

    # חוזרים לדאשבורד של הצוות
    return redirect(url_for("home_staff"))
'''

@app.route("/maintenance/reports/<int:report_id>/status", methods=["POST"])
def maintenance_report_update_status(report_id):
    if not require_roles("staff"):
        return redirect(url_for("entry"))

    new_status = request.form.get("status", "done").strip()

    try:
        if new_status == "done":
            updated = db.mark_report_group_done_by_id(report_id)
            flash(f"סומן כטופל ✅ (נסגרו {updated} דיווחים)")
        else:
            db.update_report_status(report_id, new_status)
            flash("סטטוס עודכן ✅")
    except Exception as e:
        print("update status failed:", e)
        flash("עדכון סטטוס נכשל")

    return redirect(url_for("home_staff"))



if __name__ == "__main__":
    app.run(debug=True)




