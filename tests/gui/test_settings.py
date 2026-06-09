import os
import sys
import logging

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'src'))

from core.settings import SettingsManager
from gui.settings_dialog import SettingsDialog

def test_settings_dialog(qtbot):
    SettingsManager._instance = None # Reset singleton
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    
    dialog.log_level_combo.setCurrentText("DEBUG")
    dialog.save_settings()
    
    assert SettingsManager.get_instance().get("log_level") == "DEBUG"
    assert logging.getLogger().level == logging.DEBUG

def test_settings_removed_subfolders():
    SettingsManager._instance = None
    settings = SettingsManager.get_instance()
    assert settings.get("create_subfolders") is None
    dialog = SettingsDialog()
    assert not hasattr(dialog, "subfolder_checkbox")

def test_settings_recording_mode(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr("core.settings.SETTINGS_FILE", str(tmp_path / "test_settings.json"))
    SettingsManager._instance = None
    settings = SettingsManager.get_instance()
    assert settings.get("recording_mode") == "split"
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    assert hasattr(dialog, "recording_mode_combo")

def test_settings_mute_persistence():
    SettingsManager._instance = None
    settings = SettingsManager.get_instance()
    assert settings.get("global_mute") is False
    assert isinstance(settings.get("muted_users"), list)