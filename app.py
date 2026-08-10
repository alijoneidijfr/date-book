import hmac
import os
import re
import secrets
import sqlite3
from datetime import date as gregorian_date, datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, session

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = Path(os.environ.get("DATABASE_PATH", BASE_DIR / "database.db"))

# SECRET_KEY را در محیط production حتماً در Environment تنظیم کنید.
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "").strip()
DEFAULT_PHONE = os.environ.get("DEFAULT_PHONE", "+989190118068").strip()

TIME_OPTIONS = [
    "08:30", "09:00", "09:30", "10:00", "10:30", "11:00",
    "14:30", "15:00", "15:30", "16:00", "16:30", "17:00",
    "17:30", "18:00",
]

# -----------------------------------------------------------------------------
# Jalali date helpers (no third-party dependency required)
# -----------------------------------------------------------------------------

def gregorian_to_jalali(gy, gm, gd):
    """Convert Gregorian date to Jalali date."""
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = (
        355666
        + (365 * gy)
        + ((gy2 + 3) // 4)
        - ((gy2 + 99) // 100)
        + ((gy2 + 399) // 400)
        + gd
        + g_d_m[gm - 1]
    )
    jy = -1595 + (33 * (days // 12053))
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + (days // 31)
        jd = 1 + (days % 31)
    else:
        jm = 7 + ((days - 186) // 30)
        jd = 1 + ((days - 186) % 30)
    return jy, jm, jd


def jalali_to_gregorian(jy, jm, jd):
    """Convert Jalali date to Gregorian date."""
    jy += 1595
    days = (
        -355668
        + (365 * jy)
        + ((jy // 33) * 8)
        + (((jy % 33) + 3) // 4)
        + jd
        + (31 * (jm - 1) if jm < 7 else (30 * (jm - 7) + 186))
    )
    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        gy += 100 * ((days - 1) // 36524)
        days = (days - 1) % 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    sal_a = [0, 31, 29 if (gy % 4 == 0 and (gy % 100 != 0 or gy % 400 == 0)) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 1
    while gm <= 12 and gd > sal_a[gm]:
        gd -= sal_a[gm]
        gm += 1
    return gy, gm, gd


# The conversion above intentionally avoids external packages. This validation
# function additionally makes sure the submitted Jalali date is a real date.
def parse_jalali(value):
    match = re.fullmatch(r"(13\d{2}|14\d{2})/(\d{1,2})/(\d{1,2})", value or "")
    if not match:
        return None
    jy, jm, jd = map(int, match.groups())
    if not 1 <= jm <= 12 or not 1 <= jd <= (31 if jm <= 6 else 30):
        return None
    try:
        gy, gm, gd = jalali_to_gregorian(jy, jm, jd)
        converted = gregorian_date(gy, gm, gd)
    except (ValueError, OverflowError):
        return None
    # Round-trip validation catches invalid dates such as 1405/12/30 on a non-leap year.
    if gregorian_to_jalali(converted.year, converted.month, converted.day) != (jy, jm, jd):
        return None
    return converted


MONTH_NAMES = [
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
]


def jalali_date_options(count=14):
    today = gregorian_date.today()
    options = []
    for offset in range(count):
        current = today + timedelta(days=offset)
        jy, jm, jd = gregorian_to_jalali(current.year, current.month, current.day)
        options.append({
            "value": f"{jy:04d}/{jm:02d}/{jd:02d}",
            "day": jd,
            "month": MONTH_NAMES[jm - 1],
        })
    return options


def normalize_digits(value):
    """Convert Persian/Arabic digits to ASCII digits."""
    table = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    return (value or "").translate(table)


def get_db_connection():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with get_db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS final_date (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                selected_date TEXT NOT NULL,
                selected_time TEXT NOT NULL,
                cafe_name TEXT DEFAULT '',
                cafe_area TEXT DEFAULT '',
                latitude TEXT DEFAULT '',
                longitude TEXT DEFAULT '',
                phone TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        columns = {row["name"] for row in conn.execute("PRAGMA table_info(final_date)").fetchall()}
        migrations = {
            "phone": "ALTER TABLE final_date ADD COLUMN phone TEXT DEFAULT ''",
            "cafe_name": "ALTER TABLE final_date ADD COLUMN cafe_name TEXT DEFAULT ''",
            "cafe_area": "ALTER TABLE final_date ADD COLUMN cafe_area TEXT DEFAULT ''",
            "latitude": "ALTER TABLE final_date ADD COLUMN latitude TEXT DEFAULT ''",
            "longitude": "ALTER TABLE final_date ADD COLUMN longitude TEXT DEFAULT ''",
        }
        for column, statement in migrations.items():
            if column not in columns:
                conn.execute(statement)
        conn.commit()


init_db()


def admin_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))
        return view_func(*args, **kwargs)
    return wrapper


@app.context_processor
def inject_config():
    return {"default_phone": DEFAULT_PHONE}


@app.get("/")
def index():
    return render_template("index.html")


@app.route("/arrange", methods=["GET", "POST"])
def arrange():
    dates = jalali_date_options(14)
    error = None

    if request.method == "POST":
        raw_date = normalize_digits(request.form.get("date", "")).strip()
        selected_time = normalize_digits(request.form.get("time", "")).strip()
        allowed_dates = {item["value"] for item in dates}

        if raw_date not in allowed_dates or selected_time not in TIME_OPTIONS:
            error = "لطفاً یک تاریخ و ساعت معتبر انتخاب کن."
            return render_template("arrange.html", error=error, dates=dates, time_options=TIME_OPTIONS)

        return render_template("cofe.html", date=raw_date, time=selected_time)

    return render_template("arrange.html", dates=dates, time_options=TIME_OPTIONS)


@app.post("/submit-final")
def submit_final():
    date_value = normalize_digits(request.form.get("date", "")).strip()
    time_value = normalize_digits(request.form.get("time", "")).strip()
    cafe_name = request.form.get("cafe_name", "").strip()
    cafe_area = request.form.get("cafe_area", "").strip()
    lat = normalize_digits(request.form.get("latitude", "")).strip()
    lng = normalize_digits(request.form.get("longitude", "")).strip()
    phone = request.form.get("phone", "").strip()

    available_dates = {item["value"] for item in jalali_date_options(14)}

    if date_value not in available_dates or time_value not in TIME_OPTIONS:
        return render_template("error.html", error="تاریخ یا ساعت انتخاب‌شده معتبر نیست. لطفاً دوباره انتخاب کن.")

    if not cafe_name or not cafe_area:
        return render_template("error.html", error="لطفاً نام کافه و محله را وارد کن.")

    if len(cafe_name) > 120 or len(cafe_area) > 120 or len(phone) > 40:
        return render_template("error.html", error="یکی از اطلاعات واردشده بیش از حد طولانی است.")

    # مختصات اختیاری‌اند؛ اگر وارد شده‌اند باید شکل عددی معتبر داشته باشند.
    if lat or lng:
        try:
            lat_float = float(lat)
            lng_float = float(lng)
            if not (-90 <= lat_float <= 90 and -180 <= lng_float <= 180):
                raise ValueError
            lat = f"{lat_float:.6f}"
            lng = f"{lng_float:.6f}"
        except ValueError:
            return render_template("error.html", error="لوکیشن انتخاب‌شده معتبر نیست.")

    with get_db_connection() as conn:
        conn.execute("""
            INSERT INTO final_date
            (selected_date, selected_time, cafe_name, cafe_area, latitude, longitude, phone)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (date_value, time_value, cafe_name, cafe_area, lat, lng, phone))
        conn.commit()

    return render_template(
        "thanks.html",
        date=date_value,
        time=time_value,
        cafe_name=cafe_name,
        cafe_area=cafe_area,
        latitude=lat,
        longitude=lng,
        phone=phone,
    )


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None

    if request.method == "POST":
        password = request.form.get("password", "")

        if not ADMIN_PASSWORD:
            error = "رمز مدیر روی سرور تنظیم نشده است. مقدار ADMIN_PASSWORD را در Environment تنظیم کن."
        elif hmac.compare_digest(password, ADMIN_PASSWORD):
            session.clear()
            session["admin_logged_in"] = True
            session.permanent = False
            return redirect(url_for("admin_panel"))
        else:
            error = "رمز عبور اشتباه است."

    return render_template("admin_login.html", error=error)


@app.get("/admin")
@admin_required
def admin_panel():
    with get_db_connection() as conn:
        bookings = conn.execute("""
            SELECT
                id,
                cafe_name AS name,
                selected_date AS booking_date,
                selected_time AS booking_time,
                phone,
                cafe_area,
                latitude,
                longitude,
                created_at
            FROM final_date
            ORDER BY id DESC
        """).fetchall()

    return render_template("admin.html", bookings=bookings)


@app.post("/admin/logout")
@admin_required
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


@app.post("/admin/delete/<int:booking_id>")
@admin_required
def delete_booking(booking_id):
    with get_db_connection() as conn:
        conn.execute("DELETE FROM final_date WHERE id = ?", (booking_id,))
        conn.commit()
    return redirect(url_for("admin_panel"))


# -----------------------------------------------------------------------------
# Legacy routes: kept so older templates/bookmarks do not produce BuildError.
# They do not alter the current main booking flow.
# -----------------------------------------------------------------------------
@app.route("/book", methods=["GET", "POST"])
def book():
    if request.method == "POST":
        return redirect(url_for("arrange"))
    return redirect(url_for("arrange"))


@app.get("/location")
def location():
    return render_template("location.html")


@app.get("/date-time")
def date_time():
    return redirect(url_for("arrange"))


@app.get("/health")
def health():
    return {"status": "ok"}


@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", error="صفحه موردنظر پیدا نشد."), 404


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG", "0") == "1")
