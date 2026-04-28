from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
import os

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-prod')
DATABASE = 'jobs.db'

def get_db():
    conn = sqlite3.connect(DATABASE, timeout=10)
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
@app.route('/gmail/connect')
def gmail_connect():
    from gmail_sync import get_auth_url
    auth_url, state = get_auth_url()
    session['oauth_state'] = state
    return redirect(auth_url)

@app.route('/gmail/callback')
def gmail_callback():
    from gmail_sync import exchange_code
    code = request.args.get('code')
    state = request.args.get('state')
    if code:
        exchange_code(code, state)
    return redirect(url_for('index'))

@app.route('/gmail/disconnect')
def gmail_disconnect():
    if os.path.exists('token.json'):
        os.remove('token.json')
    return redirect(url_for('index'))
@app.route('/sync')
def sync():
    import threading
    from gmail_sync import sync_emails
    def run_sync():
        try:
            sync_emails()
        except Exception as e:
            print(f'Sync error: {e}')
    thread = threading.Thread(target=run_sync)
    thread.daemon = True
    thread.start()
    return redirect(url_for('index'))

init_db()

if __name__ == '__main__':
    app.run(debug=True)