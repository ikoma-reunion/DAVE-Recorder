import os
import time
import logging
import threading
from datetime import datetime
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                               QLabel, QListWidget, QListWidgetItem, QScrollArea, 
                               QGridLayout, QMessageBox, QPushButton, QFrame)
from PySide6.QtCore import Qt, Slot, QTimer, Signal
from PySide6.QtGui import QFont

from core.process_manager import ProcessManager
from core.frida_manager import FridaManager
from core.user_resolver import UserResolver
from core.ogg_writer import OggOpusWriter
from core.settings import SettingsManager
from core.audio_player import AudioMixer
from core.video_manager import VideoManager
from gui.settings_dialog import SettingsDialog

logger = logging.getLogger(__name__)

class MainWindow(QMainWindow):
    user_info_resolved = Signal(str, dict)
    instances_refreshed = Signal(list)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Dave Recorder")
        self.resize(1280, 720)
        self.setStyleSheet("background-color: #313338; color: white; border: none;")

        self.settings = SettingsManager.get_instance()
        cache_dir = os.path.join(os.getcwd(), ".cache")
        self.resolver = UserResolver(cache_dir)

        self.frida_manager = None
        self.video_manager = VideoManager(os.path.abspath(str(self.settings.get("save_directory"))))
        self.instances = []
        self.user_cards = {} # userId -> UserCard
        self.writers = {} # userId -> dict with writer, filename, start_time
        self.writer_last_seen = {} # userId -> timestamp
        self.ssrc_map = {} # SSRC -> userId
        self.unmapped_ssrcs = {} # SSRC -> last_seen_time
        self.unmapped_packets = {} # SSRC -> list of payloads
        self.unresolved_packets = {} # userId -> list of payloads
        self.recent_speakers = {} # userId -> timestamp
        self.fetched_users = set()
        self.is_running = True

        self.inactivity_timer = QTimer(self)
        self.inactivity_timer.timeout.connect(self.check_inactivity)
        self.inactivity_timer.start(500)

        self.user_info_resolved.connect(self.on_user_info_resolved)
        self.instances_refreshed.connect(self.on_instances_refreshed)

        self.init_ui()
        self.trigger_background_refresh()

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.trigger_background_refresh)
        self.refresh_timer.start(5000)

        is_muted = bool(self.settings.get("global_mute", False))
        self.mute_btn.setProperty("muted", is_muted)
        self.mute_btn.setText("🔇 Global Muted" if is_muted else "🔊 Global Unmuted")
        self.mute_btn.style().unpolish(self.mute_btn)
        self.mute_btn.style().polish(self.mute_btn)
        AudioMixer.get_instance().set_global_mute(is_muted)

    def trigger_background_refresh(self):
        threading.Thread(target=self._refresh_worker, daemon=True).start()

    def _refresh_worker(self):
        instances = ProcessManager.get_discord_instances()
        self.instances_refreshed.emit(instances)

    @Slot(list)
    def on_instances_refreshed(self, instances):
        current_pids = {i.voice_pid for i in self.instances}
        new_pids = {i.voice_pid for i in instances}

        if current_pids != new_pids:
            self.instances = instances
            self.instance_list.clear()
            for idx, inst in enumerate(self.instances):
                item = QListWidgetItem(f"# {inst.flavor} (PID: {inst.voice_pid})")
                item.setData(Qt.ItemDataRole.UserRole, idx)
                self.instance_list.addItem(item)
        is_muted = bool(self.settings.get("global_mute", False))
        self.mute_btn.setProperty("muted", is_muted)
        self.mute_btn.setText("🔇 Global Muted" if is_muted else "🔊 Global Unmuted")
        self.mute_btn.style().unpolish(self.mute_btn)
        self.mute_btn.style().polish(self.mute_btn)
        AudioMixer.get_instance().set_global_mute(is_muted)

    def _fetch_user_info_thread(self, user_id):
        info = self.resolver.resolve_user(user_id)
        if info:
            self.user_info_resolved.emit(user_id, info)
        else:
            self.user_info_resolved.emit(user_id, {})

    @Slot(str, dict)
    def on_user_info_resolved(self, user_id, info):
        if not info:
            self.resolver.cache[user_id] = {}
        else:
            card = self.user_cards.get(user_id)
            if card:
                card.update_profile(info)

            if user_id in self.writers:
                w_info = self.writers[user_id]
                new_filename = self._generate_filepath(user_id, "opus", "_ongoing")
                if w_info['filename'] != new_filename:
                    w_info['writer'].set_filename(new_filename)
                    w_info['filename'] = new_filename

            if self.settings.get("record_video", True):
                if user_id in self.video_manager.user_filepaths:
                    new_video_filename = self._generate_filepath(user_id, "h264", "_ongoing")
                    self.video_manager.rename_user(user_id, new_video_filename)
                
        if user_id in self.unresolved_packets:
            import logging
            logging.getLogger(__name__).info(f"Flushing {len(self.unresolved_packets[user_id])} buffered packets for resolved user {user_id}")
            for ssrc, payload in self.unresolved_packets[user_id]:
                self._process_packet(user_id, ssrc, payload)
            del self.unresolved_packets[user_id]

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
        end_time_str = datetime.now().strftime("%H%M%S")

        if user_id in self.writers:
            w_info = self.writers[user_id]
            w_info['writer'].close()
            
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
            new_video_path = old_video_path.replace("_ongoing.h264", f"-{end_time_str}.h264")
            try:
                if os.path.exists(old_video_path):
                    os.rename(old_video_path, new_video_path)
                    logger.info(f"Renamed video recording for {user_id}: {new_video_path}")
            except Exception as e:
                logger.error(f"Failed to rename video file {old_video_path}: {e}")

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        server_bar = QFrame()
        server_bar.setFixedWidth(72)
        server_bar.setStyleSheet("background-color: #1E1F22;")
        server_layout = QVBoxLayout(server_bar)
        server_layout.setContentsMargins(12, 12, 12, 12)
        server_layout.setSpacing(8)
        server_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        home_btn = QPushButton("DR")
        home_btn.setFixedSize(48, 48)
        home_btn.setStyleSheet("""
            QPushButton {
                background-color: #5865F2;
                color: white;
                font-weight: bold;
                border-radius: 16px;
            }
            QPushButton:hover {
                border-radius: 12px;
                background-color: #4752C4;
            }
        """)
        server_layout.addWidget(home_btn)
        
        separator = QFrame()
        separator.setFixedHeight(2)
        separator.setStyleSheet("background-color: #35363C; border-radius: 1px; margin: 0 8px;")
        server_layout.addWidget(separator)

        self.server_layout = server_layout
        main_layout.addWidget(server_bar)
        
        sidebar = QFrame()
        sidebar.setFixedWidth(240)
        sidebar.setStyleSheet("background-color: #2B2D31;")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)
        
        sidebar_header = QFrame()
        sidebar_header.setFixedHeight(48)
        sidebar_header.setStyleSheet("border-bottom: 1px solid #1E1F22;")
        sidebar_header_layout = QHBoxLayout(sidebar_header)
        sidebar_title = QLabel("Instances")
        sidebar_title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        sidebar_title.setStyleSheet("color: white;")
        sidebar_header_layout.addWidget(sidebar_title)
        sidebar_layout.addWidget(sidebar_header)
        
        self.instance_list = QListWidget()
        self.instance_list.setStyleSheet("""
            QListWidget { 
                border: none; 
                background-color: transparent; 
                padding: 8px;
            }
            QListWidget::item { 
                padding: 6px 8px; 
                border-radius: 4px; 
                color: #949BA4;
                font-family: "Segoe UI";
                font-size: 14px;
            }
            QListWidget::item:selected { 
                background-color: #404249; 
                color: white;
            }
            QListWidget::item:hover:!selected { 
                background-color: #35373C; 
                color: #DBDEE1;
            }
        """)
        self.instance_list.itemClicked.connect(self.on_instance_selected)
        sidebar_layout.addWidget(self.instance_list)
        
        sidebar_footer = QFrame()
        sidebar_footer.setFixedHeight(84)
        sidebar_footer.setStyleSheet("background-color: #232428;")
        footer_layout = QVBoxLayout(sidebar_footer)
        footer_layout.setContentsMargins(8, 8, 8, 8)
        footer_layout.setSpacing(4)
        
        self.mute_btn = QPushButton("🔊 Global Unmuted")
        self.mute_btn.setFixedHeight(32)
        self.mute_btn.setStyleSheet("""
            QPushButton {
                background-color: #2b2d31;
                color: #B5BAC1;
                border: 1px solid #1E1F22;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton[muted="true"] {
                background-color: #da373c;
                color: white;
            }
        """)
        self.mute_btn.setProperty("muted", False)
        self.mute_btn.clicked.connect(self.toggle_global_mute)
        footer_layout.addWidget(self.mute_btn)
        
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setFixedHeight(32)
        refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #B5BAC1;
                border: 1px solid #4E5058;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4E5058;
                color: white;
            }
        """)
        refresh_btn.clicked.connect(self.refresh_instances)
        
        settings_btn = QPushButton("Settings")
        settings_btn.setFixedHeight(32)
        settings_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #B5BAC1;
                border: 1px solid #4E5058;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4E5058;
                color: white;
            }
        """)
        settings_btn.clicked.connect(self.open_settings)
        
        btn_layout.addWidget(refresh_btn)
        btn_layout.addWidget(settings_btn)
        footer_layout.addLayout(btn_layout)
        sidebar_layout.addWidget(sidebar_footer)
        
        main_layout.addWidget(sidebar)
        
        main_area = QFrame()
        main_area.setStyleSheet("background-color: #313338;")
        main_area_layout = QVBoxLayout(main_area)
        main_area_layout.setContentsMargins(0, 0, 0, 0)
        main_area_layout.setSpacing(0)
        
        main_header = QFrame()
        main_header.setFixedHeight(48)
        main_header.setStyleSheet("border-bottom: 1px solid #1E1F22;")
        main_header_layout = QHBoxLayout(main_header)
        self.status_label = QLabel("Select an instance to connect...")
        self.status_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self.status_label.setStyleSheet("color: white;")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_header_layout.addWidget(self.status_label)
        main_area_layout.addWidget(main_header)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea { border: none; background-color: transparent; }
            QScrollBar:vertical {
                background: #2B2D31;
                width: 14px;
                margin: 0px;
                border-radius: 7px;
            }
            QScrollBar::handle:vertical {
                background: #1A1B1E;
                min-height: 20px;
                border-radius: 7px;
                margin: 2px;
            }
        """)
        
        self.grid_widget = QWidget()
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.grid_layout.setSpacing(16)
        self.grid_layout.setContentsMargins(24, 24, 24, 24)
        scroll.setWidget(self.grid_widget)
        
        main_area_layout.addWidget(scroll)
        main_layout.addWidget(main_area)

    def toggle_global_mute(self):
        is_muted = self.mute_btn.property("muted")
        new_state = not is_muted
        self.mute_btn.setProperty("muted", new_state)
        self.mute_btn.setText("🔇 Global Muted" if new_state else "🔊 Global Unmuted")
        self.mute_btn.style().unpolish(self.mute_btn)
        self.mute_btn.style().polish(self.mute_btn)
        AudioMixer.get_instance().set_global_mute(new_state)
        self.settings.set("global_mute", new_state)

    def refresh_instances(self):
        self.instance_list.clear()
        self.instances = ProcessManager.get_discord_instances()
        for idx, inst in enumerate(self.instances):
            item = QListWidgetItem(f"# {inst.flavor} (PID: {inst.voice_pid})")
            item.setData(Qt.ItemDataRole.UserRole, idx)
            self.instance_list.addItem(item)
            
    def open_settings(self):
        dialog = SettingsDialog(self)
        dialog.exec()

    def on_instance_selected(self, item):
        try:
            idx = item.data(Qt.ItemDataRole.UserRole)
            if idx is None:
                return
            inst = self.instances[idx]
            
            if self.frida_manager and self.frida_manager.running:
                self.frida_manager.stop()
                self._close_all_writers()
                
            self.status_label.setText(f"Connected: {inst.flavor} Voice Channel")
            
            for i in reversed(range(self.grid_layout.count())): 
                layout_item = self.grid_layout.itemAt(i)
                if layout_item:
                    widget = layout_item.widget()
                    if widget:
                        widget.setParent(None)
            self.user_cards.clear()
            self.ssrc_map.clear()
            self.unmapped_ssrcs.clear()
            self.recent_speakers.clear()
            
            scripts_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'src', 'frida_scripts')
            self.frida_manager = FridaManager(inst.voice_pid, scripts_dir)
            
            self.frida_manager.user_mapped.connect(self.on_user_mapped)
            self.frida_manager.user_speaking.connect(self.on_user_speaking)
            self.frida_manager.user_disconnected.connect(self.on_user_disconnected)
            self.frida_manager.packet_received.connect(self.on_packet_received)
            self.frida_manager.video_decoder_frame.connect(self.on_video_decoder_frame)
            self.frida_manager.error_occurred.connect(self.on_error)
            
            self.frida_manager.start()
        except Exception as e:
            import traceback
            logger.error(f"Error in on_instance_selected: {e}\\n{traceback.format_exc()}")
            QMessageBox.critical(self, "Critical Error", f"Failed to attach:\\n{e}")

    @Slot(str, bytes, bool)
    def on_video_decoder_frame(self, decoder: str, payload: bytes, is_keyframe: bool):
        if not self.settings.get("record_video", True):
            return
        self.video_manager.on_h264_frame(decoder, payload, is_keyframe)

    @Slot(str)
    def on_video_sink_user(self, user_id: str):
        if not self.settings.get("record_video", True):
            return
        filepath = self._generate_filepath(user_id, "h264")
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        self.video_manager.on_video_sink(user_id, filepath)

    @Slot(str)
    def on_user_disconnected(self, user_id):
        card = self.user_cards.get(user_id)
        if card:
            card.set_disconnected(True)
        self._close_writer(user_id)

    @Slot(int, str)
    def on_user_mapped(self, ssrc, user_id):
        if ssrc > 0:
            self.ssrc_map[ssrc] = user_id
            
        if user_id not in self.user_cards:
            from gui.user_card import UserCard
            card = UserCard(user_id, ssrc=ssrc)
            self.user_cards[user_id] = card
            count = self.grid_layout.count()
            self.grid_layout.addWidget(card, count // 4, count % 4)
            import logging
            logging.getLogger(__name__).info(f"Added UserCard for {user_id} (SSRC: {ssrc})")

        if ssrc in self.unmapped_packets:
            import logging
            logging.getLogger(__name__).info(f"Flushing {len(self.unmapped_packets[ssrc])} buffered packets for newly mapped user {user_id}")
            for payload in self.unmapped_packets[ssrc]:
                self.on_packet_received(ssrc, payload)
            del self.unmapped_packets[ssrc]

        if user_id not in self.fetched_users and self.settings.get("resolve_user_info_via_api"):
            self.fetched_users.add(user_id)
            threading.Thread(target=self._fetch_user_info_thread, args=(user_id,), daemon=True).start()

    @Slot(str, bool)
    def on_user_speaking(self, user_id, is_speaking):
        if user_id in self.user_cards:
            self.user_cards[user_id].set_speaking(is_speaking)
            card = self.user_cards[user_id]
            if card.is_disconnected:
                card.set_disconnected(False)
                
        if is_speaking:
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

    def _generate_filepath(self, user_id, extension, suffix=""):
        base_dir = os.path.abspath(str(self.settings.get("save_directory")))
        fmt = str(self.settings.get("filename_format"))
        
        # Remove any default extension from the format if present
        if fmt.endswith(".opus"):
            fmt = fmt[:-5]
        elif fmt.endswith(".h264"):
            fmt = fmt[:-5]
            
        fmt = f"{fmt}{suffix}.{extension}"
        
        now = datetime.now()
        card = self.user_cards.get(user_id) if hasattr(self, 'user_cards') else None
        uname = card.username if card else user_id
        gname = card.global_name if card and card.global_name else uname
        if uname.startswith("Unknown ("):
            uname = user_id
        if gname.startswith("Unknown ("):
            gname = user_id
            
        formatted = fmt.format(
            user_id=user_id,
            username=uname.lstrip('@'),
            global_name=gname,
            date=now.strftime("%Y%m%d"),
            time=now.strftime("%H%M%S")
        )
        return os.path.normpath(os.path.join(base_dir, formatted))

    @Slot(int, bytes)
    def on_packet_received(self, ssrc, payload):
        if payload == b"\xf8\xff\xfe":
            return
            
        if ssrc not in self.ssrc_map:
            if ssrc not in self.unmapped_packets:
                self.unmapped_packets[ssrc] = []
            self.unmapped_packets[ssrc].append(payload)
            if len(self.unmapped_packets[ssrc]) > 500:
                self.unmapped_packets[ssrc].pop(0)
            return
            
        user_id = self.ssrc_map[ssrc]
            
        card = self.user_cards.get(user_id)
        if card and not card.is_recording:
            return
            
        if card and not card.is_speaking:
            self.on_user_speaking(user_id, True)
            
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
            filepath = self._generate_filepath(user_id, "opus", "_ongoing")
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            
            logger.info(f"Started new recording session for user {user_id} at {filepath}")
            self.writers[user_id] = {
                'writer': OggOpusWriter(filepath, ssrc),
                'filename': filepath,
                'start_time': datetime.now().strftime("%H%M%S")
            }
            
            if self.settings.get("record_video", True):
                v_filepath = self._generate_filepath(user_id, "h264", "_ongoing")
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

    @Slot(str)
    def on_error(self, err):
        logger.error(f"Frida Error via signal: {err}")
        QMessageBox.warning(self, "Frida Error", err)

    def _close_all_writers(self):
        for user_id in list(self.writers.keys()):
            self._close_writer(user_id)

    def closeEvent(self, event):
        self.is_running = False
        if hasattr(self, 'inactivity_timer'):
            self.inactivity_timer.stop()
        if hasattr(self, 'refresh_timer'):
            self.refresh_timer.stop()
        if self.frida_manager:
            self.frida_manager.stop()
        self.video_manager.stop()
        self._close_all_writers()
        from core.audio_player import AudioMixer
        AudioMixer.get_instance().stop()
        super().closeEvent(event)
