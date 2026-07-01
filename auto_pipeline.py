"""
HTML → Video Auto Pipeline
============================
Google Drive → Convert 1 HTML → Publish to social media

Logic (mirrors Valeria Solverde):
  1. Try to fetch ONE new (unpublished) HTML file from Drive
  2. If none available → weighted random repost of already-published HTML
  3. Pick random audio, convert to video, publish, mark as processed
"""

import os
import sys
import json
import random
import subprocess
import tempfile
import shutil
import time
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

load_dotenv()

# ── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_PATH = os.path.join(BASE_DIR, 'upload')
OUTPUT_DIR = os.getenv('OUTPUT_DIR', os.path.join(BASE_DIR, 'Processed_Videos'))
LOG_FILE = os.path.join(BASE_DIR, 'published_html.json')

# ── Google Drive ───────────────────────────────────────────────────────────
HTML_DRIVE_FOLDER_ID  = os.getenv('HTML_DRIVE_FOLDER_ID')
AUDIO_DRIVE_FOLDER_ID = os.getenv('AUDIO_DRIVE_FOLDER_ID')
SERVICE_ACCOUNT_KEY   = os.getenv('GOOGLE_SERVICE_ACCOUNT_KEY')

# ── Video ──────────────────────────────────────────────────────────────────
MIN_DUR = int(os.getenv('MIN_VIDEO_DURATION', '12'))
MAX_DUR = int(os.getenv('MAX_VIDEO_DURATION', '30'))


# ── Published log (mirrors Valeria Solverde's published_videos.json) ───────
def get_published_history():
    """Full publishing history with repost counts."""
    if not os.path.exists(LOG_FILE):
        return []
    try:
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, ValueError):
        return []


def get_published_html_names():
    """List of already published HTML file names."""
    return [entry.get('file', '') for entry in get_published_history()]


def get_repost_counts():
    """Count how many times each HTML has been posted."""
    counts = {}
    for entry in get_published_history():
        fname = entry.get('file', '')
        counts[fname] = counts.get(fname, 0) + 1
    return counts


def mark_published(file_name, drive_id):
    history = get_published_history()
    history.append({
        'file': file_name,
        'drive_id': drive_id,
        'date': datetime.now().isoformat()
    })
    with open(LOG_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=2)


# ── Google Drive API ───────────────────────────────────────────────────────
def get_drive_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    if not SERVICE_ACCOUNT_KEY:
        raise ValueError('GOOGLE_SERVICE_ACCOUNT_KEY not set')

    if os.path.exists(SERVICE_ACCOUNT_KEY):
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_KEY, scopes=['https://www.googleapis.com/auth/drive.readonly'])
    else:
        creds = service_account.Credentials.from_service_account_info(
            json.loads(SERVICE_ACCOUNT_KEY), scopes=['https://www.googleapis.com/auth/drive.readonly'])

    return build('drive', 'v3', credentials=creds)


