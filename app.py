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