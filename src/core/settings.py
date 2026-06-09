import json
import os
import logging
import sys

SETTINGS_FILE = "dave_recorder_settings.json"

class SettingsManager:
    _instance = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = SettingsManager()
        return cls._instance

    def __init__(self):
        self.settings = {
            "save_directory": os.path.abspath(os.path.join(os.getcwd(), "recordings")),
            "filename_format": "{username}_{date}_{time}.opus",
            "recording_mode": "split",
            "record_video": True,
            "log_level": "INFO",
            "resolve_user_info_via_api": True,
            "global_mute": False,
            "muted_users": []
        }
        self.load()
        self.apply_log_level()

    def load(self):
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.settings.update(data)
            except Exception as e:
                import traceback
                print(f"Error loading settings: {e}\n{traceback.format_exc()}", file=sys.stderr)
                sys.exit(1)

    def save(self):
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=4)
        except Exception as e:
            import traceback
            print(f"Error saving settings: {e}\n{traceback.format_exc()}", file=sys.stderr)
            sys.exit(1)
            
    def get(self, key, default=None):
        return self.settings.get(key, default)
        
    def set(self, key, value):
        self.settings[key] = value
        self.save()
        if key == "log_level":
            self.apply_log_level()

    def apply_log_level(self):
        level_str = self.settings.get("log_level", "INFO").upper()
        numeric_level = getattr(logging, level_str, logging.INFO)
        logging.getLogger().setLevel(numeric_level)