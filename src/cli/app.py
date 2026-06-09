import os
import time
import logging
import threading
from datetime import datetime

from core.frida_manager import FridaManager
from core.ogg_writer import OggOpusWriter
from core.settings import SettingsManager
from core.user_resolver import UserResolver
from core.audio_player import AudioMixer
from core.video_manager import VideoManager

logger = logging.getLogger(__name__)

class CliApp:
    def __init__(self, instances, scripts_dir):
        self.settings = SettingsManager.get_instance()
        self.instances = instances
        self.scripts_dir = scripts_dir
        self.managers = []
        self.video_manager = VideoManager(os.path.abspath(str(self.settings.get("save_directory"))))
        self.writers = {}
        self.writer_last_seen = {}
        self.ssrc_map = {}
        self.unmapped_ssrcs = {}
        self.unmapped_packets = {}
        self.unresolved_packets = {}
        self.recent_speakers = {}
        self.fetched_users = set()
        self.is_running = True
        
        cache_dir = os.path.join(os.getcwd(), ".cache")
        self.resolver = UserResolver(cache_dir)

    def start(self):
        for inst in self.instances:
            manager = FridaManager(inst.voice_pid, self.scripts_dir)
            manager.user_mapped.connect(self.on_user_mapped)
            manager.user_speaking.connect(self.on_user_speaking)
            manager.packet_received.connect(self.on_packet_received)
            manager.video_decoder_frame.connect(self.on_video_decoder_frame)
            manager.error_occurred.connect(self.on_error)
            manager.start()
            self.managers.append(manager)
        logger.info(f"Attached to {len(self.managers)} instances.")

    def on_video_decoder_frame(self, user_id_or_decoder, payload, is_keyframe):
        if not self.settings.get("record_video", True):
            return
        self.video_manager.on_h264_frame(user_id_or_decoder, payload, is_keyframe)

    def stop(self):
        self.is_running = False
        for manager in self.managers:
            manager.stop()
        self.managers.clear()
        self._close_all_writers()

    def check_inactivity(self):
        now = time.time()
        to_close = []
        to_end_segment = []
        mode = self.settings.get("recording_mode", "split")
        
        for user_id, last_seen in list(self.writer_last_seen.items()):
            if now - last_seen > 1.5:
                self.on_user_speaking(user_id, False)
                if mode == "split":
                    to_close.append(user_id)
                else:
                    to_end_segment.append(user_id)
                
        for user_id in to_close:
            self._close_writer(user_id)
            
        for user_id in to_end_segment:
            if user_id in self.writers and self.writers[user_id].get('segment_active', False):
                self.writers[user_id]['segment_active'] = False
                start_t = self.writers[user_id].get('current_segment_start', int(time.time() * 1000))
                end_t = int((now - 1.5) * 1000)
                if end_t < start_t:
                    end_t = start_t
                self.writers[user_id]['segments'].append({"start": start_t, "end": end_t})
            if user_id in self.writer_last_seen:
                del self.writer_last_seen[user_id]

    def _close_writer(self, user_id):
        if user_id in self.writers:
            w_info = self.writers[user_id]
            w_info['writer'].close()
            
            end_time_str = datetime.now().strftime("%H%M%S")
            old_filename = w_info['filename']
            new_filename = old_filename.replace("_ongoing.opus", f"-{end_time_str}.opus")
            
            try:
                if os.path.exists(old_filename):
                    os.rename(old_filename, new_filename)
                    logger.info(f"Closed and renamed recording for {user_id}: {new_filename}")
                    
                    mode = self.settings.get("recording_mode", "split")
                    if mode == "append" and 'segments' in w_info and w_info['segments']:
                        import json
                        json_filename = new_filename.replace(".opus", ".json")
                        with open(json_filename, "w", encoding="utf-8") as jf:
                            json.dump(w_info['segments'], jf, separators=(',', ':'))
            except Exception as e:
                logger.error(f"Failed to rename file {old_filename}: {e}")
                
            del self.writers[user_id]
            
        if user_id in self.writer_last_seen:
            del self.writer_last_seen[user_id]

        old_video_path = self.video_manager.close_user(user_id)
        if old_video_path and old_video_path.endswith("_ongoing.h264"):
            end_time_str = datetime.now().strftime("%H%M%S")
            new_video_path = old_video_path.replace("_ongoing.h264", f"-{end_time_str}.h264")
            try:
                if os.path.exists(old_video_path):
                    os.rename(old_video_path, new_video_path)
                    logger.info(f"Renamed video recording for {user_id}: {new_video_path}")
            except Exception as e:
                logger.error(f"Failed to rename video file {old_video_path}: {e}")

    def _close_all_writers(self):
        for user_id in list(self.writers.keys()):
            self._close_writer(user_id)

    def on_user_mapped(self, ssrc, user_id):
        if ssrc > 0:
            self.ssrc_map[ssrc] = user_id
            
            if ssrc in self.unmapped_packets:
                logger.info(f"Flushing {len(self.unmapped_packets[ssrc])} buffered packets for newly mapped user {user_id}")
                for payload in self.unmapped_packets[ssrc]:
                    self.on_packet_received(ssrc, payload)
                del self.unmapped_packets[ssrc]
                
            # If we had an unknown session for this SSRC, transfer it
            unknown_id = f"unknown_ssrc_{ssrc}"
            if unknown_id in self.writers:
                logger.info(f"Transferring recording session from {unknown_id} to {user_id}")
                sess = self.writers.pop(unknown_id)
                self.writers[user_id] = sess
                
                # We should ideally rename the file as well, but for simplicity
                # we'll just let the next segment/close use the real user_id,
                # or rename it on close. Let's rename it now if it's ongoing.
                old_filename = sess['filename']
                if "unknown_ssrc_" in old_filename and os.path.exists(old_filename):
                    new_filename = old_filename.replace(unknown_id, user_id)
                    try:
                        os.rename(old_filename, new_filename)
                        sess['filename'] = new_filename
                        sess['writer'].filename = new_filename # Update internal writer state
                        logger.info(f"Renamed ongoing recording: {new_filename}")
                    except Exception as e:
                        logger.error(f"Failed to rename ongoing recording: {e}")
                        
            if ssrc in self.unmapped_ssrcs:
                del self.unmapped_ssrcs[ssrc]
                
        logger.info(f"User mapped: {user_id} (SSRC: {ssrc})")
        if user_id not in self.fetched_users and self.settings.get("resolve_user_info_via_api"):
            self.fetched_users.add(user_id)
            threading.Thread(target=self._fetch_user_info_thread, args=(user_id,), daemon=True).start()

    def on_user_disconnected(self, user_id):
        self._close_writer(user_id)

    def _fetch_user_info_thread(self, user_id):
        if not getattr(self, 'is_running', True):
            return
        info = self.resolver.resolve_user(user_id)
        if not getattr(self, 'is_running', True):
            return
        if info:
            name = info.get("global_name") or info.get("username") or user_id
            logger.info(f"User resolved: {name} ({user_id})")
        else:
            self.resolver.cache[user_id] = {}
            
        if user_id in self.unresolved_packets:
            logger.info(f"Flushing {len(self.unresolved_packets[user_id])} buffered packets for resolved user {user_id}")
            for ssrc, payload in self.unresolved_packets[user_id]:
                self._process_packet(user_id, ssrc, payload)
            del self.unresolved_packets[user_id]

    def on_user_speaking(self, user_id, is_speaking):
        if is_speaking:
            # Timing heuristic for unknown SSRCs
            recent_ssrc = None
            recent_time = 0
            for ssrc, t in list(self.unmapped_ssrcs.items()):
                if t > recent_time:
                    recent_time = t
                    recent_ssrc = ssrc
            
            if recent_ssrc is not None and (time.time() - recent_time < 3.0):
                logger.info(f"Map (Heuristic): SSRC {recent_ssrc} -> UserID {user_id}")
                self.ssrc_map[recent_ssrc] = user_id
                
                if recent_ssrc in self.unmapped_packets:
                    logger.info(f"Flushing {len(self.unmapped_packets[recent_ssrc])} buffered packets via heuristic map for {user_id}")
                    for payload in self.unmapped_packets[recent_ssrc]:
                        self.on_packet_received(recent_ssrc, payload)
                    del self.unmapped_packets[recent_ssrc]
                    
                del self.unmapped_ssrcs[recent_ssrc]
                
                # Fix session if it was created under "unknown" ID
                unknown_id = f"unknown_ssrc_{recent_ssrc}"
                if unknown_id in self.writers:
                    sess = self.writers.pop(unknown_id)
                    self.writers[user_id] = sess
                    logger.info(f"Transferred session from {unknown_id} to {user_id}")
                
            # For append mode: Record segment start
            if user_id in self.writers:
                if 'segments' not in self.writers[user_id]:
                    self.writers[user_id]['segments'] = []
                if not self.writers[user_id].get('segment_active', False):
                    self.writers[user_id]['segment_active'] = True
                    self.writers[user_id]['current_segment_start'] = int(time.time() * 1000)
        else:
            mode = self.settings.get("recording_mode", "split")
            if mode == "split":
                self._close_writer(user_id)
            else:
                # Append mode: record segment end
                if user_id in self.writers and self.writers[user_id].get('segment_active', False):
                    self.writers[user_id]['segment_active'] = False
                    start_t = self.writers[user_id].get('current_segment_start', int(time.time() * 1000))
                    end_t = int(time.time() * 1000)
                    self.writers[user_id]['segments'].append({"start": start_t, "end": end_t})

    def on_packet_received(self, ssrc, payload):
        if payload == b"\xf8\xff\xfe":
            return # Silence packet
            
        if ssrc not in self.ssrc_map:
            # Buffer unmapped SSRC packets instead of creating unknown_ssrc files
            if ssrc not in self.unmapped_packets:
                self.unmapped_packets[ssrc] = []
                self.unmapped_ssrcs[ssrc] = time.time()
            self.unmapped_packets[ssrc].append(payload)
            if len(self.unmapped_packets[ssrc]) > 500: # Max ~10 seconds of audio
                self.unmapped_packets[ssrc].pop(0)
            return
            
        user_id = self.ssrc_map[ssrc]
            
        if self.settings.get("resolve_user_info_via_api") and user_id not in self.resolver.cache:
            if user_id not in self.unresolved_packets:
                self.unresolved_packets[user_id] = []
            self.unresolved_packets[user_id].append((ssrc, payload))
            if len(self.unresolved_packets[user_id]) > 1000:
                self.unresolved_packets[user_id].pop(0)
            return
            
        self._process_packet(user_id, ssrc, payload)

    def _process_packet(self, user_id, ssrc, payload):
        self.writer_last_seen[user_id] = time.time()
            
        if user_id not in self.writers:
            base_dir = os.path.abspath(str(self.settings.get("save_directory")))
            fmt = str(self.settings.get("filename_format"))
            if not fmt.endswith(".opus"):
                fmt += ".opus"
            fmt = fmt.replace(".opus", "_ongoing.opus")
            
            now = datetime.now()
            # For CLI we don't have user_cards, we use cache directly
            info = self.resolver.cache.get(user_id, {})
            uname = info.get("username", user_id)
            gname = info.get("global_name") or uname
            
            formatted = fmt.format(
                user_id=user_id,
                username=uname,
                global_name=gname,
                date=now.strftime("%Y%m%d"),
                time=now.strftime("%H%M%S")
            )
            filepath = os.path.normpath(os.path.join(base_dir, formatted))
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            
            logger.info(f"Started new recording session for user {user_id} at {filepath}")
            self.writers[user_id] = {
                'writer': OggOpusWriter(filepath, ssrc),
                'filename': filepath,
                'start_time': now.strftime("%H%M%S")
            }
            
            if self.settings.get("record_video", True):
                v_fmt = str(self.settings.get("filename_format"))
                if v_fmt.endswith(".opus") or v_fmt.endswith(".h264"):
                    v_fmt = v_fmt[:-5]
                v_fmt += "_ongoing.h264"
                
                v_formatted = v_fmt.format(
                    user_id=user_id,
                    username=uname,
                    global_name=gname,
                    date=now.strftime("%Y%m%d"),
                    time=now.strftime("%H%M%S")
                )
                v_filepath = os.path.normpath(os.path.join(base_dir, v_formatted))
                os.makedirs(os.path.dirname(v_filepath), exist_ok=True)
                self.video_manager.set_user_filepath(user_id, v_filepath)
            
        if self.settings.get("recording_mode", "split") == "append":
            if 'segments' not in self.writers[user_id]:
                self.writers[user_id]['segments'] = []
            if not self.writers[user_id].get('segment_active', False):
                self.writers[user_id]['segment_active'] = True
                self.writers[user_id]['current_segment_start'] = int(time.time() * 1000)
            
        self.writers[user_id]['writer'].write_packet(payload)
        AudioMixer.get_instance().add_packet(user_id, payload)

    def on_error(self, err):
        logger.error(f"Frida Error: {err}")
