import threading
import logging
import numpy as np
import sounddevice as sd
import av

logger = logging.getLogger(__name__)

class UserAudioStream:
    def __init__(self, user_id):
        self.user_id = user_id
        self.codec = av.CodecContext.create('opus', 'r')
        
        self.buffer = [] # list of numpy arrays (interleaved float32)
        self.lock = threading.Lock()
        self.volume = 1.0
        self.is_muted = False

    def add_packet(self, payload):
        try:
            packet = av.Packet(payload)
            frames = self.codec.decode(packet)
            for frame in frames:
                # 'fltp' shape is (channels, samples). We want interleaved (samples, channels)
                arr = frame.to_ndarray().T.astype(np.float32)
                with self.lock:
                    self.buffer.append(arr)
        except Exception as e:
            logger.debug(f"Audio decode error for {self.user_id}: {e}")

    def get_audio(self, frames_needed):
        """Returns interleaved numpy array of shape (frames_needed, 2) or None if not enough data"""
        with self.lock:
            if not self.buffer:
                return None
                
            total_available = sum(arr.shape[0] for arr in self.buffer)
            if total_available < frames_needed:
                return None
                
            out = np.zeros((frames_needed, 2), dtype=np.float32)
            written = 0
            
            while written < frames_needed and self.buffer:
                arr = self.buffer[0]
                arr_frames = arr.shape[0]
                needed = frames_needed - written
                
                if arr_frames <= needed:
                    out[written:written+arr_frames] = arr
                    written += arr_frames
                    self.buffer.pop(0)
                else:
                    out[written:written+needed] = arr[:needed]
                    self.buffer[0] = arr[needed:]
                    written += needed
                    
            if self.is_muted:
                return None
            return out * self.volume

class AudioMixer:
    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = AudioMixer()
        return cls._instance

    def __init__(self):
        self.streams = {} # user_id -> UserAudioStream
        self.lock = threading.Lock()
        self.stream = None
        self.global_mute = False
        self._start_stream()

    def _start_stream(self):
        try:
            self.stream = sd.OutputStream(
                samplerate=48000,
                channels=2,
                dtype='float32',
                callback=self._audio_callback,
                blocksize=960 # 20ms at 48kHz
            )
            self.stream.start()
            logger.info("AudioMixer started successfully.")
        except Exception as e:
            logger.error(f"Failed to start AudioMixer: {e}")
            self.stream = None

    def add_packet(self, user_id, payload):
        if not self.stream:
            return
            
        with self.lock:
            if user_id not in self.streams:
                self.streams[user_id] = UserAudioStream(user_id)
            stream = self.streams[user_id]
            
        stream.add_packet(payload)

    def set_volume(self, user_id, volume):
        """Set volume (0.0 to 2.0 or higher)"""
        with self.lock:
            if user_id in self.streams:
                self.streams[user_id].volume = volume

    def set_user_mute(self, user_id, is_muted: bool):
        with self.lock:
            if user_id in self.streams:
                self.streams[user_id].is_muted = is_muted
            else:
                self.streams[user_id] = UserAudioStream(user_id)
                self.streams[user_id].is_muted = is_muted

    def set_global_mute(self, is_muted: bool):
        with self.lock:
            self.global_mute = is_muted

    def remove_user(self, user_id):
        with self.lock:
            if user_id in self.streams:
                del self.streams[user_id]

    def _audio_callback(self, outdata, frames, time_info, status):
        outdata.fill(0) # initialize to silence
        
        with self.lock:
            # Copy to avoid modification during iteration
            active_streams = list(self.streams.values())
            is_muted = self.global_mute
            
        for stream in active_streams:
            user_audio = stream.get_audio(frames)
            if user_audio is not None and not is_muted:
                outdata += user_audio
                
    def stop(self):
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
