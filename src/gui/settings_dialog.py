from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QCheckBox, QFileDialog, QFormLayout, QComboBox)
from core.settings import SettingsManager

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setFixedSize(450, 350)
        self.setStyleSheet("background-color: #313338; color: white;")
        self.settings = SettingsManager.get_instance()
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        
        form_layout = QFormLayout()
        
        # Save Directory
        self.dir_input = QLineEdit(str(self.settings.get("save_directory")))
        self.dir_input.setStyleSheet("background-color: #1E1F22; border: 1px solid #4E5058; padding: 4px; border-radius: 4px;")
        dir_btn = QPushButton("Browse")
        dir_btn.setStyleSheet("background-color: #5865F2; border-radius: 4px; padding: 4px;")
        dir_btn.clicked.connect(self.browse_directory)
        
        dir_layout = QHBoxLayout()
        dir_layout.addWidget(self.dir_input)
        dir_layout.addWidget(dir_btn)
        form_layout.addRow("Save Directory:", dir_layout)
        
        # Filename Format
        self.format_input = QLineEdit(str(self.settings.get("filename_format")))
        self.format_input.setStyleSheet("background-color: #1E1F22; border: 1px solid #4E5058; padding: 4px; border-radius: 4px;")
        self.format_input.setToolTip("Available tags: {user_id}, {username}, {global_name}, {date}, {time}")
        form_layout.addRow("Filename Format:", self.format_input)
        
        # Recording Mode
        self.recording_mode_combo = QComboBox()
        self.recording_mode_combo.addItem("Split by speech (Default)", "split")
        self.recording_mode_combo.addItem("Append (One file per user)", "append")
        
        current_mode = str(self.settings.get("recording_mode", "split"))
        index = self.recording_mode_combo.findData(current_mode)
        if index >= 0:
            self.recording_mode_combo.setCurrentIndex(index)
        self.recording_mode_combo.setStyleSheet("background-color: #1E1F22; border: 1px solid #4E5058; padding: 4px; border-radius: 4px;")
        form_layout.addRow("Recording Mode:", self.recording_mode_combo)
        
        # Record Video
        self.record_video_checkbox = QCheckBox("Save H.264 Video Streams (Requires restarting screen share)")
        self.record_video_checkbox.setChecked(bool(self.settings.get("record_video", True)))
        form_layout.addRow("", self.record_video_checkbox)
        
        # VaultCord API
        self.vaultcord_checkbox = QCheckBox("Use VaultCord API for names/avatars")
        self.vaultcord_checkbox.setChecked(bool(self.settings.get("resolve_user_info_via_api")))
        form_layout.addRow("", self.vaultcord_checkbox)
        
        # Log Level
        self.log_level_combo = QComboBox()
        self.log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
        self.log_level_combo.setStyleSheet("background-color: #1E1F22; border: 1px solid #4E5058; padding: 4px; border-radius: 4px;")
        current_level = str(self.settings.get("log_level", "INFO")).upper()
        self.log_level_combo.setCurrentText(current_level)
        form_layout.addRow("Log Level:", self.log_level_combo)
        
        layout.addLayout(form_layout)
        layout.addStretch()
        
        # Buttons
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.setStyleSheet("background-color: #23a559; border-radius: 4px; padding: 8px; font-weight: bold;")
        save_btn.clicked.connect(self.save_settings)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet("background-color: #4E5058; border-radius: 4px; padding: 8px; font-weight: bold;")
        cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)

    def browse_directory(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Save Directory", self.dir_input.text())
        if dir_path:
            self.dir_input.setText(dir_path)

    def save_settings(self):
        self.settings.set("save_directory", self.dir_input.text())
        self.settings.set("filename_format", self.format_input.text())
        self.settings.set("recording_mode", self.recording_mode_combo.currentData())
        self.settings.set("record_video", self.record_video_checkbox.isChecked())
        self.settings.set("resolve_user_info_via_api", self.vaultcord_checkbox.isChecked())
        self.settings.set("log_level", self.log_level_combo.currentText())
        self.accept()