"""
Threads Upload - Enhanced Debugging Version
Uploads video to tmpfiles.org, then uses URL for Threads API
"""

import os
import requests
import time
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables with override
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path, override=True)

def upload_to_threads(video_path, text):
    """
    Upload video to Threads via temporary public URL.
    """
    
    print("\n" + "=" * 60)
    print("🧵 THREADS UPLOAD STARTING")
    print("=" * 60)
    
    # Get credentials
    access_token = os.getenv('THREADS_ACCESS_TOKEN')
    user_id = os.getenv('THREADS_USER_ID')
    
    # Debug info (masked)
    def mask(s): return f"{s[:4]}...{s[-4:]}" if s and len(s) > 8 else ("PLACEHOLDER (***)" if s == "***" else "MISSING")
    print(f"[threads] User ID: {user_id}")
    print(f"[threads] Access Token: {mask(access_token)}")

    if not access_token:
        print("[threads] ⚠️  Skipping Threads upload - THREADS_ACCESS_TOKEN not set")
        return {'status': 'skipped', 'reason': 'Missing credentials', 'platform': 'threads'}

    if not user_id:
        print("[threads] ⚠️  Skipping Threads upload - THREADS_USER_ID not set")
        return {'status': 'skipped', 'reason': 'Missing credentials', 'platform': 'threads'}
    
    print(f"[threads] ✅ Credentials loaded")
    
    # Check video file
    video_path_obj = Path(video_path)
    if not video_path_obj.exists():
        error_msg = f"❌ Video file not found: {video_path}"
        print(f"[threads] {error_msg}")
        raise FileNotFoundError(error_msg)
    
    file_size_mb = video_path_obj.stat().st_size / (1024 * 1024)
    print(f"[threads] ✅ Video file found: {video_path}")
    print(f"[threads] Video size: {file_size_mb:.2f} MB")
    
    # Limit text
    text_limited = text[:500] if len(text) > 500 else text
    print(f"[threads] Text length: {len(text_limited)} characters")
    
    try:
        # Step 1: Upload to temporary hosting (file.io for reliability)
        print(f"[threads] 📤 Step 1: Uploading to temporary hosting...")
        
        video_url = None
        
        # Primary method: file.io
        try:
            print("[threads] Uploading to file.io...")
            with open(video_path_obj, 'rb') as video_file:
                files = {'file': video_file}
                # Set expiry to 1 day to be safe, auto-delete is default on download
                response = requests.post('https://file.io/?expires=1d', files=files, timeout=60)
                
            if response.status_code == 200:
                data = response.json()
                if data.get('success'):
                    video_url = data.get('link')
                    print(f"[threads] ✅ Uploaded to file.io: {video_url}")
                else:
                    print(f"[threads] ⚠️ file.io error: {data}")
            else:
                print(f"[threads] ⚠️ file.io failed with status {response.status_code}")
        except Exception as e:
            print(f"[threads] ⚠️ file.io exception: {e}")

        # Fallback: tmpfiles.org
        if not video_url:
            print("[threads] ⚠️ Trying fallback to tmpfiles.org...")
            try:
                with open(video_path_obj, 'rb') as video_file:
                    files = {'file': ('video.mp4', video_file, 'video/mp4')}
                    temp_response = requests.post(
                        'https://tmpfiles.org/api/v1/upload',
                        files=files,
                        timeout=180
                    )
                
                if temp_response.status_code == 200:
                    temp_data = temp_response.json()
                    temp_url = temp_data.get('data', {}).get('url', '')
                    if temp_url:
                        video_url = temp_url.replace('tmpfiles.org/', 'tmpfiles.org/dl/').replace('http://', 'https://')
                        print(f"[threads] ✅ Uploaded to tmpfiles.org: {video_url}")
            except Exception as e:
                 print(f"[threads] ⚠️ tmpfiles.org exception: {e}")

        if not video_url:
             raise Exception("All hosting attempts failed (file.io and tmpfiles.org)")
            
        print(f"[threads] ✅ Temporary URL ready: {video_url}")
        
        # Step 2: Create Threads container with video URL
        print(f"[threads] 📦 Step 2: Creating Threads container...")
        
        # Try different API versions
        api_versions = ['v1.0', 'v18.0']
        container_id = None
        
        for api_version in api_versions:
            print(f"[threads] Trying API version: {api_version}")
            
            container_url = f"https://graph.threads.net/{api_version}/{user_id}/threads"
            container_params = {
                'media_type': 'VIDEO',
                'video_url': video_url,
                'text': text_limited,
                'access_token': access_token
            }
            
            print(f"[threads] Request URL: {container_url}")
            print(f"[threads] Parameters: media_type=VIDEO, video_url={video_url[:50]}..., text length={len(text_limited)}")
            
            container_response = requests.post(container_url, params=container_params, timeout=60)
            
            print(f"[threads] Response status: {container_response.status_code}")
            print(f"[threads] Response headers: {dict(container_response.headers)}")
            print(f"[threads] Response body: {container_response.text}")
            
            if container_response.status_code == 200:
                response_data = container_response.json()
                container_id = response_data.get('id')
                if container_id:
                    print(f"[threads] ✅ Container created with API {api_version}: {container_id}")
                    break
            else:
                error_data = container_response.json() if container_response.text else {}
                error_msg = error_data.get('error', {}).get('message', 'Unknown error')
                error_code = error_data.get('error', {}).get('code', 'N/A')
                error_type = error_data.get('error', {}).get('type', 'N/A')
                error_subcode = error_data.get('error', {}).get('error_subcode', 'N/A')
                
                print(f"[threads] ❌ API {api_version} failed:")
                print(f"[threads]    Error type: {error_type}")
                print(f"[threads]    Error code: {error_code}")
                print(f"[threads]    Error subcode: {error_subcode}")
                print(f"[threads]    Error message: {error_msg}")
        
        if not container_id:
            error_msg = "Failed to create container with all API versions"
            print(f"[threads] ❌ {error_msg}")
            raise Exception(error_msg)
        
        # Step 3: Wait for processing
        print(f"[threads] ⏳ Step 3: Waiting for video processing...")
        max_wait = 120
        waited = 0
        
        while waited < max_wait:
            status_url = f"https://graph.threads.net/v1.0/{container_id}"
            status_params = {
                'fields': 'status',
                'access_token': access_token
            }
            
            status_response = requests.get(status_url, params=status_params, timeout=30)
            status_data = status_response.json()
            status = status_data.get('status', 'UNKNOWN')
            
            print(f"[threads] Status: {status} (waited {waited}s)")
            
            if status == 'FINISHED':
                print(f"[threads] ✅ Video processing complete!")
                break
            elif status == 'ERROR':
                error_msg = status_data.get('error_message', 'Video processing failed')
                print(f"[threads] ❌ {error_msg}")
                raise Exception(error_msg)
            
            time.sleep(10)
            waited += 10
        
        if waited >= max_wait:
            error_msg = "Video processing timed out"
            print(f"[threads] ❌ {error_msg}")
            raise Exception(error_msg)
        
        # Step 4: Publish
        print(f"[threads] 📤 Step 4: Publishing to Threads...")
        publish_url = f"https://graph.threads.net/v1.0/{user_id}/threads_publish"
        publish_params = {
            'creation_id': container_id,
            'access_token': access_token
        }
        
        publish_response = requests.post(publish_url, params=publish_params, timeout=60)
        
        if publish_response.status_code != 200:
            error_data = publish_response.json() if publish_response.text else {}
            error_msg = error_data.get('error', {}).get('message', 'Unknown error')
            print(f"[threads] ❌ Publish failed: {error_msg}")
            raise Exception(f"Threads Publish Error: {error_msg}")
        
        thread_id = publish_response.json().get('id')
        
        print(f"[threads] ✅ SUCCESS! Video published to Threads!")
        print(f"[threads] Thread ID: {thread_id}")
        print(f"[threads] Check your Threads profile to see the post!")
        print("=" * 60)
        
        return {
            'id': thread_id,
            'platform': 'threads',
            'status': 'success'
        }
        
    except Exception as e:
        print(f"[threads] ❌ ERROR!")
        print(f"[threads] {str(e)}")
        print("=" * 60)
        raise

if __name__ == '__main__':
    video_file = Path('final_video.mp4')
    if video_file.exists():
        try:
            result = upload_to_threads(str(video_file), "Test upload")
            print(f"\n✅ Success! Result: {result}")
        except Exception as e:
            print(f"\n❌ Failed: {e}")
    else:
        print(f"❌ Video not found: {video_file}")
