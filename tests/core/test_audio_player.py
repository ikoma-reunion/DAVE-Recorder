import os
import sys
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'src'))

from core.audio_player import AudioMixer, UserAudioStream

def test_user_audio_stream_init():
    stream = UserAudioStream("test_user")
    assert stream.user_id == "test_user"
    assert stream.volume == 1.0
    assert len(stream.buffer) == 0

def test_audio_mixer_singleton():
    AudioMixer._instance = None
    mixer1 = AudioMixer.get_instance()
    mixer2 = AudioMixer.get_instance()
    assert mixer1 is mixer2
    mixer1.stop()

def test_audio_mixer_volume():
    AudioMixer._instance = None
    mixer = AudioMixer.get_instance()
    
    # It shouldn't crash if packet is invalid, but add_packet creates stream
    mixer.add_packet("vol_user", b"invalid_packet")
    assert "vol_user" in mixer.streams
    
    mixer.set_volume("vol_user", 1.5)
    assert mixer.streams["vol_user"].volume == 1.5
    
    mixer.remove_user("vol_user")
    assert "vol_user" not in mixer.streams
    
    mixer.stop()

def test_audio_mixer_callback():
    AudioMixer._instance = None
    mixer = AudioMixer.get_instance()
    
    mixer.add_packet("test_user_1", b"") # Create stream
    stream = mixer.streams["test_user_1"]
    
    # Manually inject some mock PCM data into the buffer
    mock_pcm = np.ones((960, 2), dtype=np.float32) * 0.5
    stream.buffer.append(mock_pcm)
    stream.volume = 0.5 # Expect output to be 0.25
    
    outdata = np.zeros((960, 2), dtype=np.float32)
    mixer.stream.callback(outdata, 960, None, None)
    
    assert np.allclose(outdata, 0.25)
    assert len(stream.buffer) == 0 # Buffer consumed
    
    # Test individual user mute
    mock_pcm2 = np.ones((960, 2), dtype=np.float32) * 0.5
    stream.buffer.append(mock_pcm2)
    mixer.set_user_mute("test_user_1", True)
    
    outdata2 = np.zeros((960, 2), dtype=np.float32)
    mixer.stream.callback(outdata2, 960, None, None)
    
    assert np.allclose(outdata2, 0.0) # Should be completely silent
    assert len(stream.buffer) == 0 # Buffer should STILL be consumed to prevent leaks
    
    mixer.stop()