def fetch_one_html(service, allow_repost=False):
    """
    Fetch ONE HTML file from Google Drive.

    Args:
        allow_repost: If True and no new files exist, select a random
                      already-published file (weighted by repost count).
                      If False, only fetch new (unpublished) files.

    Returns:
        dict with {'path': ..., 'name': ..., 'id': ...} or None
    """
    published = set(get_published_html_names())
    print(f'  Already published: {len(published)} file(s)')

    # List all HTML files from Drive
    all_files = []
    page_token = None
    while True:
        result = service.files().list(
            q=f"'{HTML_DRIVE_FOLDER_ID}' in parents and mimeType='text/html' and trashed=false",
            fields='nextPageToken, files(id, name, size)',
            orderBy='createdTime desc',
            pageSize=100,
            pageToken=page_token
        ).execute()
        all_files.extend(result.get('files', []))
        page_token = result.get('nextPageToken')
        if not page_token:
            break

    if not all_files:
        print('  No HTML files found in Drive folder.')
        return None

    print(f'  Total HTML files in Drive: {len(all_files)}')

    # ── Try to find a NEW (unpublished) file ────────────────────────────────
    for f in all_files:
        if f['name'] not in published:
            print(f'  ✅ Found new: {f["name"]}')
            return f

    # ── All published — repost mode ──────────────────────────────────────────
    if not allow_repost:
        print('  ✅ All files already published (no repost mode).')
        return None

    print('  No new files. Repost mode: weighted random selection...')

    repost_counts = get_repost_counts()
    choices = []
    weights = []
    for f in all_files:
        count = repost_counts.get(f['name'], 0)
        # Weight: 0 posts=1000, 1 post=333, 2 posts=111, etc.
        weight = max(1, 1000 // (3 ** min(count, 6)))
        choices.append(f)
        weights.append(weight)

    selected = random.choices(choices, weights=weights, k=1)[0]
    post_count = repost_counts.get(selected['name'], 0)
    print(f'  🎲 Repost (posted {post_count}x before): {selected["name"]}')
    return selected


def download_file(service, file_id, dest_path):
    from googleapiclient.http import MediaIoBaseDownload
    request = service.files().get_media(fileId=file_id)
    with open(dest_path, 'wb') as f:
        downloader = MediaIoBaseDownload(f, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()


def fetch_one_audio(service):
    """Pick ONE random MP3 from the audio Drive folder."""
    all_audio = []
    page_token = None
    while True:
        result = service.files().list(
            q=f"'{AUDIO_DRIVE_FOLDER_ID}' in parents and trashed=false",
            fields='nextPageToken, files(id, name)',
            pageSize=100,
            pageToken=page_token
        ).execute()
        all_audio.extend(result.get('files', []))
        page_token = result.get('nextPageToken')
        if not page_token:
            break

    # Filter to MP3s
    mp3s = [f for f in all_audio if f['name'].lower().endswith('.mp3')]
    if not mp3s:
        print('  No MP3 files in audio folder.')
        return None

    chosen = random.choice(mp3s)
    print(f'  🎵 Audio: {chosen["name"]}')
    return chosen


# ── Conversion ─────────────────────────────────────────────────────────────
def convert_html_to_video(html_path, audio_path, output_path):
    js_path = os.path.join(BASE_DIR, 'html2video.js')
    if not os.path.exists(js_path):
        print(f'  ❌ html2video.js not found')
        return False

    cmd = ['node', js_path, html_path, audio_path, output_path]
    print('  Converting HTML → video...')

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        print('  ❌ Timed out (10 min)')
        return False

    if result.returncode != 0:
        print(f'  ❌ Failed: {result.stderr.strip()[:300]}')
        return False

    if not os.path.exists(output_path):
        print(f'  ❌ Output file missing')
        return False

    print(f'  ✅ ({os.path.getsize(output_path)/1024/1024:.1f} MB)')
    return True


# ── Publishing ─────────────────────────────────────────────────────────────
def publish_video(video_path, title):
    print(f'  📤 Publishing: {os.path.basename(video_path)}')
    results = []

    if not os.path.isdir(UPLOAD_PATH):
        print(f'  ⚠️  Upload modules not found')
        print(f'  📁 Video saved at: {video_path}')
        return

    sys.path.insert(0, UPLOAD_PATH)

    platforms = []
    if os.getenv('INSTAGRAM_ACCESS_TOKEN') and os.getenv('INSTAGRAM_ACCOUNT_ID'):
        platforms.append(('Instagram', 'upload_instagram', 'upload_to_instagram', (video_path, title)))
    if os.getenv('FACEBOOK_ACCESS_TOKEN') and os.getenv('FACEBOOK_PAGE_ID'):
        platforms.append(('Facebook', 'upload_facebook', 'upload_to_facebook', (video_path, title, title)))
    if os.getenv('THREADS_ACCESS_TOKEN') and os.getenv('THREADS_USER_ID'):
        platforms.append(('Threads', 'upload_threads', 'upload_to_threads', (video_path, title)))
    if os.getenv('YT_CLIENT_ID') and os.getenv('YT_REFRESH_TOKEN'):
        desc = f'{title}\n\nAutomated ML visualization.\n#Shorts #MachineLearning #AI'
        platforms.append(('YouTube', 'upload_to_youtube', 'upload_to_youtube', (video_path, title, desc)))

    if not platforms:
        print('  ⚠️  No credentials set. Video saved locally.')
        return

    for name, mod_name, fn_name, args in platforms:
        try:
            mod = __import__(mod_name, fromlist=[fn_name])
            func = getattr(mod, fn_name)
            r = func(*args)
            status = r.get('status', 'done') if isinstance(r, dict) else 'done'
            results.append(f'{name}: {status}')
        except Exception as e:
            results.append(f'{name}: skipped ({str(e)[:80]})')

    for r in results:
        print(f'  {r}')


# ── Main pipeline ──────────────────────────────────────────────────────────
def run_pipeline():
    print('\n' + '=' * 60)
    print('🎬 HTML → VIDEO AUTO PIPELINE')
    print('=' * 60 + '\n')

    missing = []
    if not HTML_DRIVE_FOLDER_ID:  missing.append('HTML_DRIVE_FOLDER_ID')
    if not AUDIO_DRIVE_FOLDER_ID: missing.append('AUDIO_DRIVE_FOLDER_ID')
    if not SERVICE_ACCOUNT_KEY:   missing.append('GOOGLE_SERVICE_ACCOUNT_KEY')
    if missing:
        for m in missing:
            print(f'❌ {m} not set in .env')
        sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # ── Connect ────────────────────────────────────────────────────────────────
    print('📡 Connecting to Google Drive...')
    try:
        service = get_drive_service()
    except Exception as e:
        print(f'  ❌ Auth failed: {e}')
        sys.exit(1)
    print('  ✅ Connected')

    # ── Step 1: Fetch ONE HTML (try new first, fall back to repost) ────────────
    print('\n📥 STEP 1: Fetching HTML file from Google Drive...')

    html_file = fetch_one_html(service, allow_repost=False)

    if not html_file:
        print('\n⚠️  No new HTML files. Trying repost mode...')
        html_file = fetch_one_html(service, allow_repost=True)

    if not html_file:
        print('\n✅ No files to process. Pipeline complete.')
        return

    print(f'\n✅ Selected: {html_file["name"]}')

    # ── Step 2: Pick audio ────────────────────────────────────────────────────
    print('\n🎵 STEP 2: Picking audio track...')
    audio_file = fetch_one_audio(service)
    if not audio_file:
        print('❌ No audio available.')
        return

    # ── Step 3: Download both + convert ────────────────────────────────────────
    print('\n🎬 STEP 3: Downloading & converting...')
    tmp = tempfile.mkdtemp(prefix='htmlpipe_')
    try:
        # Download HTML
        html_path = os.path.join(tmp, html_file['name'])
        print(f'  ⬇️  HTML: {html_file["name"]}')
        download_file(service, html_file['id'], html_path)

        # Download audio
        audio_path = os.path.join(tmp, audio_file['name'])
        print(f'  ⬇️  Audio: {audio_file["name"]}')
        download_file(service, audio_file['id'], audio_path)

        # Convert
        out_name = html_file['name'].replace('.html', '.mp4')
        out_path = os.path.join(OUTPUT_DIR, out_name)
        ok = convert_html_to_video(html_path, audio_path, out_path)
        if not ok:
            return

        # ── Step 4: Publish ──────────────────────────────────────────────────
        print('\n📤 STEP 4: Publishing to social media...')
        title = os.path.splitext(html_file['name'])[0].replace('_', ' ').replace('-', ' ').title()
        publish_video(out_path, title)

        # ── Step 5: Log ──────────────────────────────────────────────────────
        mark_published(html_file['name'], html_file['id'])
        print(f'\n✅ Pipeline complete: {out_name}')

    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    run_pipeline()
