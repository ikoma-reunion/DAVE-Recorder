import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'src'))

from cli.app import CliApp
from core.settings import SettingsManager

class MockSignal:
    def __init__(self):
        self.callbacks = []
    def connect(self, cb):
        self.callbacks.append(cb)
    def emit(self, *args, **kwargs):
        for cb in self.callbacks:
            cb(*args, **kwargs)

class MockFridaManager:
    def __init__(self, pid, scripts_dir):
        self.pid = pid
        self.scripts_dir = scripts_dir
        self.started = False
        self.stopped = False
        self.user_mapped = MockSignal()
        self.user_speaking = MockSignal()
        self.packet_received = MockSignal()
        self.video_decoder_frame = MockSignal()
        self.error_occurred = MockSignal()

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

class MockInstance:
    def __init__(self, flavor, voice_pid):
        self.flavor = flavor
        self.voice_pid = voice_pid

def test_cliapp_initialization():
    SettingsManager._instance = None
    instances = [MockInstance("Stable", 1234)]
    
    app = CliApp(instances, "test_scripts_dir")
    
    assert app.instances == instances
    assert app.scripts_dir == "test_scripts_dir"
    assert len(app.managers) == 0

def test_cliapp_run_and_stop(monkeypatch, tmp_path):
    SettingsManager._instance = None
    SettingsManager.get_instance().set("save_directory", str(tmp_path))
    SettingsManager.get_instance().set("recording_mode", "split")
    
    monkeypatch.setattr("cli.app.FridaManager", MockFridaManager)
    
    instances = [MockInstance("Stable", 1234)]
    app = CliApp(instances, "test_scripts_dir")
    
    app.start()
    assert len(app.managers) == 1
    assert app.managers[0].started is True
    
    manager = app.managers[0]
    manager.user_mapped.emit(100, "user_1")
    assert app.ssrc_map[100] == "user_1"
    
    manager.packet_received.emit(100, b"\xfc\xff\xfe")
    assert "user_1" in app.writers
    
    manager.user_speaking.emit("user_1", False)
    assert "user_1" not in app.writers 
    
    app.stop()
    assert manager.stopped is True

def test_cliapp_inactivity(monkeypatch, tmp_path):
    SettingsManager._instance = None
    SettingsManager.get_instance().set("save_directory", str(tmp_path))
    SettingsManager.get_instance().set("recording_mode", "split")
    
    monkeypatch.setattr("cli.app.FridaManager", MockFridaManager)
    
    instances = [MockInstance("Stable", 1234)]
    app = CliApp(instances, "test_scripts_dir")
    app.start()
    
    manager = app.managers[0]
    manager.user_mapped.emit(200, "user_3")
    manager.packet_received.emit(200, b"\xfc\xff\xfe")
    
    assert "user_3" in app.writers
    
    from unittest.mock import MagicMock
    app.video_manager.close_user = MagicMock()
    
    # Fast forward time
    app.writer_last_seen["user_3"] = time.time() - 2.0
    app.check_inactivity()
    
    assert "user_3" not in app.writers
    app.video_manager.close_user.assert_called_with("user_3")
    assert app.video_manager.close_user.call_count >= 1
    
    app.stop()
