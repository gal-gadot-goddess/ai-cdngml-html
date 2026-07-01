"""
Twitter/X Upload Script

Uploads videos to Twitter/X using Twitter API (Free Tier Compatible!)

Requirements:
- Twitter Developer Account (FREE tier works!)
- TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET

Free Tier Limits:
- 500 posts per month
- Video size: max 512 MB
- Video duration: max 140 seconds
"""

import os
import sys
import time
import tweepy
from pathlib import Path
from dotenv import load_dotenv

# Configure UTF-8 encoding for console output (Windows fix)
if sys.platform == 'win32':
    import codecs
    try:
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')
    except Exception:
        pass

# Load environment variables
load_dotenv()

def upload_to_twitter(video_path, caption):
    """Upload video to Twitter/X using API v1.1 (media) + v2 (post)."""
    
    api_key = os.getenv('TWITTER_API_KEY', '').strip()
    api_secret = os.getenv('TWITTER_API_SECRET', '').strip()
    access_token = os.getenv('TWITTER_ACCESS_TOKEN', '').strip()
    access_secret = os.getenv('TWITTER_ACCESS_SECRET', '').strip()
    
    if not all([api_key, api_secret, access_token, access_secret]):
        raise ValueError("[twitter] Missing Twitter credentials in .env")
    
    print("[twitter] [info] Uploading to Twitter/X...")
    
    video_path_obj = Path(video_path)
    if not video_path_obj.exists():
        raise FileNotFoundError(f"[twitter] [error] Video file not found: {video_path}")
    
    file_size_mb = video_path_obj.stat().st_size / (1024 * 1024)
    print(f"[twitter] Video size: {file_size_mb:.2f} MB")
    
    try:
        # 1. Authenticate V1 (Media Upload)
        print("[twitter] Authenticating with API v1.1 (media upload)...")
        auth = tweepy.OAuth1UserHandler(api_key, api_secret, access_token, access_secret)
        api_v1 = tweepy.API(auth)
        
        # 2. Authenticate V2 (Posting)
        print("[twitter] Authenticating with API v2 (posting)...")
        client = tweepy.Client(
            consumer_key=api_key,
            consumer_secret=api_secret,
            access_token=access_token,
            access_token_secret=access_secret
        )
        
        # 3. Upload Video (Chunked)
        print("[twitter] Uploading video (chunked)...")
        media = api_v1.media_upload(
            filename=str(video_path_obj),
            media_category='tweet_video',
            chunked=True 
        )
        print(f"[twitter] [success] Video uploaded! Media ID: {media.media_id}")
        
        # 4. Wait for Processing
        print("[twitter] Waiting for video processing (5s)...")
        time.sleep(5)
        
        # 5. Post Tweet
        print("[twitter] Posting tweet...")
        tweet_text = caption[:280]
        
        response = client.create_tweet(
            text=tweet_text,
            media_ids=[media.media_id]
        )
        
        tweet_id = response.data['id']
        tweet_url = f"https://twitter.com/i/web/status/{tweet_id}"
        
        print(f"[twitter] [success] Posted to Twitter!")
        print(f"[twitter] URL: {tweet_url}")
        
        return {'id': tweet_id, 'url': tweet_url, 'platform': 'twitter'}
        
    except tweepy.errors.Unauthorized as e:
        print(f"[twitter] [error] Authentication failed: {e}")
        raise
    except tweepy.errors.Forbidden as e:
        print(f"[twitter] [error] Permission denied: {e}")
        raise
    except tweepy.errors.TooManyRequests as e:
        print(f"[twitter] [error] Rate limit exceeded: {e}")
        raise
    except Exception as e:
        print(f"[twitter] [error] Unexpected error: {e}")
        raise

if __name__ == '__main__':
    # Test block
    video_file = Path('final_video.mp4')
    if video_file.exists():
        upload_to_twitter(video_file, "Test Upload #TwitterAPI")
    else:
        print("[twitter] No test video found.")
