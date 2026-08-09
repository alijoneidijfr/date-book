import os
import sqlite3
from datetime import date, datetime, timedelta
from flask import Flask, flash, g, redirect, render_template, request, url_for

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-demo-secret-key")
app.config["DATABASE"] = os.path.join(app.root_path, "bookings.db")

# ساعت‌های قابل رزرو در این نمونه
TIME_SLOTS = ["10:00", "12:00", "15:00", "17:00", "19:00", "21:00"]


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            selected_date TEXT NOT NULL,
            selected_time TEXT NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(selected_date, selected_time)
        )
    """)
    db.commit()


@app.before_request
def ensure_database():
    init_db()


def available_dates():
    # از فردا تا 14 روز آینده
    start = date.today() + timedelta(days=1)
    return [start + timedelta(days=i) for i in range(14)]


@app.route("/", methods=["GET", "POST"])
def home():
    dates = available_dates()
    selected_date = request.form.get("selected_date", dates[0].isoformat())
    selected_time = request.form.get("selected_time", "")

    if request.method == "POST":
        name = request.form.get("full_name", "").strip()
        phone = request.form.get("phone", "").strip()
        note = request.form.get("note", "").strip()
        allowed_dates = {d.isoformat() for d in dates}

        if not name or not phone or not selected_date or not selected_time:
            flash("لطفاً همه‌ی فیلدهای ضروری را کامل کنید.", "error")
        elif selected_date not in allowed_dates:
            flash("تاریخ انتخاب‌شده معتبر نیست.", "error")
        elif selected_time not in TIME_SLOTS:
            flash("ساعت انتخاب‌شده معتبر نیست.", "error")
        else:
            try:
                get_db().execute(
                    """INSERT INTO bookings
                    (full_name, phone, selected_date, selected_time, note, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (name, phone, selected_date, selected_time, note,
                     datetime.now().strftime("%Y-%m-%d %H:%M"))
                )
                get_db().commit()
                return redirect(url_for("success", selected_date=selected_date, selected_time=selected_time))
            except sqlite3.IntegrityError:
                flash("این ساعت قبلاً رزرو شده است؛ لطفاً ساعت دیگری را انتخاب کنید.", "error")

    rows = get_db().execute("SELECT selected_date, selected_time FROM bookings").fetchall()
    booked_slots = {f"{r['selected_date']}|{r['selected_time']}" for r in rows}
    return render_template(
        "index.html", dates=dates, slots=TIME_SLOTS, booked_slots=booked_slots,
        selected_date=selected_date, selected_time=selected_time
    )


@app.route("/success")
def success():
    return render_template(
        "success.html",
        selected_date=request.args.get("selected_date", ""),
        selected_time=request.args.get("selected_time", "")
    )


@app.route("/admin")
def admin():
    # برای نمونه است. در پروژه واقعی حتماً ورود/رمز عبور اضافه کنید.
    bookings = get_db().execute(
        "SELECT * FROM bookings ORDER BY selected_date, selected_time"
    ).fetchall()
    return render_template("admin.html", bookings=bookings)


@app.post("/admin/delete/<int:booking_id>")
def delete_booking(booking_id):
    get_db().execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
    get_db().commit()
    flash("رزرو حذف شد.", "success")
    return redirect(url_for("admin"))


@app.route("/health")
def health():
    return {"status": "ok"}, 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
