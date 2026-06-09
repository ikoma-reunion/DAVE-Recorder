import os
import sys
import json
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'src'))

from gui.user_card import UserCard
from gui.main_window import MainWindow
from core.settings import SettingsManager
from unittest.mock import MagicMock

def test_user_card(qtbot):
    card = UserCard("1234567890")
    qtbot.addWidget(card)
    
    assert card.is_recording is True
    assert card.username_label.text() == "1234567890"
    assert card.id_label.text() == "ID: 1234567890"
    
    profile = {
        "username": "TestUser",
        "global_name": "Test Global Name",
        "avatar_hash": "abcdef123456",
        "avatar_path": None
    }
    
    # Mock load_avatar
    mock_load_avatar = MagicMock()
    card.load_avatar = mock_load_avatar
    
    card.update_profile(profile)
    assert card.global_name_label.text() == "Test Global Name"
    assert card.username_label.text() == "@TestUser"
    assert card.id_label.text() == "ID: 1234567890"
    assert card.avatar_hash == "abcdef123456"
    mock_load_avatar.assert_called_once()
    
    card.set_speaking(True)
    assert card.is_speaking is True
    assert card.property("speaking") is True
    
    card.toggle_recording()
    assert card.is_recording is False
    assert card.record_btn.property("recording") is False
    
    # Test play mute toggle
    assert card.play_mute_btn.property("muted") is False
    card.toggle_play_mute()
    assert card.play_mute_btn.property("muted") is True
    assert card.play_mute_btn.text() == "🔇"

def test_main_window_integration(qtbot, monkeypatch):
    monkeypatch.setattr("gui.main_window.UserResolver.resolve_user", lambda self, uid: None)
    
    window = MainWindow()
    qtbot.addWidget(window)
    
    assert window.status_label.text() == "Select an instance to connect..."
    
    window.on_user_mapped(9999, "user_123")
    assert 9999 in window.ssrc_map
    assert "user_123" in window.user_cards
    
    window.on_user_speaking("user_123", True)
    card = window.user_cards["user_123"]
    assert card.is_speaking is True
    
    window._close_all_writers()

def test_cache_directory(qtbot, monkeypatch):
    SettingsManager._instance = None
    def mock_thread(target, args=(), daemon=True):
        class MockThreadObj:
            def start(self):
                target(*args)
        return MockThreadObj()
    monkeypatch.setattr("gui.main_window.threading.Thread", mock_thread)
    window = MainWindow()
    qtbot.addWidget(window)
    assert window.resolver.cache_dir == os.path.join(os.getcwd(), ".cache")

def test_fetch_on_packet_received(qtbot, monkeypatch):
    SettingsManager._instance = None
    def mock_thread(target, args=(), daemon=True):
        class MockThreadObj:
            def start(self):
                target(*args)
        return MockThreadObj()
    monkeypatch.setattr("gui.main_window.threading.Thread", mock_thread)
    window = MainWindow()
    qtbot.addWidget(window)
    
    def mock_thread(target, args=(), daemon=True):
        class MockThreadObj:
            def start(self):
                target(*args)
        return MockThreadObj()
        
    monkeypatch.setattr("gui.main_window.threading.Thread", mock_thread)
    
    mock_fetch = MagicMock()
    monkeypatch.setattr(window, "_fetch_user_info_thread", mock_fetch)
    
    window.on_user_mapped(1111, "user_fetch")
    mock_fetch.assert_called_once_with("user_fetch")
    
    mock_fetch.reset_mock()
    # First packet SHOULD NOT trigger fetch since it was already done
    window.on_packet_received(1111, b"dummy")
    mock_fetch.assert_not_called()
    
    # Second packet SHOULD NOT trigger fetch again
    window.on_packet_received(1111, b"dummy")
    mock_fetch.assert_not_called()

def test_fetch_on_speaking(qtbot, monkeypatch):
    SettingsManager._instance = None
    def mock_thread(target, args=(), daemon=True):
        class MockThreadObj:
            def start(self):
                target(*args)
        return MockThreadObj()
    monkeypatch.setattr("gui.main_window.threading.Thread", mock_thread)
    window = MainWindow()
    qtbot.addWidget(window)
    
    def mock_thread(target, args=(), daemon=True):
        class MockThreadObj:
            def start(self):
                target(*args)
        return MockThreadObj()
        
    monkeypatch.setattr("gui.main_window.threading.Thread", mock_thread)
    
    mock_fetch = MagicMock()
    monkeypatch.setattr(window, "_fetch_user_info_thread", mock_fetch)
    
    # Map user should trigger fetch immediately
    window.on_user_mapped(1111, "user_fetch")
    mock_fetch.assert_called_once_with("user_fetch")
    
    mock_fetch.reset_mock()
    # First speak SHOULD NOT trigger fetch
    window.on_user_speaking("user_fetch", True)
    mock_fetch.assert_not_called()
    
    # Second speak SHOULD NOT trigger fetch
    window.on_user_speaking("user_fetch", True)
    mock_fetch.assert_not_called()

