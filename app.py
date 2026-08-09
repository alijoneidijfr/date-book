from flask import Flask, render_template, request, redirect, session, flash
import sqlite3
import os

app = Flask(__name__)
app.secret_key = "secret_key_123" # برای امنیت سشن‌ها

# تنظیم رمز عبور پنل مدیریت (این را عوض کن)
ADMIN_PASSWORD = "admin" 

def get_db_connection():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

# ساخت جدول دیتابیس در اولین اجرا
def init_db():
    conn = get_db_connection()
    conn.execute('CREATE TABLE IF NOT EXISTS bookings (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, phone TEXT, date TEXT, time TEXT)')
    conn.close()

init_db()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/book', methods=['POST'])
def book():
    name = request.form.get('name')
    phone = request.form.get('phone')
    date = request.form.get('date')
    time = request.form.get('time')
    
    # محدودیت ساعت (16 تا 22)
    hour = int(time.split(':')[0])
    if hour < 16 or hour > 22:
        return "خطا: فقط بین ساعت ۱۶ تا ۲۲ امکان رزرو وجود دارد.", 400

    conn = get_db_connection()
    conn.execute('INSERT INTO bookings (name, phone, date, time) VALUES (?, ?, ?, ?)',
                 (name, phone, date, time))
    conn.commit()
    conn.close()
    return render_template('success.html', name=name)

# بخش مدیریت با رمز عبور
@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if request.method == 'POST':
        password = request.form.get('password')
        if password == ADMIN_PASSWORD:
            session['logged_in'] = True
        else:
            flash('رمز عبور اشتباه است')

    if not session.get('logged_in'):
        return render_template('admin_login.html')

    conn = get_db_connection()
    bookings = conn.execute('SELECT * FROM bookings ORDER BY id DESC').fetchall()
    conn.close()
    return render_template('admin.html', bookings=bookings)

@app.route('/delete/<int:id>')
def delete(id):
    if session.get('logged_in'):
        conn = get_db_connection()
        conn.execute('DELETE FROM bookings WHERE id = ?', (id,))
        conn.commit()
        conn.close()
    return redirect('/admin')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect('/admin')

if __name__ == '__main__':
    app.run(debug=True)
