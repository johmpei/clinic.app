from flask import Flask, render_template, request, redirect, url_for, session, flash
import calendar, sqlite3
from datetime import date, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
import functools
import holidays

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

# 各ルートの保護 (login_required デコレータの定義をここに移動)
def login_required(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('ログインが必要です', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ★ここから追加・確認してください★
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
            # クリニックを登録
            cursor.execute("INSERT INTO clinics (name) VALUES (?)", (clinic_name,))
            clinic_id = cursor.lastrowid
            
            # ユーザーを登録 (clinic_idと紐付け)
            cursor.execute("INSERT INTO users (username, password_hash, clinic_id) VALUES (?, ?, ?)",
                           (username, hashed_password, clinic_id))
            conn.commit()
            flash('アカウントが作成されました！ログインしてください。', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            conn.rollback()
            flash('そのユーザー名は既に存在します。', 'danger')
        except Exception as e:
            conn.rollback()
            flash(f'登録中にエラーが発生しました: {e}', 'danger')
        finally:
            conn.close()
    return render_template('register.html')
# ★ここまで追加・確認してください★


@app.route('/')
@app.route('/<int:year>/<int:month>') # /YYYY/MM の形式のURLも受け入れる
@login_required
def index(year=None, month=None): # URLからyearとmonthを受け取る（デフォルトはNone）
    today = date.today()

    # URLにyearやmonthが指定されていない場合、または不正な値の場合、今日の日付をデフォルトとする
    if year is None or not isinstance(year, int):
        year = today.year
    if month is None or not isinstance(month, int) or not (1 <= month <= 12):
        month = today.month

    # 月の移動ロジックを修正: 日数ではなく月を直接計算
    # 次の月を計算
    if month == 12:
        next_month = 1
        next_year = year + 1
    else:
        next_month = month + 1
        next_year = year

    # 前の月を計算
    if month == 1:
        prev_month = 12
        prev_year = year - 1
    else:
        prev_month = month - 1
        prev_year = year

    # カレンダーのデータ準備
    cal = calendar.Calendar(firstweekday=6) # 週の始まりを日曜日に設定 (0=月曜, 6=日曜)
    month_days = cal.monthdayscalendar(year, month)
    clinic_id = session.get('clinic_id') # 現在ログインしているクリニックのIDを取得

    # 日報サマリーの取得
    daily_summaries = {}
    conn = sqlite3.connect('daily_report.db')
    cursor = conn.cursor()

    # 特定の年月の売上と患者数を集計
    cursor.execute("""
        SELECT
            strftime('%d', DR.date) as day,
            SUM(S.total_patients) as total_patients,
            DR.total_points -- total_salesをtotal_pointsに変更
        FROM daily_reports DR
        LEFT JOIN shifts S ON DR.id = S.daily_report_id
        WHERE DR.clinic_id = ? AND strftime('%Y', DR.date) = ? AND strftime('%m', DR.date) = ?
        GROUP BY DR.date
    """, (clinic_id, str(year), f"{month:02d}")) # 月を2桁のゼロ埋め文字列にフォーマット

    for row in cursor.fetchall():
        day_str, total_patients, total_points = row # total_salesをtotal_pointsに変更
        daily_summaries[int(day_str)] = {
            'total_patients': total_patients if total_patients is not None else 0,
            'total_points': total_points if total_points is not None else 0 # total_salesをtotal_pointsに変更
        }
    conn.close()

    # 日本の祝日を取得
    jp_holidays = holidays.Japan()

    # テンプレートをレンダリングして表示
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
        date_class=date # datetime.dateオブジェクトをテンプレートで使えるように渡す
    )
# ★ここまでdef index():関数の新しい内容に置き換えてください★


@app.route('/report/<int:year>/<int:month>/<int:day>', methods=['GET', 'POST'])
@login_required
def daily_report(year, month, day):
    report_date_obj = date(year, month, day) # 現在の日付オブジェクト
    report_date = report_date_obj.strftime("%Y-%m-%d") # データベース検索用の文字列

    # 前の日と次の日の計算
    prev_day_obj = report_date_obj - timedelta(days=1)
    next_day_obj = report_date_obj + timedelta(days=1)

    clinic_id = session.get('clinic_id')
    if not clinic_id:
        flash('クリニック情報が見つかりません。再ログインしてください。', 'danger')
        return redirect(url_for('login'))

    message = None

    conn = sqlite3.connect('daily_report.db')
    cursor = conn.cursor()

    # 必要なマスタを都度取得
    cursor.execute("SELECT id, name FROM procedures WHERE clinic_id=?", (clinic_id,))
    procedures_master = cursor.fetchall()

    cursor.execute("SELECT id, name FROM doctors WHERE clinic_id=?", (clinic_id,))
    doctors_master = cursor.fetchall()

    # まず既存の日報データを取得
    cursor.execute(
        "SELECT id, total_points, total_sales FROM daily_reports WHERE clinic_id=? AND date=?",
        (clinic_id, report_date)
    )
    result = cursor.fetchone()
    daily_report_id = result[0] if result else None
    total_points = result[1] if result else 0
    total_sales = result[2] if result else 0

    # shiftsデータも取得
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

    # procedures_recordsデータを取得
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

    # daily_doctor_shiftsデータを取得
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

    # POSTなら保存処理
    if request.method == 'POST':
        total_points = request.form.get('total_points', 0)
        total_sales = request.form.get('total_sales', 0)

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
            new_patients = request.form.get(f'new_{period}', 0)
            returning_patients = request.form.get(f'return_{period}', 0)
            total_patients = request.form.get(f'total_{period}', 0)

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
                count = request.form.get(f'procedure_{procedure_id}_{period}', 0)

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
            selected_doctors = [int(doc_id) for doc_id in selected_doctors if doc_id.strip() != '']

            for doctor_id in selected_doctors:
                cursor.execute(
                    "INSERT INTO daily_doctor_shifts (daily_report_id, doctor_id, time_period) VALUES (?, ?, ?)",
                    (daily_report_id, doctor_id, period)
                )

        conn.commit()
        message = "保存しました！"

        # 保存直後のデータを再取得して反映する (これは変更なしでOK)
        cursor.execute(
            "SELECT total_points, total_sales FROM daily_reports WHERE clinic_id=? AND date=?",
            (clinic_id, report_date)
        )
        result_after_save = cursor.fetchone()
        total_points = result_after_save[0] if result_after_save else 0
        total_sales = result_after_save[1] if result_after_save else 0

        cursor.execute(
            "SELECT time_period, new_patients, returning_patients, total_patients FROM shifts WHERE daily_report_id=?",
            (daily_report_id,)
        )
        shifts_data_after_save = cursor.fetchall()
        shifts = {}
        for row in shifts_data_after_save:
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
        cursor.execute(
            "SELECT procedure_id, time_period, count FROM procedure_records WHERE daily_report_id=?",
            (daily_report_id,)
        )
        proc_records_data_after_save = cursor.fetchall()
        for row in proc_records_data_after_save:
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
        cursor.execute(
            "SELECT doctor_id, time_period FROM daily_doctor_shifts WHERE daily_report_id=?",
            (daily_report_id,)
        )
        doctor_shifts_data_after_save = cursor.fetchall()
        for doctor_id, time_period in doctor_shifts_data_after_save:
            if time_period in daily_doctors:
                daily_doctors[time_period].append(doctor_id)
        for period in ['AM', 'PM', '夜間']:
            if period not in daily_doctors:
                daily_doctors[period] = []

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
        date=report_date_obj, # 現在の日付オブジェクト
        prev_day_year=prev_day_obj.year, # 前の日の年
        prev_day_month=prev_day_obj.month, # 前の日の月
        prev_day_day=prev_day_obj.day, # 前の日
        next_day_year=next_day_obj.year, # 次の日の年
        next_day_month=next_day_obj.month, # 次の日の月
        next_day_day=next_day_obj.day # 次の日
    )


#日報データ削除 (変更なし)
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
            cursor.execute("DELETE FROM shifts WHERE daily_report_id=?", (daily_report_id,))
            cursor.execute("DELETE FROM procedure_records WHERE daily_report_id=?", (daily_report_id,))
            cursor.execute("DELETE FROM daily_doctor_shifts WHERE daily_report_id=?", (daily_report_id,))
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

#医者とかの登録 (変更なし)
@app.route('/manage_masters', methods=['GET', 'POST'])
@login_required
def manage_masters():
    clinic_id = session.get('clinic_id')
    conn = sqlite3.connect('daily_report.db')
    cursor = conn.cursor()
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

    cursor.execute("SELECT id, name FROM doctors WHERE clinic_id=?", (clinic_id,))
    doctors = cursor.fetchall()
    cursor.execute("SELECT id, name FROM procedures WHERE clinic_id=?", (clinic_id,))
    procedures = cursor.fetchall()

    conn.close()
    return render_template('manage_masters.html', doctors=doctors, procedures=procedures, message=message)


# 月次レポートのデータを取得するヘルパー関数
def get_monthly_data(year, month, clinic_id):
    """指定された年月の集計データを取得する"""
    conn = sqlite3.connect('daily_report.db')
    cursor = conn.cursor()
    # SQLクエリ: total_sales, total_points, 各患者数の合計を取得
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
    # データがない場合は0を返す
    return {
        'total_sales': data[0] or 0,
        'total_points': data[1] or 0,
        'new_patients': data[2] or 0,
        'returning_patients': data[3] or 0,
        'total_patients': data[4] or 0
    }
# 日次データをグラフ用に取得するヘルパー関数
def get_daily_trend_data(year, month, clinic_id):
    """グラフ用に日ごとの売上と患者数を取得する"""
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
    today = date.today()
    # フォームから年月の指定がなければ、現在の年月を使用
    year = request.form.get('year', default=today.year, type=int)
    month = request.form.get('month', default=today.month, type=int)
    # ① 当月の集計データ
    current_month_data = get_monthly_data(year, month, clinic_id)
    # ② 前年同月の集計データ
    last_year_data = get_monthly_data(year - 1, month, clinic_id)
    # グラフ用の日次推移データ
    trend_data = get_daily_trend_data(year, month, clinic_id)
    # テンプレートに渡すための年リスト (過去10年分など)
    year_options = range(today.year, today.year - 10, -1)
    return render_template(
        'monthly_report.html',
        year=year,
        month=month,
        year_options=year_options,
        current_data=current_month_data,
        last_year_data=last_year_data,
        trend_data=trend_data # グラフ用データを渡す
    )

if __name__ == '__main__':
    app.run(debug=True)