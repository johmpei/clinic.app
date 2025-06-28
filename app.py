from flask import Flask, render_template, request, redirect, url_for
import calendar, sqlite3
from datetime import date

app = Flask(__name__)

@app.route('/')
def index():
    today = date.today()
    year, month = today.year, today.month
    cal = calendar.Calendar(firstweekday=6)
    month_days = cal.monthdayscalendar(year, month)
    return render_template('index.html', year=year, month=month, month_days=month_days)

@app.route('/report/<int:year>/<int:month>/<int:day>', methods=['GET', 'POST'])
def daily_report(year, month, day):
    report_date = f"{year:04d}-{month:02d}-{day:02d}"
    clinic_id = 1  # MVPなので仮で1固定
    message = None

    # 必要なマスタを都度取得
    conn = sqlite3.connect('daily_report.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM procedures WHERE clinic_id=?", (clinic_id,))
    procedures = cursor.fetchall()
    conn.close()

    # まず既存の日報データを取得
    conn = sqlite3.connect('daily_report.db')
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, total_points, total_sales FROM daily_reports WHERE clinic_id=? AND date=?",
        (clinic_id, report_date)
    )
    result = cursor.fetchone()
    daily_report_id = result[0] if result else None
    total_points = result[1] if result else ''
    total_sales = result[2] if result else ''

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

    conn.close()

    # POSTなら保存処理
    if request.method == 'POST':
        total_points = request.form.get('total_points')
        total_sales = request.form.get('total_sales')

        conn = sqlite3.connect('daily_report.db')
        cursor = conn.cursor()

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
        for period in ['AM', 'PM', '夜間']:
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

        # 処置の保存（例。必要に応じて実装）
        for procedure in procedures:
            for period in ['AM', 'PM', '夜間']:
                count = request.form.get(f'procedure_{procedure[0]}_{period}', 0)
                # shift_procedure_recordsにINSERT/UPDATEするロジックをここに

        conn.commit()
        conn.close()
        message = "保存しました！"

        # 保存直後のデータを再取得して反映する
        # 再度DBを開いてshifts等も取得
        conn = sqlite3.connect('daily_report.db')
        cursor = conn.cursor()
        cursor.execute(
            "SELECT time_period, new_patients, returning_patients, total_patients FROM shifts WHERE daily_report_id=?",
            (daily_report_id,)
        )
        shifts_data = cursor.fetchall()
        shifts = {}
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
        conn.close()

    # テンプレートに渡す
    return render_template(
        'daily_report.html',
        year=year, month=month, day=day,
        total_points=total_points, total_sales=total_sales,
        shifts=shifts,
        procedures=procedures,
        message=message
    )

if __name__ == '__main__':
    app.run(debug=True)
