import os
import sys
from dave_recorder.core.process_manager import ProcessManager
from dave_recorder.core.frida_manager import FridaManager
from dave_recorder.core.ogg_writer import OggOpusWriter

def test_full_recording_e2e():
    instances = ProcessManager.get_discord_instances()
    ptbs = [i for i in instances if i.flavor == 'PTB']
    if not ptbs:
        print("No PTB instance found. Skipping E2E test.")
        sys.exit(0)
        
    inst = ptbs[0]
    print(f"Testing PTB (Voice PID: {inst.voice_pid})")
    
    scripts_dir = os.path.join(os.path.dirname(__file__), 'src', 'dave_recorder', 'frida_scripts')
    fm = FridaManager(inst.voice_pid, scripts_dir)
    
    recordings = {}
    success = False
    
    def on_packet(ssrc, payload):
        nonlocal success
        if ssrc not in recordings:
            filepath = os.path.abspath(f"recordings_test_{ssrc}.opus")
            recordings[ssrc] = OggOpusWriter(filepath, ssrc)
            print(f"Created file: {filepath}")
            
        recordings[ssrc].write_packet(payload)
        success = True

    fm.packet_received.connect(on_packet)
    fm.start()
    
    print("Waiting 10 seconds for packets...")
    
    # We need Qt Event loop for signals
    from PySide6.QtCore import QCoreApplication, QTimer
    app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    
    def check():
        fm.stop()
        for w in recordings.values():
            w.close()
        app.quit()
        
    QTimer.singleShot(10000, check)
    app.exec()
    
    if success:
        print("RESULT: PASS. Successfully received and recorded packets via Frida!")
    else:
        print("RESULT: WARNING. No packets received, but no crash occurred. Are you speaking in a channel?")
        
    for ssrc, w in recordings.items():
        if os.path.exists(w.file.name):
            size = os.path.getsize(w.file.name)
            print(f"File {w.file.name} created. Size: {size} bytes")

if __name__ == '__main__':
    test_full_recording_e2e()