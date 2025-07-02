from flask import Flask, render_template, request, redirect, url_for, session, flash
import calendar, sqlite3
from datetime import date, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
import functools
import holidays

app = Flask(__name__)
app.secret_key = 'your_secret_key_here' # 本番環境ではより複雑なものに変更してください

# 各ルートの保護 (login_required デコレータ)
def login_required(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('ログインが必要です', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# データベースの初期化関数
def init_db():
    conn = sqlite3.connect('daily_report.db')
    cursor = conn.cursor()
    # clinics テーブルが存在しない場合のみ作成
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clinics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )
    """)
    # users テーブルが存在しない場合のみ作成 (clinic_idを追加)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            clinic_id INTEGER,
            FOREIGN KEY (clinic_id) REFERENCES clinics(id)
        )
    """)
    # daily_reports テーブルが存在しない場合のみ作成
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clinic_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            total_points INTEGER DEFAULT 0,
            total_sales INTEGER DEFAULT 0,
            UNIQUE(clinic_id, date),
            FOREIGN KEY (clinic_id) REFERENCES clinics(id)
        )
    """)
    # shifts テーブルが存在しない場合のみ作成
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS shifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            daily_report_id INTEGER NOT NULL,
            time_period TEXT NOT NULL, -- 'AM', 'PM', '夜間'
            new_patients INTEGER DEFAULT 0,
            returning_patients INTEGER DEFAULT 0,
            total_patients INTEGER DEFAULT 0,
            FOREIGN KEY (daily_report_id) REFERENCES daily_reports(id) ON DELETE CASCADE,
            UNIQUE(daily_report_id, time_period)
        )
    """)
    # procedures テーブルが存在しない場合のみ作成
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS procedures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clinic_id INTEGER NOT NULL,
            name TEXT NOT NULL UNIQUE,
            FOREIGN KEY (clinic_id) REFERENCES clinics(id)
        )
    """)
    # procedure_records テーブルが存在しない場合のみ作成
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS procedure_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            daily_report_id INTEGER NOT NULL,
            procedure_id INTEGER NOT NULL,
            time_period TEXT NOT NULL, -- 'AM', 'PM', '夜間'
            count INTEGER DEFAULT 0,
            FOREIGN KEY (daily_report_id) REFERENCES daily_reports(id) ON DELETE CASCADE,
            FOREIGN KEY (procedure_id) REFERENCES procedures(id) ON DELETE CASCADE,
            UNIQUE(daily_report_id, procedure_id, time_period)
        )
    """)
    # doctors テーブルが存在しない場合のみ作成
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS doctors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clinic_id INTEGER NOT NULL,
            name TEXT NOT NULL UNIQUE,
            FOREIGN KEY (clinic_id) REFERENCES clinics(id)
        )
    """)
    # daily_doctor_shifts テーブルが存在しない場合のみ作成
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_doctor_shifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            daily_report_id INTEGER NOT NULL,
            doctor_id INTEGER NOT NULL,
            time_period TEXT NOT NULL, -- 'AM', 'PM', '夜間'
            FOREIGN KEY (daily_report_id) REFERENCES daily_reports(id) ON DELETE CASCADE,
            FOREIGN KEY (doctor_id) REFERENCES doctors(id) ON DELETE CASCADE,
            UNIQUE(daily_report_id, doctor_id, time_period)
        )
    """)
    conn.commit()
    conn.close()