def test_mute_persistence(qtbot, monkeypatch):
    SettingsManager._instance = None
    def mock_thread(target, args=(), daemon=True):
        class MockThreadObj:
            def start(self):
                target(*args)
        return MockThreadObj()
    monkeypatch.setattr("gui.main_window.threading.Thread", mock_thread)
    settings = SettingsManager.get_instance()
    settings.set("global_mute", True)
    settings.set("muted_users", ["muted_user_1"])
    
    window = MainWindow()
    qtbot.addWidget(window)
    
    assert window.mute_btn.property("muted") is True
    
    window.on_user_mapped(2222, "muted_user_1")
    window.on_user_mapped(3333, "unmuted_user_2")
    
    assert window.user_cards["muted_user_1"].is_recording is False
    assert window.user_cards["unmuted_user_2"].is_recording is True
    
    # Toggle and verify settings updated
    window.user_cards["unmuted_user_2"].toggle_recording()
    assert "unmuted_user_2" in settings.get("muted_users")
    
    window.toggle_global_mute()
    assert settings.get("global_mute") is False

def test_unresolved_packets_buffering(qtbot, tmp_path, monkeypatch):
    SettingsManager._instance = None
    settings = SettingsManager.get_instance()
    settings.set("save_directory", str(tmp_path))
    settings.set("resolve_user_info_via_api", True)
    
    window = MainWindow()
    qtbot.addWidget(window)
    window.resolver.cache = {}
    
    # Mock the fetch thread so it doesn't execute
    monkeypatch.setattr(window, "_fetch_user_info_thread", lambda uid: None)
    
    # Map the user but DO NOT put them in the cache yet
    window.on_user_mapped(8888, "user_unresolved")
    
    # Send a packet. Because cache is empty and resolve is True, it should buffer, not create a writer
    window.on_packet_received(8888, b"buffered_payload_1")
    window.on_packet_received(8888, b"buffered_payload_2")
    
    assert "user_unresolved" not in window.writers
    assert "user_unresolved" in window.unresolved_packets
    assert len(window.unresolved_packets["user_unresolved"]) == 2
    
    # Simulate API resolving the user
    window.resolver.cache["user_unresolved"] = {"username": "ResolvedUser"}
    window.on_user_info_resolved("user_unresolved", {"username": "ResolvedUser"})
    
    # The buffer should be flushed, writer created, and buffer cleared
    assert "user_unresolved" not in window.unresolved_packets
    assert "user_unresolved" in window.writers
    
    # Cleanup
    window._close_all_writers()
    
    files = os.listdir(str(tmp_path))
    opus_files = [f for f in files if f.endswith(".opus")]
    assert len(opus_files) == 1
    assert "ResolvedUser" in opus_files[0]

class MockDiscordInstance:
    def __init__(self, pid, flavor):
        self.voice_pid = pid
        self.flavor = flavor

def test_auto_refresh_instances(qtbot, monkeypatch):
    SettingsManager._instance = None
    def mock_thread(target, args=(), daemon=True):
        class MockThreadObj:
            def start(self):
                target(*args)
        return MockThreadObj()
    monkeypatch.setattr("gui.main_window.threading.Thread", mock_thread)
    
    # We want to mock threading.Thread to just call the target synchronously for testing
    def mock_thread(target, args=(), daemon=True):
        class MockThreadObj:
            def start(self):
                target(*args)
        return MockThreadObj()
        
    monkeypatch.setattr("gui.main_window.threading.Thread", mock_thread)
    
    # Mock ProcessManager.get_discord_instances
    mock_instances = [MockDiscordInstance(1111, "Stable")]
    monkeypatch.setattr("gui.main_window.ProcessManager.get_discord_instances", lambda: mock_instances)
    
    window = MainWindow()
    qtbot.addWidget(window)
    
    # Initially should have 1 item
    assert window.instance_list.count() == 1
    assert window.instances[0].voice_pid == 1111
    
    # Now simulate a change in processes
    mock_instances = [MockDiscordInstance(2222, "PTB")]
    monkeypatch.setattr("gui.main_window.ProcessManager.get_discord_instances", lambda: mock_instances)
    
    # Trigger the refresh worker directly
    window.trigger_background_refresh()
    
    # It should emit the signal and update the list
    assert window.instance_list.count() == 1
    assert window.instances[0].voice_pid == 2222
    assert "PTB" in window.instance_list.item(0).text()

