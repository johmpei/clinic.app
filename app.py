from flask import Flask, render_template, request, redirect, url_for, session, flash
import calendar, sqlite3
from datetime import date, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
import functools
import holidays

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

def login_required(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('ログインが必要です', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def init_db():
    conn = sqlite3.connect('daily_report.db')
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS clinics (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE)")
    cursor.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, clinic_id INTEGER, FOREIGN KEY (clinic_id) REFERENCES clinics(id))")
    cursor.execute("CREATE TABLE IF NOT EXISTS daily_reports (id INTEGER PRIMARY KEY AUTOINCREMENT, clinic_id INTEGER NOT NULL, date TEXT NOT NULL, total_points INTEGER DEFAULT 0, total_sales INTEGER DEFAULT 0, UNIQUE(clinic_id, date), FOREIGN KEY (clinic_id) REFERENCES clinics(id))")
    cursor.execute("CREATE TABLE IF NOT EXISTS shifts (id INTEGER PRIMARY KEY AUTOINCREMENT, daily_report_id INTEGER NOT NULL, time_period TEXT NOT NULL, new_patients INTEGER DEFAULT 0, returning_patients INTEGER DEFAULT 0, total_patients INTEGER DEFAULT 0, FOREIGN KEY (daily_report_id) REFERENCES daily_reports(id) ON DELETE CASCADE, UNIQUE(daily_report_id, time_period))")
    cursor.execute("CREATE TABLE IF NOT EXISTS procedures (id INTEGER PRIMARY KEY AUTOINCREMENT, clinic_id INTEGER NOT NULL, name TEXT NOT NULL UNIQUE, FOREIGN KEY (clinic_id) REFERENCES clinics(id))")
    cursor.execute("CREATE TABLE IF NOT EXISTS procedure_records (id INTEGER PRIMARY KEY AUTOINCREMENT, daily_report_id INTEGER NOT NULL, procedure_id INTEGER NOT NULL, time_period TEXT NOT NULL, count INTEGER DEFAULT 0, FOREIGN KEY (daily_report_id) REFERENCES daily_reports(id) ON DELETE CASCADE, FOREIGN KEY (procedure_id) REFERENCES procedures(id) ON DELETE CASCADE, UNIQUE(daily_report_id, procedure_id, time_period))")
    cursor.execute("CREATE TABLE IF NOT EXISTS doctors (id INTEGER PRIMARY KEY AUTOINCREMENT, clinic_id INTEGER NOT NULL, name TEXT NOT NULL UNIQUE, FOREIGN KEY (clinic_id) REFERENCES clinics(id))")
    cursor.execute("CREATE TABLE IF NOT EXISTS daily_doctor_shifts (id INTEGER PRIMARY KEY AUTOINCREMENT, daily_report_id INTEGER NOT NULL, doctor_id INTEGER NOT NULL, time_period TEXT NOT NULL, FOREIGN KEY (daily_report_id) REFERENCES daily_reports(id) ON DELETE CASCADE, FOREIGN KEY (doctor_id) REFERENCES doctors(id) ON DELETE CASCADE, UNIQUE(daily_report_id, doctor_id, time_period))")
    conn.commit()
    conn.close()

with app.app_context():
    init_db()

# --- ログイン・登録関連ルート ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = sqlite3.connect('daily_report.db')
        cursor = conn.cursor()
        cursor.execute("SELECT id, password_hash, clinic_id FROM users WHERE username=?", (username,))
        user = cursor.fetchone()
        conn.close()
        if user and check_password_hash(user[1], password):
            session['user_id'] = user[0]
            session['clinic_id'] = user[2]
            flash('ログインしました！', 'success')
            return redirect(url_for('index'))
        else:
            flash('ユーザー名またはパスワードが違います', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('clinic_id', None)
    flash('ログアウトしました', 'info')
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        clinic_name = request.form['clinic_name']
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        conn = sqlite3.connect('daily_report.db')
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO clinics (name) VALUES (?)", (clinic_name,))
            clinic_id = cursor.lastrowid
            cursor.execute("INSERT INTO users (username, password_hash, clinic_id) VALUES (?, ?, ?)", (username, hashed_password, clinic_id))
            conn.commit()
            flash('アカウントが作成されました！ログインしてください。', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError as e:
            conn.rollback()
            if "UNIQUE constraint failed: users.username" in str(e): flash('そのユーザー名は既に存在します。', 'danger')
            elif "UNIQUE constraint failed: clinics.name" in str(e): flash('そのクリニック名は既に存在します。別の名前を試してください。', 'danger')
            else: flash(f'登録中にエラーが発生しました: {e}', 'danger')
        finally: conn.close()
    return render_template('register.html')

# --- メイン機能ルート ---
@app.route('/')
@app.route('/<int:year>/<int:month>')
@login_required
def index(year=None, month=None):
    today = date.today()
    if year is None: year = today.year
    if month is None: month = today.month
    next_month, next_year = (1, year + 1) if month == 12 else (month + 1, year)
    prev_month, prev_year = (12, year - 1) if month == 1 else (month - 1, year)

    cal = calendar.Calendar(firstweekday=6)
    month_days = cal.monthdayscalendar(year, month)
    
    user_id = session.get('user_id')
    clinic_id = session.get('clinic_id')
    username, clinic_name = "ゲスト", "未所属クリニック"

    conn = sqlite3.connect('daily_report.db')
    cursor = conn.cursor()
    if user_id:
        cursor.execute("SELECT username, clinic_id FROM users WHERE id=?", (user_id,))
        user_data = cursor.fetchone()
        if user_data:
            username, clinic_id = user_data
            if clinic_id:
                cursor.execute("SELECT name FROM clinics WHERE id=?", (clinic_id,))
                clinic_data = cursor.fetchone()
                if clinic_data: clinic_name = clinic_data[0]

    daily_summaries = {}
    if clinic_id:
        cursor.execute("SELECT strftime('%d', DR.date) as day, SUM(S.total_patients) as total_patients, DR.total_points FROM daily_reports DR LEFT JOIN shifts S ON DR.id = S.daily_report_id WHERE DR.clinic_id = ? AND strftime('%Y', DR.date) = ? AND strftime('%m', DR.date) = ? GROUP BY DR.date", (clinic_id, str(year), f"{month:02d}"))
        for day_str, total_patients, total_points in cursor.fetchall():
            daily_summaries[int(day_str)] = {'total_patients': total_patients or 0, 'total_points': total_points or 0}
    conn.close()

    return render_template('index.html', year=year, month=month, month_days=month_days, daily_summaries=daily_summaries, prev_year=prev_year, prev_month=prev_month, next_year=next_year, next_month=next_month, jp_holidays=holidays.Japan(), date_class=date, username=username, clinic_name=clinic_name)

@app.route('/report/<int:year>/<int:month>/<int:day>', methods=['GET', 'POST'])
@login_required
def daily_report(year, month, day):
    # (この関数は長いため省略しますが、内容は変更ありません)
    report_date_obj = date(year, month, day)
    report_date = report_date_obj.strftime("%Y-%m-%d")
    prev_day_obj = report_date_obj - timedelta(days=1)
    next_day_obj = report_date_obj + timedelta(days=1)
    clinic_id = session.get('clinic_id')
    if not clinic_id:
        flash('クリニック情報が見つかりません。再ログインしてください。', 'danger')
        return redirect(url_for('login'))
    conn = sqlite3.connect('daily_report.db')
    cursor = conn.cursor()
    if request.method == 'POST':
        total_points = request.form.get('total_points', 0, type=int)
        total_sales = request.form.get('total_sales', 0, type=int)
        cursor.execute("SELECT id FROM daily_reports WHERE clinic_id=? AND date=?", (clinic_id, report_date))
        result = cursor.fetchone()
        if result:
            daily_report_id = result[0]
            cursor.execute("UPDATE daily_reports SET total_points=?, total_sales=? WHERE id=?", (total_points, total_sales, daily_report_id))
        else:
            cursor.execute("INSERT INTO daily_reports (clinic_id, date, total_points, total_sales) VALUES (?, ?, ?, ?)", (clinic_id, report_date, total_points, total_sales))
            daily_report_id = cursor.lastrowid
        for period in ['AM', 'PM']:
            new = request.form.get(f'new_{period}', 0, type=int); ret = request.form.get(f'return_{period}', 0, type=int); total = new + ret
            cursor.execute("REPLACE INTO shifts (daily_report_id, time_period, new_patients, returning_patients, total_patients) VALUES (?, ?, ?, ?, ?)", (daily_report_id, period, new, ret, total))
        cursor.execute("DELETE FROM daily_doctor_shifts WHERE daily_report_id=?", (daily_report_id,))
        for period in ['AM', 'PM']:
            for doctor_id in request.form.getlist(f'doctors_{period}[]'):
                if doctor_id: cursor.execute("INSERT INTO daily_doctor_shifts (daily_report_id, doctor_id, time_period) VALUES (?, ?, ?)", (daily_report_id, int(doctor_id), period))
        procedures_master = cursor.execute("SELECT id FROM procedures WHERE clinic_id=?", (clinic_id,)).fetchall()
        for proc_id in procedures_master:
            for period in ['AM', 'PM']:
                count = request.form.get(f'procedure_{proc_id[0]}_{period}', 0, type=int)
                cursor.execute("REPLACE INTO procedure_records (daily_report_id, procedure_id, time_period, count) VALUES (?, ?, ?, ?)", (daily_report_id, proc_id[0], period, count))
        conn.commit()
        conn.close()
        flash('保存しました！', 'success')
        return redirect(url_for('daily_report', year=year, month=month, day=day))
    
    # GET request
    cursor.execute("SELECT id, name FROM procedures WHERE clinic_id=?", (clinic_id,)); procedures_master = cursor.fetchall()
    cursor.execute("SELECT id, name FROM doctors WHERE clinic_id=?", (clinic_id,)); doctors_master = cursor.fetchall()
    cursor.execute("SELECT id, total_points, total_sales FROM daily_reports WHERE clinic_id=? AND date=?", (clinic_id, report_date)); result = cursor.fetchone()
    daily_report_id = result[0] if result else None; total_points = result[1] if result else 0; total_sales = result[2] if result else 0
    shifts = {p: {'new_patients': 0, 'returning_patients': 0, 'total_patients': 0} for p in ['AM', 'PM', '夜間']}
    if daily_report_id:
        cursor.execute("SELECT time_period, new_patients, returning_patients, total_patients FROM shifts WHERE daily_report_id=?", (daily_report_id,))
        for row in cursor.fetchall(): shifts[row[0]] = {'new_patients': row[1], 'returning_patients': row[2], 'total_patients': row[3]}
    procedures_records = {proc[0]: {} for proc in procedures_master}
    if daily_report_id:
        cursor.execute("SELECT procedure_id, time_period, count FROM procedure_records WHERE daily_report_id=?", (daily_report_id,))
        for p_id, period, count in cursor.fetchall(): procedures_records[p_id][period] = count
    daily_doctors = {p: [] for p in ['AM', 'PM', '夜間']}
    if daily_report_id:
        cursor.execute("SELECT doctor_id, time_period FROM daily_doctor_shifts WHERE daily_report_id=?", (daily_report_id,))
        for doc_id, period in cursor.fetchall(): daily_doctors[period].append(doc_id)
    conn.close()
    return render_template('daily_report.html', year=year, month=month, day=day, total_points=total_points, total_sales=total_sales, shifts=shifts, procedures=procedures_master, procedures_records=procedures_records, doctors=doctors_master, daily_doctors=daily_doctors, message=None, date=report_date_obj, prev_day_year=prev_day_obj.year, prev_day_month=prev_day_obj.month, prev_day_day=prev_day_obj.day, next_day_year=next_day_obj.year, next_day_month=next_day_obj.month, next_day_day=next_day_obj.day)

# ▼▼▼【ここから追加・復活】▼▼▼
@app.route('/delete_report/<int:year>/<int:month>/<int:day>', methods=['POST'])
@login_required
def delete_report(year, month, day):
    report_date = f"{year:04d}-{month:02d}-{day:02d}"
    clinic_id = session.get('clinic_id')
    conn = sqlite3.connect('daily_report.db')
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM daily_reports WHERE clinic_id=? AND date=?", (clinic_id, report_date))
        daily_report_id = cursor.fetchone()
        if daily_report_id:
            cursor.execute("DELETE FROM daily_reports WHERE id=?", (daily_report_id[0],))
            conn.commit()
            flash('日報を削除しました。', 'success')
        else:
            flash('削除対象の日報が見つかりませんでした。', 'warning')
    except Exception as e:
        conn.rollback()
        flash(f'日報の削除中にエラーが発生しました: {e}', 'danger')
    finally:
        conn.close()
    return redirect(url_for('index'))

@app.route('/manage_masters', methods=['GET', 'POST'])
@login_required
def manage_masters():
    clinic_id = session.get('clinic_id')
    conn = sqlite3.connect('daily_report.db')
    cursor = conn.cursor()
    if request.method == 'POST':
        if 'add_doctor_name' in request.form:
            doctor_name = request.form['add_doctor_name']
            try:
                cursor.execute("INSERT INTO doctors (clinic_id, name) VALUES (?, ?)", (clinic_id, doctor_name))
                conn.commit()
                flash(f"ドクター「{doctor_name}」を追加しました！", 'success')
            except sqlite3.IntegrityError:
                flash(f"ドクター「{doctor_name}」は既に存在します。", 'danger')
        elif 'delete_doctor_id' in request.form:
            cursor.execute("DELETE FROM doctors WHERE id=? AND clinic_id=?", (request.form['delete_doctor_id'], clinic_id))
            conn.commit()
            flash("ドクターを削除しました。", 'info')
        elif 'add_procedure_name' in request.form:
            procedure_name = request.form['add_procedure_name']
            try:
                cursor.execute("INSERT INTO procedures (clinic_id, name) VALUES (?, ?)", (clinic_id, procedure_name))
                conn.commit()
                flash(f"処置「{procedure_name}」を追加しました！", 'success')
            except sqlite3.IntegrityError:
                flash(f"処置「{procedure_name}」は既に存在します。", 'danger')
        elif 'delete_procedure_id' in request.form:
            cursor.execute("DELETE FROM procedures WHERE id=? AND clinic_id=?", (request.form['delete_procedure_id'], clinic_id))
            conn.commit()
            flash("処置を削除しました。", 'info')
        return redirect(url_for('manage_masters'))
    
    cursor.execute("SELECT id, name FROM doctors WHERE clinic_id=?", (clinic_id,))
    doctors = cursor.fetchall()
    cursor.execute("SELECT id, name FROM procedures WHERE clinic_id=?", (clinic_id,))
    procedures = cursor.fetchall()
    conn.close()
    return render_template('manage_masters.html', doctors=doctors, procedures=procedures)
# ▲▲▲【ここまで追加・復活】▲▲▲

# --- ヘルパー関数群 ---
def get_monthly_data(year, month, clinic_id):
    conn = sqlite3.connect('daily_report.db')
    cursor = conn.cursor()
    cursor.execute("SELECT SUM(dr.total_sales), SUM(dr.total_points), SUM(s.new_patients), SUM(s.returning_patients), SUM(s.total_patients) FROM daily_reports dr LEFT JOIN (SELECT daily_report_id, SUM(new_patients) as new_patients, SUM(returning_patients) as returning_patients, SUM(total_patients) as total_patients FROM shifts GROUP BY daily_report_id) s ON dr.id = s.daily_report_id WHERE dr.clinic_id = ? AND STRFTIME('%Y', dr.date) = ? AND STRFTIME('%m', dr.date) = ?", (clinic_id, str(year), f"{month:02d}"))
    data = cursor.fetchone()
    conn.close()
    return {'total_sales': data[0] or 0, 'total_points': data[1] or 0, 'new_patients': data[2] or 0, 'returning_patients': data[3] or 0, 'total_patients': data[4] or 0}

def get_daily_trend_data(year, month, clinic_id):
    conn = sqlite3.connect('daily_report.db')
    cursor = conn.cursor()
    cursor.execute("SELECT CAST(STRFTIME('%d', dr.date) AS INTEGER) as day, dr.total_points, (SELECT SUM(total_patients) FROM shifts s WHERE s.daily_report_id = dr.id) as daily_total_patients FROM daily_reports dr WHERE dr.clinic_id = ? AND STRFTIME('%Y', dr.date) = ? AND STRFTIME('%m', dr.date) = ? ORDER BY day", (clinic_id, str(year), f"{month:02d}"))
    report_data = {row[0]: (row[1] or 0, row[2] or 0) for row in cursor.fetchall()}
    conn.close()
    days, points, patients, day_colors = [], [], [], []
    num_days = calendar.monthrange(year, month)[1]
    jp_holidays = holidays.Japan()
    for day_num in range(1, num_days + 1):
        days.append(day_num)
        day_points, day_patients = report_data.get(day_num, (0, 0))
        points.append(day_points)
        patients.append(day_patients)
        current_date = date(year, month, day_num)
        if current_date in jp_holidays or current_date.weekday() == 6: day_colors.append('red')
        elif current_date.weekday() == 5: day_colors.append('blue')
        else: day_colors.append('#666')
    average_points = sum(points) / len(points) if points else 0
    return {'days': days, 'points': points, 'patients': patients, 'average_points': average_points, 'day_colors': day_colors}

def calculate_business_days(year, month):
    jp_holidays = holidays.Japan()
    business_days = 0
    cal = calendar.Calendar()
    for day in cal.itermonthdates(year, month):
        if day.month == month and day.weekday() < 5 and day not in jp_holidays: business_days += 1
        elif day.month == month and day.weekday() == 5 and day not in jp_holidays: business_days += 0.5
    return business_days

def get_monthly_procedure_counts(year, month, clinic_id):
    conn = sqlite3.connect('daily_report.db')
    cursor = conn.cursor()
    target_procedures = ['胃カメラ', '大腸カメラ（ポリペクなし）', '大腸カメラ（ポリペクあり）', 'インフルエンザワクチン', '健診（自治体）']
    placeholders = ','.join('?' for _ in target_procedures)
    query = f"SELECT p.name, SUM(pr.count) FROM procedure_records pr JOIN procedures p ON pr.procedure_id = p.id JOIN daily_reports dr ON pr.daily_report_id = dr.id WHERE dr.clinic_id = ? AND STRFTIME('%Y', dr.date) = ? AND STRFTIME('%m', dr.date) = ? AND p.name IN ({placeholders}) GROUP BY p.name"
    params = [clinic_id, str(year), f"{month:02d}"] + target_procedures
    cursor.execute(query, params)
    counts = {name: 0 for name in target_procedures}
    for row in cursor.fetchall(): counts[row[0]] = row[1]
    conn.close()
    return counts

def get_cumulative_daily_points_data(year, month, clinic_id):
    if not clinic_id: return {'days': [], 'cumulative_points': [], 'last_year_total_points': 0}
    conn = sqlite3.connect('daily_report.db')
    cursor = conn.cursor()
    _, num_days = calendar.monthrange(year, month)
    daily_points = {day: 0 for day in range(1, num_days + 1)}
    cursor.execute("SELECT CAST(STRFTIME('%d', date) AS INTEGER) as day, total_points FROM daily_reports WHERE clinic_id = ? AND STRFTIME('%Y', date) = ? AND STRFTIME('%m', date) = ?", (clinic_id, str(year), f"{month:02d}"))
    for row in cursor.fetchall(): daily_points[row[0]] = row[1] or 0
    cumulative_points = []
    current_total = 0
    for day in range(1, num_days + 1):
        current_total += daily_points[day]
        cumulative_points.append(current_total)
    cursor.execute("SELECT SUM(total_points) FROM daily_reports WHERE clinic_id = ? AND STRFTIME('%Y', date) = ? AND STRFTIME('%m', date) = ?", (clinic_id, str(year - 1), f"{month:02d}"))
    last_year_total_points = cursor.fetchone()[0] or 0
    conn.close()
    return {'days': list(range(1, num_days + 1)), 'cumulative_points': cumulative_points, 'last_year_total_points': last_year_total_points}

def get_cumulative_daily_patients_data(year, month, clinic_id):
    if not clinic_id: return {'days': [], 'cumulative_patients': [], 'last_year_total_patients': 0}
    conn = sqlite3.connect('daily_report.db')
    cursor = conn.cursor()
    _, num_days = calendar.monthrange(year, month)
    daily_patients = {day: 0 for day in range(1, num_days + 1)}
    cursor.execute("SELECT CAST(STRFTIME('%d', dr.date) AS INTEGER) as day, (SELECT SUM(s.total_patients) FROM shifts s WHERE s.daily_report_id = dr.id) as daily_total FROM daily_reports dr WHERE dr.clinic_id = ? AND STRFTIME('%Y', dr.date) = ? AND STRFTIME('%m', dr.date) = ?", (clinic_id, str(year), f"{month:02d}"))
    for row in cursor.fetchall(): daily_patients[row[0]] = row[1] or 0
    cumulative_patients = []
    current_total = 0
    for day in range(1, num_days + 1):
        current_total += daily_patients[day]
        cumulative_patients.append(current_total)
    cursor.execute("SELECT SUM(s.total_patients) FROM shifts s JOIN daily_reports dr ON s.daily_report_id = dr.id WHERE dr.clinic_id = ? AND STRFTIME('%Y', dr.date) = ? AND STRFTIME('%m', dr.date) = ?", (clinic_id, str(year - 1), f"{month:02d}"))
    last_year_total_patients = cursor.fetchone()[0] or 0
    conn.close()
    return {'days': list(range(1, num_days + 1)), 'cumulative_patients': cumulative_patients, 'last_year_total_patients': last_year_total_patients}

def get_summary_data(target_year, target_month, clinic_id):
    if not clinic_id: return None
    base_data = get_monthly_data(target_year, target_month, clinic_id)
    proc_counts = get_monthly_procedure_counts(target_year, target_month, clinic_id)
    business_days = calculate_business_days(target_year, target_month)
    total_patients = base_data.get('total_patients', 0)
    total_points = base_data.get('total_points', 0)
    new_patients = base_data.get('new_patients', 0)
    avg_daily_patients = (total_patients / business_days) if business_days > 0 else 0
    new_patient_rate = (new_patients / total_patients * 100) if total_patients > 0 else 0
    avg_price = (total_points / total_patients * 10) if total_patients > 0 else 0
    return {'total_patients': total_patients, 'business_days': business_days, 'avg_daily_patients': avg_daily_patients, 'new_patient_rate': new_patient_rate, 'total_points': total_points, 'avg_price': avg_price, 'g_camera': proc_counts.get('胃カメラ', 0), 'c_camera_no_polypectomy': proc_counts.get('大腸カメラ（ポリペクなし）', 0), 'c_camera_with_polypectomy': proc_counts.get('大腸カメラ（ポリペクあり）', 0), 'flu_vaccine': proc_counts.get('インフルエンザワクチン', 0), 'health_check': proc_counts.get('健診（自治体）', 0)}

def get_yearly_trend_data(end_year, end_month, clinic_id):
    labels, kpi_data = [], {key: [] for key in ['total_patients', 'business_days', 'avg_daily_patients', 'new_patient_rate', 'total_points', 'avg_price', 'g_camera', 'c_camera_no_polypectomy', 'c_camera_with_polypectomy', 'flu_vaccine', 'health_check']}
    current_date = date(end_year, end_month, 1)
    for _ in range(12):
        year, month = current_date.year, current_date.month
        summary = get_summary_data(year, month, clinic_id)
        labels.insert(0, f"{year % 100:02d}/{month:02d}")
        if summary:
            for key in kpi_data.keys(): kpi_data[key].insert(0, summary.get(key, 0))
        else:
            for key in kpi_data.keys(): kpi_data[key].insert(0, 0)
        current_date = date(year, month, 1) - timedelta(days=1)
    return {'labels': labels, 'kpi_data': kpi_data}

def get_heatmap_data(clinic_id, start_date, end_date):
    conn = sqlite3.connect('daily_report.db')
    cursor = conn.cursor()
    query = "SELECT CAST(strftime('%w', dr.date) AS INTEGER) as day_of_week, s.time_period, AVG(s.total_patients) as avg_patients FROM daily_reports dr JOIN shifts s ON dr.id = s.daily_report_id WHERE dr.clinic_id = ? AND dr.date BETWEEN ? AND ? GROUP BY day_of_week, s.time_period"
    cursor.execute(query, (clinic_id, start_date, end_date))
    heatmap_data = {i: {} for i in range(1, 8)}
    for day, period, avg_p in cursor.fetchall():
        day_adjusted = day if day != 0 else 7
        if day_adjusted > 0: heatmap_data[day_adjusted][period] = avg_p
    conn.close()
    return heatmap_data

def get_color_for_value(value, min_val, max_val):
    if value is None or min_val is None or max_val is None or min_val == max_val: return "#f0f0f0"
    normalized = (value - min_val) / (max_val - min_val)
    hue = 180 * (1 - normalized)
    return f"hsl({hue}, 80%, 65%)"

@app.route('/monthly_report', methods=['GET', 'POST'])
@login_required
def monthly_report():
    clinic_id = session.get('clinic_id')
    user_id = session.get('user_id')
    username, clinic_name = "ゲスト", "未所属クリニック"
    conn = sqlite3.connect('daily_report.db')
    cursor = conn.cursor()
    if user_id:
        cursor.execute("SELECT username, clinic_id FROM users WHERE id=?", (user_id,))
        user_data = cursor.fetchone()
        if user_data:
            username, clinic_id = user_data
            if clinic_id:
                cursor.execute("SELECT name FROM clinics WHERE id=?", (clinic_id,))
                clinic_data = cursor.fetchone()
                if clinic_data: clinic_name = clinic_data[0]
    conn.close()

    today = date.today()
    year = request.form.get('year', default=today.year, type=int)
    month = request.form.get('month', default=today.month, type=int)

    current_summary = get_summary_data(year, month, clinic_id)
    last_year_summary = get_summary_data(year - 1, month, clinic_id)
    trend_data = get_daily_trend_data(year, month, clinic_id)
    cumulative_points_data = get_cumulative_daily_points_data(year, month, clinic_id)
    cumulative_patients_data = get_cumulative_daily_patients_data(year, month, clinic_id)
    yearly_trend_data = get_yearly_trend_data(year, month, clinic_id)

    year_options = range(today.year, today.year - 10, -1)
    
    return render_template('monthly_report.html', year=year, month=month, year_options=year_options, current_data=current_summary, last_year_data=last_year_summary, trend_data=trend_data, cumulative_points_data=cumulative_points_data, cumulative_patients_data=cumulative_patients_data, yearly_trend_data=yearly_trend_data, username=username, clinic_name=clinic_name)

@app.route('/analysis/heatmap', methods=['GET', 'POST'])
@login_required
def heatmap_analysis():
    clinic_id = session.get('clinic_id')
    today = date.today()
    start_date_default = (today - timedelta(days=90)).strftime("%Y-%m-%d")
    end_date_default = today.strftime("%Y-%m-%d")
    start_date = request.form.get('start_date', start_date_default)
    end_date = request.form.get('end_date', end_date_default)
    raw_data = get_heatmap_data(clinic_id, start_date, end_date)
    all_values = [v for day_data in raw_data.values() for v in day_data.values()]
    min_avg = min(all_values) if all_values else 0
    max_avg = max(all_values) if all_values else 0
    return render_template('heatmap.html', heatmap_data=raw_data, start_date=start_date, end_date=end_date, min_avg=min_avg, max_avg=max_avg, get_color_for_value=get_color_for_value, username=session.get('username', 'ゲスト'), clinic_name=session.get('clinic_name', '未所属'))

if __name__ == '__main__':
    app.run(debug=True)