# アプリケーション起動時にDB初期化を実行
with app.app_context():
    init_db()

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
            session['clinic_id'] = user[2] # ログイン時にclinic_idをセッションに保存
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
        clinic_name = request.form['clinic_name'] # clinic_idではなくclinic_nameを受け取る

        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')

        conn = sqlite3.connect('daily_report.db')
        cursor = conn.cursor()
        try:
            # クリニックを登録
            cursor.execute("INSERT INTO clinics (name) VALUES (?)", (clinic_name,))
            clinic_id = cursor.lastrowid # 新しく作成されたクリニックのIDを取得
            
            # ユーザーを登録 (clinic_idと紐付け)
            cursor.execute("INSERT INTO users (username, password_hash, clinic_id) VALUES (?, ?, ?)",
                           (username, hashed_password, clinic_id))
            conn.commit()
            flash('アカウントが作成されました！ログインしてください。', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError as e:
            conn.rollback()
            # エラーメッセージをより具体的に
            if "UNIQUE constraint failed: users.username" in str(e):
                flash('そのユーザー名は既に存在します。', 'danger')
            elif "UNIQUE constraint failed: clinics.name" in str(e):
                flash('そのクリニック名は既に存在します。別の名前を試してください。', 'danger')
            else:
                flash(f'登録中にエラーが発生しました: {e}', 'danger')
        except Exception as e:
            conn.rollback()
            flash(f'予期せぬエラーが発生しました: {e}', 'danger')
        finally:
            conn.close()
    return render_template('register.html') # clinicsデータは不要なので渡さない

@app.route('/')
@app.route('/<int:year>/<int:month>')
@login_required
def index(year=None, month=None):
    today = date.today()

    if year is None or not isinstance(year, int):
        year = today.year
    if month is None or not isinstance(month, int) or not (1 <= month <= 12):
        month = today.month

    if month == 12:
        next_month = 1
        next_year = year + 1
    else:
        next_month = month + 1
        next_year = year

    if month == 1:
        prev_month = 12
        prev_year = year - 1
    else:
        prev_month = month - 1
        prev_year = year

    cal = calendar.Calendar(firstweekday=6) # 週の始まりを日曜日に設定 (0=月曜, 6=日曜)
    month_days = cal.monthdayscalendar(year, month)
    
    user_id = session.get('user_id')
    username = "ゲスト"
    clinic_name = "未所属クリニック"
    clinic_id = session.get('clinic_id') # セッションからclinic_idを取得

    conn = sqlite3.connect('daily_report.db')
    cursor = conn.cursor()
    
    if user_id:
        cursor.execute("SELECT username, clinic_id FROM users WHERE id=?", (user_id,))
        user_data = cursor.fetchone()
        if user_data:
            username = user_data[0]
            # データベースから取得したclinic_idを優先
            clinic_id_from_db = user_data[1] 
            if clinic_id_from_db and clinic_id_from_db != clinic_id:
                session['clinic_id'] = clinic_id_from_db # セッションも更新
                clinic_id = clinic_id_from_db

            if clinic_id:
                cursor.execute("SELECT name FROM clinics WHERE id=?", (clinic_id,))
                clinic_data = cursor.fetchone()
                if clinic_data:
                    clinic_name = clinic_data[0]

    daily_summaries = {}
    if clinic_id: # clinic_idがある場合のみデータを取得
        cursor.execute("""
            SELECT
                strftime('%d', DR.date) as day,
                SUM(S.total_patients) as total_patients,
                DR.total_points
            FROM daily_reports DR
            LEFT JOIN shifts S ON DR.id = S.daily_report_id
            WHERE DR.clinic_id = ? AND strftime('%Y', DR.date) = ? AND strftime('%m', DR.date) = ?
            GROUP BY DR.date
        """, (clinic_id, str(year), f"{month:02d}"))

        for row in cursor.fetchall():
            day_str, total_patients, total_points = row
            daily_summaries[int(day_str)] = {
                'total_patients': total_patients if total_patients is not None else 0,
                'total_points': total_points if total_points is not None else 0
            }
    conn.close()

    jp_holidays = holidays.Japan()

    return render_template(
        'index.html',
        year=year,
        month=month,
        month_days=month_days,
        daily_summaries=daily_summaries,
        prev_year=prev_year,
        prev_month=prev_month,
        next_year=next_year,
        next_month=next_month,
        jp_holidays=jp_holidays,
        date_class=date,
        username=username,
        clinic_name=clinic_name # クリニック名をテンプレートに渡す
    )

@app.route('/report/<int:year>/<int:month>/<int:day>', methods=['GET', 'POST'])
@login_required
def daily_report(year, month, day):
    report_date_obj = date(year, month, day)
    report_date = report_date_obj.strftime("%Y-%m-%d")

    prev_day_obj = report_date_obj - timedelta(days=1)
    next_day_obj = report_date_obj + timedelta(days=1)

    clinic_id = session.get('clinic_id')
    user_id = session.get('user_id')
    username = "ゲスト"
    clinic_name = "未所属クリニック"

    conn = sqlite3.connect('daily_report.db')
    cursor = conn.cursor()
    if user_id:
        cursor.execute("SELECT username, clinic_id FROM users WHERE id=?", (user_id,))
        user_data = cursor.fetchone()
        if user_data:
            username = user_data[0]
            current_clinic_id = user_data[1]
            if current_clinic_id:
                cursor.execute("SELECT name FROM clinics WHERE id=?", (current_clinic_id,))
                clinic_data = cursor.fetchone()
                if clinic_data:
                    clinic_name = clinic_data[0]

    if not clinic_id:
        flash('クリニック情報が見つかりません。再ログインしてください。', 'danger')
        conn.close()
        return redirect(url_for('login'))

    message = None

    cursor.execute("SELECT id, name FROM procedures WHERE clinic_id=?", (clinic_id,))
    procedures_master = cursor.fetchall()

    cursor.execute("SELECT id, name FROM doctors WHERE clinic_id=?", (clinic_id,))
    doctors_master = cursor.fetchall()

    cursor.execute(
        "SELECT id, total_points, total_sales FROM daily_reports WHERE clinic_id=? AND date=?",
        (clinic_id, report_date)
    )
    result = cursor.fetchone()
    daily_report_id = result[0] if result else None
    total_points = result[1] if result else 0
    total_sales = result[2] if result else 0

    shifts = {}
    if daily_report_id:
        cursor.execute(
            "SELECT time_period, new_patients, returning_patients, total_patients FROM shifts WHERE daily_report_id=?",
            (daily_report_id,)
        )
        shifts_data = cursor.fetchall()
        for row in shifts_data:
            period, new_patients, returning_patients, total_patients = row
            shifts[period] = {
                'new_patients': new_patients,
                'returning_patients': returning_patients,
                'total_patients': total_patients
            }
    for period in ['AM', 'PM', '夜間']:
        if period not in shifts:
            shifts[period] = {'new_patients': 0, 'returning_patients': 0, 'total_patients': 0}

    procedures_records = {}
    if daily_report_id:
        cursor.execute(
            "SELECT procedure_id, time_period, count FROM procedure_records WHERE daily_report_id=?",
            (daily_report_id,)
        )
        proc_records_data = cursor.fetchall()
        for row in proc_records_data:
            procedure_id, time_period, count = row
            if procedure_id not in procedures_records:
                procedures_records[procedure_id] = {}
            procedures_records[procedure_id][time_period] = count

    for proc_id, _ in procedures_master:
        if proc_id not in procedures_records:
            procedures_records[proc_id] = {}
        for period in ['AM', 'PM', '夜間']:
            if period not in procedures_records[proc_id]:
                procedures_records[proc_id][period] = 0

    daily_doctors = {'AM': [], 'PM': [], '夜間': []}
    if daily_report_id:
        cursor.execute(
            "SELECT doctor_id, time_period FROM daily_doctor_shifts WHERE daily_report_id=?",
            (daily_report_id,)
        )
        doctor_shifts_data = cursor.fetchall()
        for doctor_id, time_period in doctor_shifts_data:
            if time_period in daily_doctors:
                daily_doctors[time_period].append(doctor_id)
    for period in ['AM', 'PM', '夜間']:
        if period not in daily_doctors:
            daily_doctors[period] = []

    if request.method == 'POST':
        total_points = request.form.get('total_points', 0, type=int) # int型で取得
        total_sales = request.form.get('total_sales', 0, type=int)   # int型で取得

        if result:
            cursor.execute(
                "UPDATE daily_reports SET total_points=?, total_sales=? WHERE clinic_id=? AND date=?",
                (total_points, total_sales, clinic_id, report_date)
            )
            daily_report_id = result[0]
        else:
            cursor.execute(
                "INSERT INTO daily_reports (clinic_id, date, total_points, total_sales) VALUES (?, ?, ?, ?)",
                (clinic_id, report_date, total_points, total_sales)
            )
            daily_report_id = cursor.lastrowid

        for period in ['AM', 'PM']: # '夜間' は現在HTML側にinputがないため除外
            new_patients = request.form.get(f'new_{period}', 0, type=int)
            returning_patients = request.form.get(f'return_{period}', 0, type=int)
            total_patients = request.form.get(f'total_{period}', 0, type=int)

            cursor.execute(
                "SELECT id FROM shifts WHERE daily_report_id=? AND time_period=?",
                (daily_report_id, period)
            )
            shift = cursor.fetchone()
            if shift:
                cursor.execute(
                    "UPDATE shifts SET new_patients=?, returning_patients=?, total_patients=? WHERE daily_report_id=? AND time_period=?",
                    (new_patients, returning_patients, total_patients, daily_report_id, period)
                )
            else:
                cursor.execute(
                    "INSERT INTO shifts (daily_report_id, time_period, new_patients, returning_patients, total_patients) VALUES (?, ?, ?, ?, ?)",
                    (daily_report_id, period, new_patients, returning_patients, total_patients)
                )

        for procedure_id, _ in procedures_master:
            for period in ['AM', 'PM']: # '夜間' は現在HTML側にinputがないため除外
                count = request.form.get(f'procedure_{procedure_id}_{period}', 0, type=int)

                cursor.execute(
                    "SELECT id FROM procedure_records WHERE daily_report_id=? AND procedure_id=? AND time_period=?",
                    (daily_report_id, procedure_id, period)
                )
                record = cursor.fetchone()
                if record:
                    cursor.execute(
                        "UPDATE procedure_records SET count=? WHERE daily_report_id=? AND procedure_id=? AND time_period=?",
                        (count, daily_report_id, procedure_id, period)
                    )
                else:
                    cursor.execute(
                        "INSERT INTO procedure_records (daily_report_id, procedure_id, time_period, count) VALUES (?, ?, ?, ?)",
                        (daily_report_id, procedure_id, period, count)
                    )

        cursor.execute("DELETE FROM daily_doctor_shifts WHERE daily_report_id=?", (daily_report_id,))
        for period in ['AM', 'PM']: # '夜間' は現在HTML側にselectがないため除外
            selected_doctors = request.form.getlist(f'doctors_{period}[]')
            # 空の文字列を除外してからintに変換
            selected_doctors = [int(doc_id) for doc_id in selected_doctors if doc_id.strip() != '']

            for doctor_id in selected_doctors:
                cursor.execute(
                    "INSERT INTO daily_doctor_shifts (daily_report_id, doctor_id, time_period) VALUES (?, ?, ?)",
                    (daily_report_id, doctor_id, period)
                )

        conn.commit()
        
        flash('保存しました！', 'success')
        return redirect(url_for('daily_report', year=year, month=month, day=day))

    conn.close()

    return render_template(
        'daily_report.html',
        year=year, month=month, day=day,
        total_points=total_points, total_sales=total_sales,
        shifts=shifts,
        procedures=procedures_master,
        procedures_records=procedures_records,
        doctors=doctors_master,
        daily_doctors=daily_doctors,
        message=message,
        date=report_date_obj,
        prev_day_year=prev_day_obj.year,
        prev_day_month=prev_day_obj.month,
        prev_day_day=prev_day_obj.day,
        next_day_year=next_day_obj.year,
        next_day_month=next_day_obj.month,
        next_day_day=next_day_obj.day,
        username=username,
        clinic_name=clinic_name
    )

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
            daily_report_id = daily_report_id[0]
            # ON DELETE CASCADE が設定されているので、関連データも自動で削除される
            cursor.execute("DELETE FROM daily_reports WHERE id=?", (daily_report_id,))
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
    user_id = session.get('user_id')
    username = "ゲスト"
    clinic_name = "未所属クリニック"

    conn = sqlite3.connect('daily_report.db')
    cursor = conn.cursor()
    if user_id:
        cursor.execute("SELECT username, clinic_id FROM users WHERE id=?", (user_id,))
        user_data = cursor.fetchone()
        if user_data:
            username = user_data[0]
            current_clinic_id = user_data[1]
            if current_clinic_id:
                cursor.execute("SELECT name FROM clinics WHERE id=?", (current_clinic_id,))
                clinic_data = cursor.fetchone()
                if clinic_data:
                    clinic_name = clinic_data[0]

    message = None

    if request.method == 'POST':
        if 'add_doctor_name' in request.form:
            doctor_name = request.form['add_doctor_name']
            try:
                cursor.execute("INSERT INTO doctors (clinic_id, name) VALUES (?, ?)", (clinic_id, doctor_name))
                conn.commit()
                message = f"ドクター「{doctor_name}」を追加しました！"
            except sqlite3.IntegrityError:
                message = f"ドクター「{doctor_name}」は既に存在します。"
        elif 'delete_doctor_id' in request.form:
            doctor_id = request.form['delete_doctor_id']
            cursor.execute("DELETE FROM doctors WHERE id=? AND clinic_id=?", (doctor_id, clinic_id))
            conn.commit()
            message = "ドクターを削除しました。"

        elif 'add_procedure_name' in request.form:
            procedure_name = request.form['add_procedure_name']
            try:
                cursor.execute("INSERT INTO procedures (clinic_id, name) VALUES (?, ?)", (clinic_id, procedure_name))
                conn.commit()
                message = f"処置「{procedure_name}」を追加しました！"
            except sqlite3.IntegrityError:
                message = f"処置「{procedure_name}」は既に存在します。"
        elif 'delete_procedure_id' in request.form:
            procedure_id = request.form['delete_procedure_id']
            cursor.execute("DELETE FROM procedures WHERE id=? AND clinic_id=?", (procedure_id, clinic_id))
            conn.commit()
            message = "処置を削除しました。"

    doctors = []
    procedures = []
    if clinic_id: # clinic_idがある場合のみマスタデータを取得
        cursor.execute("SELECT id, name FROM doctors WHERE clinic_id=?", (clinic_id,))
        doctors = cursor.fetchall()
        cursor.execute("SELECT id, name FROM procedures WHERE clinic_id=?", (clinic_id,))
        procedures = cursor.fetchall()

    conn.close()
    return render_template('manage_masters.html', doctors=doctors, procedures=procedures, message=message, username=username, clinic_name=clinic_name)

def get_monthly_data(year, month, clinic_id):
    conn = sqlite3.connect('daily_report.db')
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            SUM(dr.total_sales),
            SUM(dr.total_points),
            SUM(s.new_patients),
            SUM(s.returning_patients),
            SUM(s.total_patients)
        FROM daily_reports dr
        LEFT JOIN (
            SELECT daily_report_id,
                   SUM(new_patients) as new_patients,
                   SUM(returning_patients) as returning_patients,
                   SUM(total_patients) as total_patients
            FROM shifts GROUP BY daily_report_id
        ) s ON dr.id = s.daily_report_id
        WHERE dr.clinic_id = ? AND STRFTIME('%Y', dr.date) = ? AND STRFTIME('%m', dr.date) = ?
    """, (clinic_id, str(year), f"{month:02d}"))
    data = cursor.fetchone()
    conn.close()
    return {
        'total_sales': data[0] or 0,
        'total_points': data[1] or 0,
        'new_patients': data[2] or 0,
        'returning_patients': data[3] or 0,
        'total_patients': data[4] or 0
    }

def get_daily_trend_data(year, month, clinic_id):
    conn = sqlite3.connect('daily_report.db')
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            CAST(STRFTIME('%d', dr.date) AS INTEGER) as day,
            dr.total_sales,
            (SELECT SUM(total_patients) FROM shifts s WHERE s.daily_report_id = dr.id) as daily_total_patients
        FROM daily_reports dr
        WHERE dr.clinic_id = ? AND STRFTIME('%Y', dr.date) = ? AND STRFTIME('%m', dr.date) = ?
        ORDER BY day
    """, (clinic_id, str(year), f"{month:02d}"))
    days = []
    sales = []
    patients = []
    for row in cursor.fetchall():
        days.append(row[0])
        sales.append(row[1] or 0)
        patients.append(row[2] or 0)
    conn.close()
    return {'days': days, 'sales': sales, 'patients': patients}

