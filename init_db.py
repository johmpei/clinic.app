# init_db.py
import sqlite3
from werkzeug.security import generate_password_hash # パスワードハッシュ化用

def init_db():
    conn = sqlite3.connect('daily_report.db')
    cursor = conn.cursor()

    # clinics テーブル（複数のクリニックを扱う場合）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS clinics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )
    ''')

    # users テーブル
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            clinic_id INTEGER,
            FOREIGN KEY (clinic_id) REFERENCES clinics(id)
        )
    ''')

    # daily_reports テーブル
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clinic_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            total_points INTEGER DEFAULT 0,
            total_sales INTEGER DEFAULT 0,
            FOREIGN KEY (clinic_id) REFERENCES clinics(id),
            UNIQUE(clinic_id, date)
        )
    ''')

    # shifts テーブル
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS shifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            daily_report_id INTEGER NOT NULL,
            time_period TEXT NOT NULL, -- 'AM', 'PM', '夜間'
            new_patients INTEGER DEFAULT 0,
            returning_patients INTEGER DEFAULT 0,
            total_patients INTEGER DEFAULT 0,
            FOREIGN KEY (daily_report_id) REFERENCES daily_reports(id),
            UNIQUE(daily_report_id, time_period)
        )
    '''
    )

    # procedures テーブル
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS procedures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clinic_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            FOREIGN KEY (clinic_id) REFERENCES clinics(id),
            UNIQUE(clinic_id, name)
        )
    '''
    )

    # procedure_records テーブル
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS procedure_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            daily_report_id INTEGER NOT NULL,
            procedure_id INTEGER NOT NULL,
            time_period TEXT NOT NULL, -- 'AM', 'PM', '夜間'
            count INTEGER DEFAULT 0,
            FOREIGN KEY (daily_report_id) REFERENCES daily_reports(id),
            FOREIGN KEY (procedure_id) REFERENCES procedures(id),
            UNIQUE(daily_report_id, procedure_id, time_period)
        )
    ''')

    # doctors テーブル
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS doctors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clinic_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            FOREIGN KEY (clinic_id) REFERENCES clinics(id),
            UNIQUE(clinic_id, name)
        )
    ''')

    # daily_doctor_shifts テーブル
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_doctor_shifts (
            daily_report_id INTEGER NOT NULL,
            doctor_id INTEGER NOT NULL,
            time_period TEXT NOT NULL, -- 'AM', 'PM', '夜間'
            FOREIGN KEY (daily_report_id) REFERENCES daily_reports(id),
            FOREIGN KEY (doctor_id) REFERENCES doctors(id),
            PRIMARY KEY (daily_report_id, doctor_id, time_period)
        )
    ''')

    # サンプルデータの挿入 (オプション: 初回のみ実行される)
    cursor.execute("INSERT OR IGNORE INTO clinics (name) VALUES (?)", ("サンプルクリニック",))
    
    # サンプルユーザーの追加（パスワードはハッシュ化）
    # 'password123' をハッシュ化したもの
    hashed_password = generate_password_hash('password123', method='pbkdf2:sha256')
    cursor.execute("INSERT OR IGNORE INTO users (username, password_hash, clinic_id) VALUES (?, ?, ?)", ("user1", hashed_password, 1))

    cursor.execute("INSERT OR IGNORE INTO doctors (clinic_id, name) VALUES (?, ?)", (1, "山田太郎"))
    cursor.execute("INSERT OR IGNORE INTO doctors (clinic_id, name) VALUES (?, ?)", (1, "田中花子"))
    cursor.execute("INSERT OR IGNORE INTO procedures (clinic_id, name) VALUES (?, ?)", (1, "胃カメラ"))
    cursor.execute("INSERT OR IGNORE INTO procedures (clinic_id, name) VALUES (?, ?)", (1, "レントゲン"))


    conn.commit()
    conn.close()

if __name__ == '__main__':
    init_db()
    print("Database initialized successfully!")