"""One-time helper that creates the Spotify refresh token used by Little Guy."""

import os

from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyOAuth


load_dotenv()

client_id = os.environ["SPOTIFY_CLIENT_ID"]
client_secret = os.environ["SPOTIFY_CLIENT_SECRET"]
redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
oauth = SpotifyOAuth(
    client_id=client_id,
    client_secret=client_secret,
    redirect_uri=redirect_uri,
    scope="playlist-read-private playlist-read-collaborative",
    open_browser=False,
    cache_path=None,
)

print("Open this URL in a browser and approve access:\n")
print(oauth.get_authorize_url())
redirected_url = input("\nPaste the full URL you were redirected to: ").strip()
code = oauth.parse_response_code(redirected_url)
token_info = oauth.get_access_token(code=code, check_cache=False)
print("\nAdd this secret to .env as SPOTIFY_REFRESH_TOKEN:\n")
print(token_info["refresh_token"])