@app.route('/monthly_report', methods=['GET', 'POST'])
@login_required
def monthly_report():
    clinic_id = session.get('clinic_id')
    user_id = session.get('user_id')
    username = "ゲスト"
    clinic_name = "未所属クリニック"

    # --- ユーザー・クリニック情報取得 (この部分は変更なし) ---
    conn = sqlite3.connect('daily_report.db')
    cursor = conn.cursor()
    if user_id:
        cursor.execute("SELECT username, clinic_id FROM users WHERE id=?", (user_id,))
        user_data = cursor.fetchone()
        if user_data:
            username = user_data[0]
            current_clinic_id = user_data[1]
            if current_clinic_id:
                cursor.execute("SELECT name FROM clinics WHERE id=?", (current_clinic_id,))
                clinic_data = cursor.fetchone()
                if clinic_data:
                    clinic_name = clinic_data[0]
    conn.close()
    # --- ここまで変更なし ---

    today = date.today()
    year = request.form.get('year', default=today.year, type=int)
    month = request.form.get('month', default=today.month, type=int)

    def get_summary_data(target_year, target_month, clinic_id):
        """サマリーデータをまとめて取得する内部関数"""
        if not clinic_id:
            return None

        # 基本データを取得
        base_data = get_monthly_data(target_year, target_month, clinic_id)
        # 処置件数を取得
        proc_counts = get_monthly_procedure_counts(target_year, target_month, clinic_id)
        # 営業日数を計算
        business_days = calculate_business_days(target_year, target_month)
        
        # 各指標を計算
        total_patients = base_data.get('total_patients', 0)
        total_points = base_data.get('total_points', 0)
        new_patients = base_data.get('new_patients', 0)
        
        avg_daily_patients = (total_patients / business_days) if business_days > 0 else 0
        new_patient_rate = (new_patients / total_patients * 100) if total_patients > 0 else 0
        avg_price = (total_points / total_patients * 10) if total_patients > 0 else 0
        
        summary = {
            'total_patients': total_patients,
            'returning_patients': base_data.get('returning_patients', 0),
            'business_days': business_days,
            'avg_daily_patients': avg_daily_patients,
            'new_patients': new_patients,
            'new_patient_rate': new_patient_rate,
            'total_points': total_points,
            'avg_price': avg_price,
            **proc_counts # 処置件数の辞書を展開して結合
        }
        return summary

    current_summary = get_summary_data(year, month, clinic_id)
    last_year_summary = get_summary_data(year - 1, month, clinic_id)
    trend_data = get_daily_trend_data(year, month, clinic_id) if clinic_id else {}
    
    year_options = range(today.year, today.year - 10, -1)
    
    return render_template(
        'monthly_report.html',
        year=year,
        month=month,
        year_options=year_options,
        current_data=current_summary,   # 新しいサマリーデータ
        last_year_data=last_year_summary, # 新しいサマリーデータ
        trend_data=trend_data,
        username=username,
        clinic_name=clinic_name
    )

