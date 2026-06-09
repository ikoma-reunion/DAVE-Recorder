import pytest
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'src'))

class MockOutputStream:
    def __init__(self, *args, **kwargs):
        self.callback = kwargs.get('callback')
    def start(self): pass
    def stop(self): pass
    def close(self): pass

@pytest.fixture(autouse=True)
def mock_sounddevice(monkeypatch):
    monkeypatch.setattr("sounddevice.OutputStream", MockOutputStream)

@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    from core.settings import SettingsManager
    import core.settings
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir(exist_ok=True)
    test_settings_path = os.path.join(str(settings_dir), "test_settings.json")
    monkeypatch.setattr(core.settings, "SETTINGS_FILE", test_settings_path)
    SettingsManager._instance = None
    yield
    SettingsManager._instance = None
