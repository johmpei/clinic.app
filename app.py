from flask import Flask, render_template, request, redirect, url_for, session, flash # flashを追加
import calendar, sqlite3 
from datetime import date
from werkzeug.security import generate_password_hash, check_password_hash # パスワードハッシュ化用
import functools


app = Flask(__name__)
app.secret_key = 'your_secret_key_here' # セッション管理のためのシークレットキー。本番環境ではランダムな強い文字列を設定

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

        if user and check_password_hash(user[1], password): # パスワードの検証
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

# 各ルートの保護
def login_required(f):
    @functools.wraps(f) # デコレータを使う場合は functools をインポート
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('ログインが必要です', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# 例: index ルートに適用
# from functools import wraps
# @app.route('/')
# @login_required
# def index():
#     # ...
#     pass

# ... (他のルートにも適用) ...

# ユーザー登録ルート (テスト用、本番では管理画面に)
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        clinic_id = request.form['clinic_id'] # どのクリニックに紐づけるか
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')

        conn = sqlite3.connect('daily_report.db')
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO users (username, password_hash, clinic_id) VALUES (?, ?, ?)",
                           (username, hashed_password, clinic_id))
            conn.commit()
            flash('ユーザー登録が完了しました！', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('そのユーザー名は既に使われています。', 'danger')
        finally:
            conn.close()
    
    # 登録時に選択できるようにクリニックの一覧も渡す
    conn = sqlite3.connect('daily_report.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM clinics")
    clinics = cursor.fetchall()
    conn.close()
    return render_template('register.html', clinics=clinics)


@app.route('/')
@login_required # ログイン必須に
def index():
    today = date.today()
    year, month = today.year, today.month
    cal = calendar.Calendar(firstweekday=6)
    month_days = cal.monthdayscalendar(year, month)
    clinic_id = session.get('clinic_id') # セッションからクリニックIDを取得

    daily_summaries = {}
    conn = sqlite3.connect('daily_report.db')
    cursor = conn.cursor()
    # 月全体のサマリーデータを効率的に取得
    # LEFT JOIN を使うことで、日報がない日も結果に含まれるようにする
    cursor.execute("""
        SELECT 
            strftime('%d', DR.date) as day, 
            SUM(S.total_patients) as total_patients, 
            DR.total_sales 
        FROM daily_reports DR
        LEFT JOIN shifts S ON DR.id = S.daily_report_id
        WHERE DR.clinic_id = ? AND strftime('%Y', DR.date) = ? AND strftime('%m', DR.date) = ?
        GROUP BY DR.date
    """, (clinic_id, str(year), f"{month:02d}"))
    
    for row in cursor.fetchall():
        day_str, total_patients, total_sales = row
        daily_summaries[int(day_str)] = {
            'total_patients': total_patients if total_patients is not None else 0,
            'total_sales': total_sales if total_sales is not None else 0
        }
    conn.close()

    return render_template(
        'index.html', 
        year=year, 
        month=month, 
        month_days=month_days, 
        daily_summaries=daily_summaries
    )


@app.route('/report/<int:year>/<int:month>/<int:day>', methods=['GET', 'POST'])
def daily_report(year, month, day):
    report_date = f"{year:04d}-{month:02d}-{day:02d}"
    clinic_id = 1  # MVPなので仮で1固定
    message = None

    conn = sqlite3.connect('daily_report.db')
    cursor = conn.cursor()

    # 必要なマスタを都度取得
    cursor.execute("SELECT id, name FROM procedures WHERE clinic_id=?", (clinic_id,))
    procedures_master = cursor.fetchall() # 'procedures'と名前が重複しないように変更

    # まず既存の日報データを取得
    cursor.execute(
        "SELECT id, total_points, total_sales FROM daily_reports WHERE clinic_id=? AND date=?",
        (clinic_id, report_date)
    )
    result = cursor.fetchone()
    daily_report_id = result[0] if result else None
    total_points = result[1] if result else 0 # Noneの場合に備えて初期値を0に
    total_sales = result[2] if result else 0   # Noneの場合に備えて初期値を0に

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
    # なければ0を入れておく
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
    
    # なければ0を入れておく
    for proc_id, _ in procedures_master:
        if proc_id not in procedures_records:
            procedures_records[proc_id] = {}
        for period in ['AM', 'PM', '夜間']: # '夜間'はHTMLにないので注意
            if period not in procedures_records[proc_id]:
                procedures_records[proc_id][period] = 0

    # POSTなら保存処理
    if request.method == 'POST':
        total_points = request.form.get('total_points', 0)
        total_sales = request.form.get('total_sales', 0)

        # daily_reportsを保存・取得
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

        # shiftsテーブルの保存
        for period in ['AM', 'PM']: # '夜間'はdaily_report.htmlのフォームにないので外す
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

        # 処置の保存
        for procedure_id, _ in procedures_master:
            for period in ['AM', 'PM']: # '夜間'はdaily_report.htmlのフォームにないので外す
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

        conn.commit()
        message = "保存しました！"

        # 保存直後のデータを再取得して反映する (shiftsは既に実装済み、procedures_recordsも同様に再取得)
        # daily_reportsの再取得
        cursor.execute(
            "SELECT total_points, total_sales FROM daily_reports WHERE clinic_id=? AND date=?",
            (clinic_id, report_date)
        )
        result_after_save = cursor.fetchone()
        total_points = result_after_save[0] if result_after_save else 0
        total_sales = result_after_save[1] if result_after_save else 0

        # shiftsデータの再取得
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
        
        # procedures_recordsデータの再取得
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
        
        # なければ0を入れておく
        for proc_id, _ in procedures_master:
            if proc_id not in procedures_records:
                procedures_records[proc_id] = {}
            for period in ['AM', 'PM', '夜間']:
                if period not in procedures_records[proc_id]:
                    procedures_records[proc_id][period] = 0

    conn.close() # POST/GETに関わらず最後に閉じる

    # テンプレートに渡す
    return render_template(
        'daily_report.html',
        year=year, month=month, day=day,
        total_points=total_points, total_sales=total_sales,
        shifts=shifts,
        procedures=procedures_master, # procedures_masterを渡す
        procedures_records=procedures_records, # 新しく追加
        message=message
    )




if __name__ == '__main__':
    app.run(debug=True)