import os
import sqlite3
import datetime
from email.utils import parsedate_to_datetime
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
DATABASE = 'jobs.db'

def get_gmail_service():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            import json
            import tempfile
            creds_json = os.environ.get('GOOGLE_CREDENTIALS')
            if creds_json:
                with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                    f.write(creds_json)
                    temp_path = f.name
                flow = InstalledAppFlow.from_client_secrets_file(temp_path, SCOPES)
            else:
                flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return build('gmail', 'v1', credentials=creds)

def detect_status(subject, snippet):
    text = (subject + ' ' + snippet).lower()

    rejected = [
        'unfortunately', 'regret to inform', 'not moving forward',
        'decided to move forward with other', 'not selected',
        'we will not be moving', 'position has been filled',
        'we have decided not', 'not be proceeding',
        'chose another candidate', 'other applicants',
        'not be moving forward', 'we regret'
    ]
    if any(k in text for k in rejected):
        return 'Rejected'

    interview = [
        'schedule an interview', 'schedule a call', 'schedule time with',
        'phone screen', 'video interview', 'technical interview',
        'want to set up a', 'invite you to interview',
        'pleased to invite', 'move forward with an interview',
        'like to speak with you', 'would like to connect',
        'interview invitation', 'hiring manager would like to',
        'next step is', 'advance you to', 'selected for an interview'
    ]
    if any(k in text for k in interview):
        return 'Interview'

    applied = [
        'thank you for applying', 'thank you for your application',
        'received your application', 'application received',
        'application has been received', 'successfully applied',
        'we have received your application', 'your application to',
        'thanks for applying', 'thank you for your interest in joining',
        'thank you for submitting', 'application submitted',
        'we got your application', 'you have applied',
        'thank you for apply', 'thank you for expressing'
    ]
    if any(k in text for k in applied):
        return 'Applied'

    return None

def get_db():
    conn = sqlite3.connect(DATABASE, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

def sync_emails():
    service = get_gmail_service()
    conn = get_db()
    new_count = 0
    processed = set()

    # Get existing message IDs to avoid duplicates
    existing = conn.execute("SELECT notes FROM jobs WHERE role='Via Email'").fetchall()
    for row in existing:
        if row['notes']:
            parts = row['notes'].split(']')[0].replace('[','').strip()
            processed.add(parts)

    # Scan inbox page by page
    page_token = None
    pages_scanned = 0
    max_pages = 20  # scan up to 2000 emails

    while pages_scanned < max_pages:
        params = {
            'userId': 'me',
            'maxResults': 100,
            'labelIds': ['INBOX']
        }
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
                    userId='me',
                    id=msg['id'],
                    format='metadata',
                    metadataHeaders=['Subject', 'From', 'Date']
                ).execute()

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
                    (company, 'Via Email', email_date, status, f'[{msg["id"]}] {subject[:80]}')
                )
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