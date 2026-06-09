import os
import threading
import logging

logger = logging.getLogger(__name__)

class VideoManager:
    def __init__(self, output_dir="recordings"):
        self.output_dir = output_dir
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
            
        self.lock = threading.Lock()
        
        self.user_files = {} # userId -> file object
        self.user_filepaths = {} # userId -> current file path
        self.keyframe_seen = {} # userId -> bool

    def _get_filepath(self, user_id):
        return os.path.join(self.output_dir, f"video_{user_id}.h264")

    def _has_h264_keyframe(self, data: bytes) -> bool:
        # Check for 4-byte start codes
        idx = 0
        while True:
            idx = data.find(b'\x00\x00\x00\x01', idx)
            if idx == -1:
                break
            if idx + 4 < len(data):
                nal_type = data[idx+4] & 0x1F
                if nal_type in (7, 5): # SPS (7) or IDR (5)
                    return True
            idx += 4
            
        # Check for 3-byte start codes
        idx = 0
        while True:
            idx = data.find(b'\x00\x00\x01', idx)
            if idx == -1:
                break
            # Ignore if it's actually a 4-byte start code (we already checked them)
            if idx > 0 and data[idx-1] == 0:
                idx += 3
                continue
                
            if idx + 3 < len(data):
                nal_type = data[idx+3] & 0x1F
                if nal_type in (7, 5): # SPS (7) or IDR (5)
                    return True
            idx += 3
            
        return False

    def on_h264_frame(self, user_id: str, data: bytes, is_keyframe: bool = False):
        with self.lock:
            if not user_id:
                return
                
            # If user_id is a decoder pointer (not mapped yet), we create a fallback unknown file
            if not user_id.isdigit() and not user_id.startswith("unknown_ssrc_"):
                # user_id is actually a decoder pointer string here
                filepath = self.user_filepaths.get(user_id)
                if not filepath:
                    filepath = os.path.join(self.output_dir, f"unknown_decoder_{user_id}.h264")
                    self.user_filepaths[user_id] = filepath
                    
                if user_id not in self.keyframe_seen:
                    self.keyframe_seen[user_id] = False
                    
                if not self.keyframe_seen[user_id]:
                    if is_keyframe or self._has_h264_keyframe(data):
                        self.keyframe_seen[user_id] = True
                    else:
                        return
                        
                if user_id not in self.user_files:
                    self.user_files[user_id] = open(filepath, 'ab')
                
                self.user_files[user_id].write(data)
                self.user_files[user_id].flush()
                return
                
            if user_id not in self.keyframe_seen:
                self.keyframe_seen[user_id] = False
                logger.info(f"Waiting for keyframe on video stream for {user_id}...")
                
            if not self.keyframe_seen[user_id]:
                if is_keyframe or self._has_h264_keyframe(data):
                    self.keyframe_seen[user_id] = True
                    logger.info(f"Keyframe found for {user_id}. Starting recording.")
                else:
                    return # Drop frame until keyframe arrives
                    
            if user_id in self.user_files:
                self.user_files[user_id].write(data)
                self.user_files[user_id].flush()
            else:
                # We don't have a file opened yet. Let's open the default one.
                filepath = self.user_filepaths.get(user_id)
                if not filepath:
                    filepath = self._get_filepath(user_id)
                    self.user_filepaths[user_id] = filepath
                    
                self.user_files[user_id] = open(filepath, 'ab')
                self.user_files[user_id].write(data)
                self.user_files[user_id].flush()

    def set_user_filepath(self, user_id: str, filepath: str):
        with self.lock:
            if user_id in self.user_files:
                self.user_files[user_id].close()
                del self.user_files[user_id]
            self.user_filepaths[user_id] = filepath
            logger.info(f"Registered intended video filepath for {user_id}: {filepath}")

    def rename_user(self, user_id: str, new_filepath: str):
        with self.lock:
            if user_id not in self.user_filepaths:
                return

            old_filepath = self.user_filepaths[user_id]
            if old_filepath == new_filepath:
                return

            was_open = False
            if user_id in self.user_files:
                self.user_files[user_id].close()
                del self.user_files[user_id]
                was_open = True

            if os.path.exists(old_filepath):
                os.rename(old_filepath, new_filepath)
                logger.info(f"Renamed video file for {user_id}: {old_filepath} -> {new_filepath}")

            self.user_filepaths[user_id] = new_filepath
            if was_open or os.path.exists(new_filepath):
                self.user_files[user_id] = open(new_filepath, 'ab')

    def close_user(self, user_id: str):
        with self.lock:
            filepath = self.user_filepaths.get(user_id)
            if user_id in self.user_files:
                self.user_files[user_id].close()
                del self.user_files[user_id]
                logger.info(f"Closed video file for {user_id}")
            
            if user_id in self.user_filepaths:
                del self.user_filepaths[user_id]
                
            if user_id in self.keyframe_seen:
                del self.keyframe_seen[user_id]
                
            return filepath

    def stop(self):
        with self.lock:
            for f in self.user_files.values():
                if not f.closed:
                    f.close()
            self.user_files.clear()
            self.keyframe_seen.clear()

    def __del__(self):
        self.stop()
