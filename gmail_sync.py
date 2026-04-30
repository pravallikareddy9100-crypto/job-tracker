import os
import sqlite3
import datetime
import json
import tempfile
from email.utils import parsedate_to_datetime
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
DATABASE = 'jobs.db'

def get_credentials_dict():
    creds_json = os.environ.get('GOOGLE_CREDENTIALS')
    if creds_json:
        return json.loads(creds_json)
    with open('credentials.json') as f:
        return json.load(f)

def get_redirect_uri():
    base = os.environ.get('RENDER_EXTERNAL_URL', 'http://localhost:5000')
    return f'{base}/gmail/callback'

verifier_store = {}

def get_auth_url():
    import secrets
    import hashlib
    import base64
    creds_dict = get_credentials_dict()
    flow = Flow.from_client_config(creds_dict, scopes=SCOPES, redirect_uri=get_redirect_uri())
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b'=').decode()
    auth_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        code_challenge=code_challenge,
        code_challenge_method='S256'
    )
    # Save verifier to database
    conn = get_db()
    conn.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)',
                 (f'verifier_{state}', code_verifier))
    conn.commit()
    conn.close()
    return auth_url, state

def exchange_code(code, state=None):
    import requests
    creds_dict = get_credentials_dict()
    client_info = creds_dict.get('web', creds_dict.get('installed', {}))
    data = {
        'code': code,
        'client_id': client_info['client_id'],
        'client_secret': client_info['client_secret'],
        'redirect_uri': get_redirect_uri(),
        'grant_type': 'authorization_code'
    }
    if state:
        verifier = get_verifier(state)
        if verifier:
            data['code_verifier'] = verifier
    response = requests.post('https://oauth2.googleapis.com/token', data=data)
    token_data = response.json()
    if 'access_token' not in token_data:
        print(f'Token error: {token_data}')
        return None
    token_file = {
        'access_token': token_data.get('access_token'),
        'refresh_token': token_data.get('refresh_token'),
        'token_uri': 'https://oauth2.googleapis.com/token',
        'client_id': client_info['client_id'],
        'client_secret': client_info['client_secret'],
        'scopes': SCOPES,
        'universe_domain': 'googleapis.com',
        'account': ''
    }
    return json.dumps(token_file)

def get_gmail_service(token_json=None):
    creds = None
    if token_json:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write(token_json)
            temp_path = f.name
        creds = Credentials.from_authorized_user_file(temp_path, SCOPES)
    elif os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build('gmail', 'v1', credentials=creds)

def detect_status(subject, snippet):
    text = (subject + ' ' + snippet).lower()
    rejected = ['unfortunately', 'regret to inform', 'not moving forward',
        'decided to move forward with other', 'not selected',
        'we will not be moving', 'position has been filled',
        'we have decided not', 'not be proceeding',
        'chose another candidate', 'not be moving forward', 'we regret']
    if any(k in text for k in rejected):
        return 'Rejected'
    interview = ['schedule an interview', 'schedule a call', 'phone screen',
        'video interview', 'technical interview', 'invite you to interview',
        'pleased to invite', 'move forward with an interview',
        'like to speak with you', 'interview invitation', 'selected for an interview']
    if any(k in text for k in interview):
        return 'Interview'
    applied = ['thank you for applying', 'thank you for your application',
        'received your application', 'application received',
        'application has been received', 'successfully applied',
        'we have received your application', 'thanks for applying',
        'thank you for submitting', 'application submitted']
    if any(k in text for k in applied):
        return 'Applied'
    return None

def get_db():
    conn = sqlite3.connect(DATABASE, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

def sync_emails(token_json=None):
    service = get_gmail_service(token_json)
    conn = get_db()
    new_count = 0
    processed = set()
    existing = conn.execute("SELECT notes FROM jobs WHERE role='Via Email'").fetchall()
    for row in existing:
        if row['notes']:
            parts = row['notes'].split(']')[0].replace('[', '').strip()
            processed.add(parts)
    page_token = None
    pages_scanned = 0
    max_pages = 3
    while pages_scanned < max_pages:
        params = {'userId': 'me', 'maxResults': 50, 'labelIds': ['INBOX']}
        if page_token:
            params['pageToken'] = page_token
        results = service.users().messages().list(**params).execute()
        messages = results.get('messages', [])
        if not messages:
            break
        for msg in messages:
            if msg['id'] in processed:
                continue
            try:
                data = service.users().messages().get(
                    userId='me', id=msg['id'], format='metadata',
                    metadataHeaders=['Subject', 'From', 'Date']).execute()
                headers = {h['name']: h['value'] for h in data['payload']['headers']}
                subject = headers.get('Subject', '')
                sender = headers.get('From', '')
                snippet = data.get('snippet', '')
                raw_date = headers.get('Date', '')
                try:
                    email_date = parsedate_to_datetime(raw_date).date().isoformat()
                except:
                    email_date = datetime.date.today().isoformat()
                status = detect_status(subject, snippet)
                if not status:
                    continue
                company = sender.split('<')[0].strip().strip('"')
                if not company:
                    company = sender
                processed.add(msg['id'])
                conn.execute(
                    'INSERT INTO jobs (company, role, date_applied, status, notes) VALUES (?, ?, ?, ?, ?)',
                    (company, 'Via Email', email_date, status, f'[{msg["id"]}] {subject[:80]}'))
                new_count += 1
            except Exception:
                continue
        page_token = results.get('nextPageToken')
        if not page_token:
            break
        pages_scanned += 1
    conn.commit()
    conn.close()
    return new_count