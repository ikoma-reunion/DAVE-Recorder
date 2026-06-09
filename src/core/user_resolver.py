import os
import json
import logging
import requests

logger = logging.getLogger(__name__)

class UserResolver:
    API_URL = "https://api.vaultcord.com/webhooks/public-lookup/{}"
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 DAVERecorder/1.0"

    def __init__(self, cache_dir: str):
        self.cache_dir = cache_dir
        self.avatars_dir = os.path.join(self.cache_dir, "avatars")
        self.json_path = os.path.join(self.cache_dir, "users.json")
        self.cache = {}
        self._refreshed_this_session = set()
        
        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.avatars_dir, exist_ok=True)
        self._load_cache()

    def _load_cache(self):
        if os.path.exists(self.json_path):
            with open(self.json_path, "r", encoding="utf-8") as f:
                self.cache = json.load(f)

    def _save_cache(self):
        with open(self.json_path, "w", encoding="utf-8") as f:
            json.dump(self.cache, f, ensure_ascii=False, indent=4)

    def resolve_user(self, user_id: str):
        if user_id in self.cache and user_id in self._refreshed_this_session:
            return self.cache[user_id]
            
        logger.info(f"Resolving user ID {user_id} via VaultCord API...")
        user_info = self._fetch_user_from_api(user_id)
        
        self._refreshed_this_session.add(user_id)
        
        if user_info:
            self.cache[user_id] = user_info
            self._save_cache()
            return user_info
        else:
            if user_id in self.cache:
                logger.info(f"Using cached data for user {user_id} as API fetch failed.")
                return self.cache[user_id]
            return None

    def _fetch_user_from_api(self, user_id: str):
        headers = {"User-Agent": self.USER_AGENT}
        resp = requests.get(self.API_URL.format(user_id), headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            
            # Download avatar
            avatar_hash = data.get("avatar")
            avatar_path = None
            if avatar_hash:
                ext = "gif" if avatar_hash.startswith("a_") else "png"
                img_url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.{ext}?size=128"
                img_resp = requests.get(img_url, headers=headers, timeout=5)
                if img_resp.status_code == 200:
                    avatar_path = os.path.join(self.avatars_dir, f"{user_id}_{avatar_hash}.{ext}")
                    with open(avatar_path, "wb") as f:
                        f.write(img_resp.content)
                        
            user_info = {
                "id": user_id,
                "username": data.get("username"),
                "global_name": data.get("global_name"),
                "avatar_hash": avatar_hash,
                "avatar_path": avatar_path
            }
            
            return user_info
        else:
            logger.warning(f"Failed to fetch user {user_id}: API returned {resp.status_code} - {resp.text}")
            return None