def calculate_business_days(year, month):
    """営業日数を計算する（平日:1, 土曜:0.5, 日祝:0）"""
    jp_holidays = holidays.Japan()
    business_days = 0
    cal = calendar.Calendar()

    for day in cal.itermonthdates(year, month):
        # その月の日付のみを対象
        if day.month == month:
            # 日曜 (weekday==6) または祝日
            if day.weekday() == 6 or day in jp_holidays:
                continue
            # 土曜 (weekday==5)
            elif day.weekday() == 5:
                business_days += 0.5
            # 平日
            else:
                business_days += 1
    return business_days

def get_monthly_procedure_counts(year, month, clinic_id):
    """特定の処置項目の月間合計数を取得する"""
    conn = sqlite3.connect('daily_report.db')
    cursor = conn.cursor()
    
    # 取得したい処置リスト
    target_procedures = [
        '胃カメラ', '大腸カメラ（ポリペクなし）', '大腸カメラ（ポリペクあり）',
        'インフルエンザワクチン', '健診（自治体）'
    ]
    
    # プレースホルダを作成
    placeholders = ','.join('?' for name in target_procedures)
    
    query = f"""
        SELECT p.name, SUM(pr.count)
        FROM procedure_records pr
        JOIN procedures p ON pr.procedure_id = p.id
        JOIN daily_reports dr ON pr.daily_report_id = dr.id
        WHERE dr.clinic_id = ?
          AND STRFTIME('%Y', dr.date) = ?
          AND STRFTIME('%m', dr.date) = ?
          AND p.name IN ({placeholders})
        GROUP BY p.name
    """
    
    params = [clinic_id, str(year), f"{month:02d}"] + target_procedures
    cursor.execute(query, params)
    
    # 結果を辞書に格納
    counts = {name: 0 for name in target_procedures}
    for row in cursor.fetchall():
        counts[row[0]] = row[1]
        
    conn.close()
    return counts

if __name__ == '__main__':
    app.run(debug=True)