def test_recording_modes_split(qtbot, monkeypatch, tmp_path):
    SettingsManager._instance = None
    def mock_thread(target, args=(), daemon=True):
        class MockThreadObj:
            def start(self):
                target(*args)
        return MockThreadObj()
    monkeypatch.setattr("gui.main_window.threading.Thread", mock_thread)
    settings = SettingsManager.get_instance()
    settings.set("save_directory", str(tmp_path))
    settings.set("recording_mode", "split")

    window = MainWindow()
    qtbot.addWidget(window)

    from unittest.mock import MagicMock
    window.video_manager.close_user = MagicMock()

    window.on_user_mapped(1234, "user_split")
    window.on_packet_received(1234, b"dummy")
    assert "user_split" in window.writers

    # In split mode, stopping speaking closes the writer
    window.on_user_speaking("user_split", False)
    assert "user_split" not in window.writers
    window.video_manager.close_user.assert_called_with("user_split")

    files = os.listdir(str(tmp_path))
    opus_files = [f for f in files if f.endswith(".opus")]
    assert len(opus_files) == 1
    assert "-" in opus_files[0]

def test_video_sync_integration(qtbot, monkeypatch, tmp_path):
    SettingsManager._instance = None
    def mock_thread(target, args=(), daemon=True):
        class MockThreadObj:
            def start(self):
                target(*args)
        return MockThreadObj()
    monkeypatch.setattr("gui.main_window.threading.Thread", mock_thread)
    settings = SettingsManager.get_instance()
    settings.set("save_directory", str(tmp_path))
    settings.set("record_video", True)

    window = MainWindow()
    qtbot.addWidget(window)
    
    # We do NOT mock VideoManager here, we want a real integration test
    # 1. Packet triggers new session creation
    window.on_user_mapped(1234, "test_video_user")
    window.on_packet_received(1234, b"dummy")
    
    assert "test_video_user" in window.writers
    v_path = window.video_manager.user_filepaths.get("test_video_user")
    assert v_path is not None
    assert v_path.endswith("_ongoing.h264")
    
    # Feed a fake video frame so the file is actually opened
    window.video_manager.on_h264_frame("test_video_user", b'\x00\x00\x00\x01\x07dummy', is_keyframe=True)
    assert os.path.exists(v_path)
    
    # 2. User info resolution triggers rename
    profile = {
        "username": "ResolvedUser",
        "global_name": "Resolved Name",
        "avatar_hash": None,
        "avatar_path": None
    }
    
    window.on_user_info_resolved("test_video_user", profile)
    
    # Check if renamed
    new_v_path = window.video_manager.user_filepaths.get("test_video_user")
    assert new_v_path != v_path
    assert new_v_path.endswith("_ongoing.h264")
    assert "ResolvedUser" in new_v_path
    assert os.path.exists(new_v_path)
    
    # 3. Closing session triggers timestamping
    window._close_writer("test_video_user")
    
    # The file should be renamed to not have _ongoing
    found = False
    for f in os.listdir(str(tmp_path)):
        if f.endswith(".h264") and not f.endswith("_ongoing.h264"):
            found = True
            break
    assert found

def test_recording_modes_append(qtbot, monkeypatch, tmp_path):
    SettingsManager._instance = None
    def mock_thread(target, args=(), daemon=True):
        class MockThreadObj:
            def start(self):
                target(*args)
        return MockThreadObj()
    monkeypatch.setattr("gui.main_window.threading.Thread", mock_thread)
    settings = SettingsManager.get_instance()
    settings.set("save_directory", str(tmp_path))
    settings.set("recording_mode", "append")

    window = MainWindow()
    qtbot.addWidget(window)

    from unittest.mock import MagicMock
    window.video_manager.close_user = MagicMock()

    window.on_user_mapped(5678, "user_append")
    window.on_packet_received(5678, b"dummy")

    # Send a speech segment
    window.on_user_speaking("user_append", True)
    time.sleep(0.01)
    window.on_user_speaking("user_append", False)
    assert "user_append" in window.writers

    # Send another speech segment
    window.on_user_speaking("user_append", True)
    time.sleep(0.01)

    # Simulate inactivity
    window.writer_last_seen["user_append"] = time.time() - 2.0
    window.check_inactivity()
    assert "user_append" in window.writers

    # Disconnect
    if hasattr(window, "on_user_disconnected"):
        window.on_user_disconnected("user_append")
    else:
        # Fallback to simulate manual close if method not yet implemented
        window._close_writer("user_append")

    assert "user_append" not in window.writers
    window.video_manager.close_user.assert_called_with("user_append")    
    files = os.listdir(str(tmp_path))
    opus_files = [f for f in files if f.endswith(".opus")]
    json_files = [f for f in files if f.endswith(".json")]
    
    assert len(opus_files) == 1
    assert len(json_files) == 1
    
    with open(os.path.join(str(tmp_path), json_files[0]), 'r') as f:
        data = json.load(f)
        assert isinstance(data, list)
        assert len(data) == 2
        assert "start" in data[0]
        assert "end" in data[0]
