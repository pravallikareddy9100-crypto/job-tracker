from flask import Flask, render_template, request, redirect, url_for
import sqlite3

app = Flask(__name__)
DATABASE = 'jobs.db'

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL,
            role TEXT NOT NULL,
            date_applied TEXT,
            status TEXT DEFAULT 'Applied',
            notes TEXT
        )
    ''')
    conn.commit()
    conn.close()

@app.route('/')
def index():
    conn = get_db()
    jobs = conn.execute('SELECT * FROM jobs ORDER BY date_applied DESC').fetchall()
    conn.close()
    return render_template('index.html', jobs=jobs)

@app.route('/add', methods=['GET', 'POST'])
def add():
    if request.method == 'POST':
        company = request.form['company']
        role = request.form['role']
        date_applied = request.form['date_applied']
        status = request.form['status']
        notes = request.form['notes']
        conn = get_db()
        conn.execute('INSERT INTO jobs (company, role, date_applied, status, notes) VALUES (?, ?, ?, ?, ?)',
                     (company, role, date_applied, status, notes))
        conn.commit()
        conn.close()
        return redirect(url_for('index'))
    return render_template('add.html')

@app.route('/sync')
def sync():
    from gmail_sync import sync_emails
    count = sync_emails()
    return redirect(url_for('index'))

init_db()

if __name__ == '__main__':
    app.run(debug=True)