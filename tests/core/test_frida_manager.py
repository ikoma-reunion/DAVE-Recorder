from unittest.mock import MagicMock
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'src'))

from core.frida_manager import FridaManager

def test_frida_manager_video_signals(qtbot):
    fm = FridaManager(1234, "fake_dir")
    
    # Mock to catch signals
    mock_decoder_frame = MagicMock()
    mock_sink_user = MagicMock()
    
    fm.video_decoder_frame.connect(mock_decoder_frame)
    fm.video_sink_user.connect(mock_sink_user)
    
    # Simulate a video sink message
    sink_msg = {
        'type': 'send',
        'payload': {
            'type': 'video_sink',
            'userId': '123456789'
        }
    }
    fm._on_voice_message(sink_msg, None)
    mock_sink_user.assert_called_once_with('123456789')
    
    # Simulate a h264 frame message
    frame_msg = {
        'type': 'send',
        'payload': {
            'type': 'h264_frame',
            'decoder': '0x1234ABCD'
        }
    }
    dummy_data = b'\x00\x00\x00\x01\x67\x42'
    fm._on_voice_message(frame_msg, dummy_data)
    mock_decoder_frame.assert_called_once_with('0x1234ABCD', dummy_data, False)

def test_frida_manager_dynamic_user_mapping(qtbot):
    fm = FridaManager(1234, "fake_dir")
    
    mock_user_mapped = MagicMock()
    fm.user_mapped.connect(mock_user_mapped)
    
    # Simulate a dynamic user_mapped message
    mapped_msg = {
        'type': 'send',
        'payload': {
            'type': 'mapping',
            'ssrc': 1234567,
            'userId': '987654321'
        }
    }
    
    fm._on_voice_message(mapped_msg, None)
    mock_user_mapped.assert_called_once_with(1234567, '987654321')
