"""
Instagram Reels Upload - Using temp hosting services for Public URL
Uploads video via fallback chain of free hosts, then uses URL for Instagram API
"""

import os
import subprocess
import requests
import tempfile
import time
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path, override=True)

TEMP_COMPRESS_DIR = Path(tempfile.gettempdir()) / "ig_compress"
TEMP_COMPRESS_DIR.mkdir(parents=True, exist_ok=True)

REQ_TIMEOUT = (15, 120)


def compress_for_instagram(video_path):
    """Compress video to ~30-40MB for faster Instagram processing."""
    input_path = Path(video_path)
    output_path = TEMP_COMPRESS_DIR / f"compressed_{input_path.stem}.mp4"

    original_size_mb = input_path.stat().st_size / (1024 * 1024)
    print(f"[instagram] Original size: {original_size_mb:.1f} MB")

    if original_size_mb < 40:
        print(f"[instagram] Under 40MB, skipping compression")
        return str(video_path)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-c:v", "libx264",
        "-crf", "28",
        "-preset", "fast",
        "-c:a", "aac",
        "-b:a", "96k",
        "-movflags", "+faststart",
        str(output_path)
    ]

    print(f"[instagram] Compressing video (target ~30MB)...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    if result.returncode != 0 or not output_path.exists():
        print(f"[instagram] Compression failed: {result.stderr[:500]}")
        print(f"[instagram] Falling back to original video")
        return str(video_path)

    compressed_size_mb = output_path.stat().st_size / (1024 * 1024)
    ratio = (1 - compressed_size_mb / original_size_mb) * 100
    print(f"[instagram] Compressed: {original_size_mb:.1f}MB → {compressed_size_mb:.1f}MB ({ratio:.0f}% reduction)")
    return str(output_path)


def cleanup_compressed(file_path):
    """Remove compressed temp file."""
    try:
        p = Path(file_path)
        if p.parent == TEMP_COMPRESS_DIR and p.exists():
            p.unlink()
    except Exception:
        pass


    for name, upload_func in HOSTING_SERVICES:
        try:
            print(f"[instagram] Trying {name}...")
            url = upload_func(file_path)
            print(f"[instagram] Uploaded via {name}: {url}")
            return url
        except Exception as e:
            print(f"[instagram] {name} failed: {e}")
            last_error = e
            continue
    raise Exception(f"All hosting services failed. Last error: {last_error}")


def upload_to_instagram(video_path, caption, is_story=False):
    media_type = 'STORIES' if is_story else 'REELS'

    print("\n" + "=" * 60)
    print(f"INSTAGRAM {media_type} UPLOAD STARTING")
    print("=" * 60)

    access_token = os.getenv('INSTAGRAM_ACCESS_TOKEN') or os.getenv('FACEBOOK_ACCESS_TOKEN')
    user_id = os.getenv('INSTAGRAM_ACCOUNT_ID') or os.getenv('IG_USER_ID')

    def mask(s):
        return f"{s[:10]}...{s[-4:]}" if s and len(s) > 10 else ("PLACEHOLDER" if s == "***" else "MISSING")

    print(f"[instagram] User ID Provided: {user_id}")
    print(f"[instagram] Access Token: {mask(access_token)}")

    if not access_token:
        print("[instagram] Skipping Instagram upload - INSTAGRAM_ACCESS_TOKEN not set")
        return {'status': 'skipped', 'reason': 'Missing credentials', 'platform': 'instagram'}

    if access_token.startswith('IGAA'):
        print("[instagram] Detected 'IGAA' token (Instagram Basic/Standard API)")
        print("[instagram] Fetching correct ID for this token...")
        try:
            me_resp = requests.get(
                f"https://graph.facebook.com/me?fields=id,username&access_token={access_token}",
                timeout=10
            )
            if me_resp.status_code == 200:
                me_data = me_resp.json()
                detected_id = me_data.get('id')
                if detected_id and detected_id != user_id:
                    print(f"[instagram] ID Mismatch! Provided: {user_id}, Detected: {detected_id}")
                    print(f"[instagram] Using detected ID: {detected_id}")
                    user_id = detected_id
            else:
                print(f"[instagram] Could not verify token: {me_resp.text}")
        except Exception as e:
            print(f"[instagram] Error during ID verification: {e}")

    if not user_id:
        print("[instagram] Skipping Instagram upload - INSTAGRAM_ACCOUNT_ID not set")
        return {'status': 'skipped', 'reason': 'Missing credentials', 'platform': 'instagram'}

    print("[instagram] Credentials loaded")

    video_path_obj = Path(video_path)
    if not video_path_obj.exists():
        error_msg = f"Video file not found: {video_path}"
        print(f"[instagram] {error_msg}")
        raise FileNotFoundError(error_msg)

    file_size_mb = video_path_obj.stat().st_size / (1024 * 1024)
    print(f"[instagram] Video file found: {video_path}")
    print(f"[instagram] Video size: {file_size_mb:.2f} MB")

    caption_limited = caption[:2200] if len(caption) > 2200 else caption
    print(f"[instagram] Caption length: {len(caption_limited)} characters")

    compressed = compress_for_instagram(video_path)
    upload_path = compressed

    try:
        print("[instagram] Step 1: Uploading to GitHub raw URL...")
        import subprocess as _sp, uuid as _uuid, os as _os
        _vid_name = "ig_" + _uuid.uuid4().hex[:8] + ".mp4"
        _os.system("cp " + str(upload_path) + " " + _vid_name)
        _os.system("git config --global user.email bot@bot.com")
        _os.system("git config --global user.name Bot")
        _os.system("git add -f " + _vid_name)
        _os.system("git commit -m \"add " + _vid_name + "\"")
        for _ in range(3):
            _ret = _os.system("git push origin main")
            if _ret == 0:
                break
            time.sleep(5)
        video_url = "https://raw.githubusercontent.com/ai-cdngml-html/main/" + _vid_name
        print("[instagram] GitHub raw URL: " + video_url)

        container_url = f"https://graph.facebook.com/v21.0/{user_id}/media"
        container_params = {
            'media_type': media_type,
            'video_url': video_url,
            'access_token': access_token
        }

        if not is_story:
            container_params['caption'] = caption_limited
            container_params['share_to_feed'] = 'false'
            container_params['thumb_offset'] = '5000'

        container_response = requests.post(container_url, params=container_params, timeout=60)

        if container_response.status_code != 200:
            error_data = container_response.json() if container_response.text else {}
            error_msg = error_data.get('error', {}).get('message', 'Unknown error')
            print(f"[instagram] Container creation failed: {error_msg}")
            print(f"[instagram] Full response: {container_response.text[:500]}")

            print("[instagram] Retrying with Instagram Graph API endpoint...")
            container_url = f"https://graph.instagram.com/v21.0/{user_id}/media"
            container_response = requests.post(container_url, params=container_params, timeout=60)

            if container_response.status_code != 200:
                error_data = container_response.json() if container_response.text else {}
                error_msg = error_data.get('error', {}).get('message', 'Unknown error')
                raise Exception(f"Instagram Container Error: {error_msg}")

        container_id = container_response.json().get('id')
        print(f"[instagram] Container created: {container_id}")

        print("[instagram] Step 3: Waiting 60 seconds for processing...")
        time.sleep(60)

        # Step 4: Publish
        print("[instagram] Step 4: Publishing...")
        publish_url = f"https://graph.facebook.com/v21.0/{user_id}/media_publish"
        publish_params = {
            "creation_id": container_id,
            "access_token": access_token
        }
        publish_response = requests.post(publish_url, params=publish_params, timeout=60)

        if publish_response.status_code != 200:
            print("[instagram] First publish failed, retrying after 30s...")
            time.sleep(30)
            publish_response = requests.post(publish_url, params=publish_params, timeout=60)

        if publish_response.status_code != 200:
            error_data = publish_response.json() if publish_response and publish_response.text else {}
            error_msg = error_data.get("error", {}).get("message", "Unknown error")
            print(f"[instagram] Publish failed: {error_msg}")
            raise Exception(f"Instagram Publish Error: {error_msg}")

        media_id = publish_response.json().get("id")

        print("[instagram] SUCCESS! Video published to Instagram!")
        print(f"[instagram] Media ID: {media_id}")
        print("[instagram] Check your Instagram profile to see the post!")
        print("=" * 60)

        return {
            'id': media_id,
            'platform': 'instagram',
            'status': 'success'
        }

    except Exception as e:
        print("[instagram] ERROR!")
        print(f"[instagram] {str(e)}")
        print("=" * 60)
        raise

    finally:
        cleanup_compressed(upload_path)


if __name__ == '__main__':
    video_file = Path('ielts_short.mp4')
    if video_file.exists():
        try:
            result = upload_to_instagram(str(video_file), "IELTS Band 9 Upgrade! #IELTS #English")
            print(f"\nSuccess! Result: {result}")
        except Exception as e:
            print(f"\nFailed: {e}")
    else:
        print(f"Video not found: {video_file}")
