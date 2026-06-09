import os
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QSlider, QHBoxLayout
from PySide6.QtGui import QPixmap, QImage, QColor, QPainter, QBrush
from PySide6.QtCore import Qt
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtCore import QUrl

from core.audio_player import AudioMixer
from core.settings import SettingsManager

class UserCard(QWidget):
    def __init__(self, user_id, ssrc=0):
        super().__init__()
        self.settings = SettingsManager.get_instance()
        self.user_id = user_id
        self.ssrc = ssrc
        
        muted_users = self.settings.get("muted_users", [])
        self.is_recording = user_id not in muted_users
        
        self.is_speaking = False
        self.is_disconnected = False
        self.username = f"Unknown ({user_id})"
        self.global_name = None
        self.avatar_hash = None
        
        self.network_manager = QNetworkAccessManager(self)
        self.network_manager.finished.connect(self._on_avatar_downloaded)
        
        self.init_ui()

    def init_ui(self):
        self.setFixedSize(200, 300) # Increased height slightly to fit SSRC
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("""
            UserCard {
                background-color: #2b2d31;
                border-radius: 8px;
                border: 2px solid transparent;
            }
            UserCard[speaking="true"] {
                border: 2px solid #23a559;
            }
            UserCard[disconnected="true"] {
                opacity: 0.5;
            }
            UserCard:hover {
                background-color: #313338;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Avatar Label
        self.avatar_label = QLabel(self)
        self.avatar_label.setFixedSize(80, 80)
        self.avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._set_default_avatar()
        layout.addWidget(self.avatar_label, alignment=Qt.AlignmentFlag.AlignCenter)

        # Global Name Label
        self.global_name_label = QLabel(self.username)
        self.global_name_label.setStyleSheet("color: white; font-weight: bold; font-size: 14px;")
        self.global_name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.global_name_label)

        # Username Label
        self.username_label = QLabel(self.user_id)
        self.username_label.setStyleSheet("color: #b5bac1; font-size: 12px;")
        self.username_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.username_label)
        
        # ID Label
        self.id_label = QLabel(f"ID: {self.user_id}")
        self.id_label.setStyleSheet("color: #80848E; font-size: 10px;")
        self.id_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.id_label)
        
        # SSRC Label
        self.ssrc_label = QLabel(f"SSRC: {self.ssrc}")
        self.ssrc_label.setStyleSheet("color: #80848E; font-size: 10px;")
        self.ssrc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.ssrc_label)

        layout.addStretch()

        # Volume Slider
        vol_layout = QHBoxLayout()
        vol_icon = QLabel("🔊")
        vol_icon.setStyleSheet("color: #b5bac1; font-size: 14px;")
        
        self.play_mute_btn = QPushButton("🔊")
        self.play_mute_btn.setFixedSize(24, 24)
        self.play_mute_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                font-size: 14px;
            }
            QPushButton[muted="true"] {
                color: #da373c;
            }
        """)
        self.play_mute_btn.setProperty("muted", False)
        self.play_mute_btn.clicked.connect(self.toggle_play_mute)
        
        self.vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 200)
        self.vol_slider.setValue(100)
        self.vol_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border-radius: 2px;
                height: 4px;
                background: #4f545c;
            }
            QSlider::handle:horizontal {
                background: #ffffff;
                width: 12px;
                height: 12px;
                margin: -4px 0;
                border-radius: 6px;
            }
            QSlider::sub-page:horizontal {
                background: #5865F2;
                border-radius: 2px;
            }
        """)
        self.vol_slider.valueChanged.connect(self.on_volume_changed)
        vol_layout.addWidget(self.play_mute_btn)
        vol_layout.addWidget(self.vol_slider)
        layout.addLayout(vol_layout)

        # Record Toggle Button
        self.record_btn = QPushButton("Recording: ON" if self.is_recording else "Recording: OFF")
        self.record_btn.setStyleSheet("""
            QPushButton {
                background-color: #23a559;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px;
                font-weight: bold;
            }
            QPushButton[recording="false"] {
                background-color: #da373c;
            }
        """)
        self.record_btn.setProperty("recording", self.is_recording)
        self.record_btn.clicked.connect(self.toggle_recording)
        layout.addWidget(self.record_btn)

    def on_volume_changed(self, value):
        AudioMixer.get_instance().set_volume(self.user_id, value / 100.0)

    def _set_default_avatar(self):
        # Draw a simple circle as default
        pixmap = QPixmap(80, 80)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(QColor("#5865f2"))) # Discord blurple
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(0, 0, 80, 80)
        painter.end()
        self.avatar_label.setPixmap(pixmap)

    def update_profile(self, profile_data):
        if profile_data.get('global_name'):
            self.global_name = profile_data['global_name']
            self.global_name_label.setText(self.global_name)
        if profile_data.get('username'):
            self.username = profile_data['username']
            if self.global_name:
                self.username_label.setText(f"@{self.username}")
            else:
                self.global_name_label.setText(self.username)
                self.username_label.setText(self.user_id)
                
        if profile_data.get('avatar_path') and os.path.exists(profile_data['avatar_path']):
            self.load_local_avatar(profile_data['avatar_path'])
        elif profile_data.get('avatar_hash'):
            self.avatar_hash = profile_data['avatar_hash']
            self.load_avatar()

    def load_local_avatar(self, path):
        img = QImage(path)
        if not img.isNull():
            self._apply_circle_mask(img)

    def load_avatar(self):
        if not self.avatar_hash:
            return
        # https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.png
        ext = "gif" if self.avatar_hash.startswith("a_") else "png"
        url = f"https://cdn.discordapp.com/avatars/{self.user_id}/{self.avatar_hash}.{ext}?size=128"
        req = QNetworkRequest(QUrl(url))
        self.network_manager.get(req)

    def _on_avatar_downloaded(self, reply):
        if reply.error() == QNetworkReply.NetworkError.NoError:
            data = reply.readAll()
            img = QImage.fromData(data)
            if not img.isNull():
                self._apply_circle_mask(img)
        reply.deleteLater()
        
    def _apply_circle_mask(self, img):
        pixmap = QPixmap.fromImage(img).scaled(80, 80, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        rounded = QPixmap(80, 80)
        rounded.fill(Qt.GlobalColor.transparent)
        painter = QPainter(rounded)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(pixmap))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(0, 0, 80, 80)
        painter.end()
        self.avatar_label.setPixmap(rounded)

    def set_speaking(self, is_speaking):
        self.is_speaking = is_speaking
        self.setProperty("speaking", is_speaking)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_disconnected(self, is_disconnected):
        self.is_disconnected = is_disconnected
        self.setProperty("disconnected", is_disconnected)
        self.style().unpolish(self)
        self.style().polish(self)

    def toggle_play_mute(self):
        is_muted = self.play_mute_btn.property("muted")
        new_state = not is_muted
        self.play_mute_btn.setProperty("muted", new_state)
        self.play_mute_btn.setText("🔇" if new_state else "🔊")
        self.play_mute_btn.style().unpolish(self.play_mute_btn)
        self.play_mute_btn.style().polish(self.play_mute_btn)
        AudioMixer.get_instance().set_user_mute(self.user_id, new_state)

    def toggle_recording(self):
        self.is_recording = not self.is_recording
        
        muted_users = self.settings.get("muted_users", [])
        if self.is_recording and self.user_id in muted_users:
            muted_users.remove(self.user_id)
            self.settings.set("muted_users", muted_users)
        elif not self.is_recording and self.user_id not in muted_users:
            muted_users.append(self.user_id)
            self.settings.set("muted_users", muted_users)
            
        self.record_btn.setProperty("recording", self.is_recording)
        self.record_btn.setText("Recording: ON" if self.is_recording else "Recording: OFF")
        self.record_btn.style().unpolish(self.record_btn)
        self.record_btn.style().polish(self.record_btn)