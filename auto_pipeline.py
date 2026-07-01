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


def extract_html_title(html_path):
    """Extract <title> tag content from an HTML file."""
    try:
        with open(html_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read(4096)  # Read first 4KB — title is always in <head>
        import re
        m = re.search(r'<title[^>]*>(.*?)</title>', content, re.IGNORECASE | re.DOTALL)
        if m:
            return m.group(1).strip()
    except:
        pass
    return None


def generate_title_and_description(html_path, html_file_name):
    """Generate video title + description from HTML filename and <title> tag.
    
    Uses POLLINATIONS_API_KEY (same as Valeria Solverde) if available,
    otherwise falls back to filename-based title + default description.
    """
    # Extract topic from filename
    base = os.path.splitext(html_file_name)[0]
    topic = base.replace('_', ' ').replace('-', ' ').title()

    # Try to get HTML <title> tag
    html_title = extract_html_title(html_path)
    if html_title:
        topic = html_title

    # ── Use AI if API key is available ────────────────────────────────────────
    api_key = os.getenv('POLLINATIONS_API_KEY')
    if api_key:
        import requests
        prompt = (
            f'Write a short, catchy title (max 8 words) and a 2-sentence description '
            f'for a YouTube Short / Instagram Reel about "{topic}" — '
            f'an educational machine learning / programming visualization. '
            f'Make it engaging and clear. '
            f'Return ONLY a valid JSON object: {{"title": "...", "description": "..."}}'
        )
        try:
            resp = requests.post(
                'https://gen.pollinations.ai/v1/chat/completions',
                headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                json={
                    'model': os.getenv('AI_MODEL', 'openai'),
                    'messages': [{'role': 'user', 'content': prompt}],
                    'temperature': 0.8,
                },
                timeout=15
            )
            data = resp.json()
            content = data.get('choices', [{}])[0].get('message', {}).get('content', '')
            content = content.replace('```json', '').replace('```', '').strip()
            result = json.loads(content)
            if result.get('title') and result.get('description'):
                return result['title'], result['description']
        except Exception as e:
            print(f'  ⚠️  AI caption failed: {e}')

    # ── Fallback ──────────────────────────────────────────────────────────────
    desc = (
        f'{topic} — Machine Learning visualization.\n\n'
        f'Watch and learn. Perfect for beginners and enthusiasts.\n\n'
        f'#MachineLearning #AI #DataScience #Coding #Shorts'
    )
    return topic, desc


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


# ── Publishing (mirrors Valeria Solverde pattern) ──────────────────────────
def publish_video(video_path, title, description):
    print(f'  📤 Publishing: {os.path.basename(video_path)}')
    results = {}

    if not os.path.isdir(UPLOAD_PATH):
        print(f'  ⚠️  Upload modules not found')
        print(f'  📁 Video saved at: {video_path}')
        return

    sys.path.insert(0, os.path.dirname(UPLOAD_PATH))
    combined_caption = f'{title}\n\n{description}'

    # ── Instagram Reel ────────────────────────────────────────────────────────
    if os.getenv('INSTAGRAM_ACCESS_TOKEN') and os.getenv('INSTAGRAM_ACCOUNT_ID'):
        try:
            from upload.upload_instagram import upload_to_instagram
            r = upload_to_instagram(video_path, combined_caption, is_story=False)
            if r and r.get('status') == 'skipped':
                results['Instagram Reel'] = f'skipped ({r.get("reason", "")})'
            else:
                results['Instagram Reel'] = 'done'
        except Exception as e:
            results['Instagram Reel'] = f'skipped ({str(e)[:60]})'

    # ── Instagram Story ───────────────────────────────────────────────────────
    if os.getenv('INSTAGRAM_ACCESS_TOKEN') and os.getenv('INSTAGRAM_ACCOUNT_ID'):
        try:
            from upload.upload_instagram import upload_to_instagram
            r = upload_to_instagram(video_path, combined_caption, is_story=True)
            if r and r.get('status') == 'skipped':
                results['Instagram Story'] = f'skipped ({r.get("reason", "")})'
            else:
                results['Instagram Story'] = 'done'
        except Exception as e:
            results['Instagram Story'] = f'skipped ({str(e)[:60]})'

    # ── Facebook Reel ─────────────────────────────────────────────────────────
    if os.getenv('FACEBOOK_ACCESS_TOKEN') and os.getenv('FACEBOOK_PAGE_ID'):
        try:
            from upload.upload_facebook import upload_to_facebook
            r = upload_to_facebook(video_path, description, title=title)
            if r and r.get('status') == 'skipped':
                results['Facebook Reel'] = f'skipped ({r.get("reason", "")})'
            else:
                results['Facebook Reel'] = 'done'
        except Exception as e:
            results['Facebook Reel'] = f'skipped ({str(e)[:60]})'

    # ── Facebook Story ────────────────────────────────────────────────────────
    if os.getenv('FACEBOOK_ACCESS_TOKEN') and os.getenv('FACEBOOK_PAGE_ID'):
        try:
            from upload.upload_facebook import upload_to_facebook_story
            r = upload_to_facebook_story(video_path)
            if r and r.get('status') == 'skipped':
                results['Facebook Story'] = f'skipped'
            else:
                results['Facebook Story'] = 'done'
        except Exception as e:
            results['Facebook Story'] = f'skipped ({str(e)[:60]})'

    # ── Threads ───────────────────────────────────────────────────────────────
    if os.getenv('THREADS_ACCESS_TOKEN') and os.getenv('THREADS_USER_ID'):
        try:
            from upload.upload_threads import upload_to_threads
            r = upload_to_threads(video_path, combined_caption)
            if r and r.get('status') == 'skipped':
                results['Threads'] = f'skipped ({r.get("reason", "")})'
            else:
                results['Threads'] = 'done'
        except Exception as e:
            results['Threads'] = f'skipped ({str(e)[:60]})'

    # ── YouTube Shorts ────────────────────────────────────────────────────────
    if os.getenv('YT_CLIENT_ID') and os.getenv('YT_REFRESH_TOKEN'):
        try:
            from upload.upload_to_youtube import upload_to_youtube
            tags = ['machine learning', 'ai', 'visualization', 'coding', 'shorts', 'education', 'datascience']
            upload_to_youtube(video_path, title, description, tags=tags)
            results['YouTube'] = 'done'
        except Exception as e:
            results['YouTube'] = f'skipped ({str(e)[:60]})'

    for platform, status in results.items():
        print(f'  {platform}: {status}')
    if not results:
        print('  ⚠️  No credentials set. Video saved locally.')


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

        # ── Step 4: Generate title + description ──────────────────────────────
        print('\n📝 Generating title & description...')
        title, description = generate_title_and_description(html_path, html_file['name'])
        print(f'  Title: {title}')
        print(f'  Description: {description[:100]}...')

        # ── Step 5: Publish ──────────────────────────────────────────────────
        print('\n📤 STEP 5: Publishing to social media...')
        publish_video(out_path, title, description)

        # ── Step 5: Log ──────────────────────────────────────────────────────
        mark_published(html_file['name'], html_file['id'])
        print(f'\n✅ Pipeline complete: {out_name}')

    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    run_pipeline()
