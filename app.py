
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
@login_required
def daily_report(year, month, day):
    report_date = f"{year:04d}-{month:02d}-{day:02d}"
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
    doctors_master = cursor.fetchall() # ここを all_doctors とかにしても良い

    # まず既存の日報データを取得
    cursor.execute(
        "SELECT id, total_points, total_sales FROM daily_reports WHERE clinic_id=? AND date=?",
        (clinic_id, report_date)
    )
    result = cursor.fetchone()
    daily_report_id = result[0] if result else None
    total_points = result[1] if result else 0
    total_sales = result[2] if result else 0

    # shiftsデータも取得 (変更なし)
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

    # procedures_recordsデータを取得 (変更なし)
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
    # ここは、保存されている doctor_id のリストとして取得します
    daily_doctors = {'AM': [], 'PM': [], '夜間': []} # 初期化
    if daily_report_id:
        cursor.execute(
            "SELECT doctor_id, time_period FROM daily_doctor_shifts WHERE daily_report_id=?",
            (daily_report_id,)
        )
        doctor_shifts_data = cursor.fetchall()
        for doctor_id, time_period in doctor_shifts_data:
            if time_period in daily_doctors: # 念のため存在チェック
                daily_doctors[time_period].append(doctor_id)

    # POSTなら保存処理
    if request.method == 'POST':
        total_points = request.form.get('total_points', 0)
        total_sales = request.form.get('total_sales', 0)

        # daily_reportsを保存・取得 (変更なし)
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

        # shiftsテーブルの保存 (変更なし)
        for period in ['AM', 'PM']:
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

        # 処置の保存 (変更なし)
        for procedure_id, _ in procedures_master:
            for period in ['AM', 'PM']:
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

        # daily_doctor_shiftsの保存 (ここを変更)
        cursor.execute("DELETE FROM daily_doctor_shifts WHERE daily_report_id=?", (daily_report_id,))
        for period in ['AM', 'PM']:
            # name="doctors_{{ period }}[]" なので、getlistで受け取る
            selected_doctors = request.form.getlist(f'doctors_{period}[]')
            # 空の選択肢が送られてくることがあるので、フィルタリング
            selected_doctors = [int(doc_id) for doc_id in selected_doctors if doc_id.strip() != '']
            
            for doctor_id in selected_doctors:
                cursor.execute(
                    "INSERT INTO daily_doctor_shifts (daily_report_id, doctor_id, time_period) VALUES (?, ?, ?)",
                    (daily_report_id, doctor_id, period)
                )
        
        conn.commit()
        message = "保存しました！"

        # 保存直後のデータを再取得して反映する (これは既存ロジックなので変更なしでOK)
        # ただし、daily_doctors の再取得ロジックは上記のGETリクエスト時のものと同じにする
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

        # daily_doctor_shiftsデータの再取得 (ここも変更)
        daily_doctors = {'AM': [], 'PM': [], '夜間': []} # 初期化
        cursor.execute(
            "SELECT doctor_id, time_period FROM daily_doctor_shifts WHERE daily_report_id=?",
            (daily_report_id,)
        )
        doctor_shifts_data_after_save = cursor.fetchall()
        for doctor_id, time_period in doctor_shifts_data_after_save:
            if time_period in daily_doctors:
                daily_doctors[time_period].append(doctor_id)

    conn.close()

    # テンプレートに渡す
    return render_template(
        'daily_report.html',
        year=year, month=month, day=day,
        total_points=total_points, total_sales=total_sales,
        shifts=shifts,
        procedures=procedures_master,
        procedures_records=procedures_records,
        doctors=doctors_master,        # ドクターマスタ
        daily_doctors=daily_doctors,  # 選択されたドクター
        message=message
    )



#日報データ削除
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
            # 関連するデータを削除
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

#医者とかの登録
@app.route('/manage_masters', methods=['GET', 'POST'])
@login_required
def manage_masters():
    clinic_id = session.get('clinic_id')
    conn = sqlite3.connect('daily_report.db')
    cursor = conn.cursor()
    message = None

    if request.method == 'POST':
        # ドクターの追加/削除
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
        
        # 処置の追加/削除（同様に実装）
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
        
        # TODO: 編集機能も追加する
            
    # 現在のドクターと処置マスタを取得
    cursor.execute("SELECT id, name FROM doctors WHERE clinic_id=?", (clinic_id,))
    doctors = cursor.fetchall()
    cursor.execute("SELECT id, name FROM procedures WHERE clinic_id=?", (clinic_id,))
    procedures = cursor.fetchall()

    conn.close()
    return render_template('manage_masters.html', doctors=doctors, procedures=procedures, message=message)

# index.html などに管理画面へのリンクを追加:
# <p><a href="{{ url_for('manage_masters') }}">マスタ管理</a></p>



if __name__ == '__main__':
    app.run(debug=True)