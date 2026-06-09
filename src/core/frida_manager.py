import os
import logging
import frida
from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)

class FridaManager(QObject):
    # Signals for GUI integration
    user_mapped = Signal(int, str) # SSRC, UserID
    user_speaking = Signal(str, bool) # UserID, is_speaking
    user_disconnected = Signal(str) # UserID
    packet_received = Signal(int, bytes) # SSRC, payload
    video_decoder_frame = Signal(str, bytes, bool) # DecoderInstance, payload, is_keyframe
    video_sink_user = Signal(str) # UserID
    error_occurred = Signal(str)

    def __init__(self, voice_pid, scripts_dir):
        super().__init__()
        self.voice_pid = voice_pid
        self.scripts_dir = scripts_dir
        self.voice_session = None
        self.running = False
        
    def start(self):
        logger.info(f"Starting FridaManager. Voice PID: {self.voice_pid}")
        try:
            # Attach to Voice
            self.voice_session = frida.attach(self.voice_pid)
            logger.debug("Attached to voice process.")
            with open(os.path.join(self.scripts_dir, 'voice_hook.js'), 'r', encoding='utf-8') as f:
                v_code = f.read()
            v_script = self.voice_session.create_script(v_code)
            v_script.on('message', self._on_voice_message)
            v_script.load()
            logger.debug("Loaded voice_hook.js")
            
            self.running = True
            logger.info("FridaManager started successfully.")
            
        except Exception as e:
            logger.error(f"Frida attach failed: {e}")
            self.error_occurred.emit(f"Frida attach failed: {e}")
            
    def stop(self):
        logger.info("Stopping FridaManager...")
        self.running = False
        try:
            if self.voice_session:
                self.voice_session.detach()
        except Exception as e:
            import traceback
            import sys
            logger.error(f"Error during detach: {e}\n{traceback.format_exc()}")
            sys.exit(1)

    def _on_voice_message(self, message, data):
        if message['type'] == 'send':
            payload = message['payload']

            if isinstance(payload, str):
                logger.info(f"[Frida Log] {payload}")
                return

            ptype = payload.get('type')
            
            if ptype == 'log':
                logger.info(f"[Frida Voice] {payload.get('message')}")
                
            elif ptype == 'status':
                logger.info(f"[Frida Voice Status] {payload.get('message')}")

            elif ptype == 'mapping':
                ssrc = payload['ssrc']
                user_id = payload['userId']
                logger.info(f"User mapped: SSRC={ssrc}, UserID={user_id}")
                self.user_mapped.emit(ssrc, user_id)
                
            elif ptype == 'speaking':
                logger.debug(f"User speaking: UserID={payload['userId']}, is_speaking={payload['is_speaking']}")
                self.user_speaking.emit(payload['userId'], payload['is_speaking'])

            elif ptype == 'disconnect':
                logger.info(f"User disconnected: UserID={payload['userId']}")
                self.user_disconnected.emit(payload['userId'])
                
            elif ptype == 'payload':
                ssrc = payload['ssrc']
                if data:
                    self.packet_received.emit(ssrc, data)
                    
            elif ptype == 'video_sink':
                user_id = payload['userId']
                logger.info(f"Video sink attached for UserID={user_id}")
                self.video_sink_user.emit(user_id)
                
            elif ptype == 'h264_frame':
                user_id_or_decoder = payload.get('userId') or payload.get('decoder')
                is_keyframe = payload.get('is_keyframe', False)
                if data and user_id_or_decoder:
                    self.video_decoder_frame.emit(user_id_or_decoder, data, is_keyframe)
                    
        elif message['type'] == 'error':
            logger.error(f"[Frida Voice Error] {message['description']}")
            self.error_occurred.emit(message['description'])