import sys
import os
import time
import frida
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from core.process_manager import ProcessManager

def on_message(message, data):
    if message['type'] == 'send':
        print(message['payload'])
    elif message['type'] == 'error':
        print(message['stack'])
    else:
        print(message)

if __name__ == "__main__":
    pm = ProcessManager()
    instances = pm.get_discord_instances()
    ptbs = [i for i in instances if i.flavor == "PTB" and i.is_valid()]
    if not ptbs:
        print("No valid Discord PTB instance found.")
        sys.exit(1)
    
    inst = ptbs[0]
    print(f"Attaching to Discord PTB Voice PID: {inst.voice_pid}")
    
    try:
        session = frida.attach(inst.voice_pid)
    except Exception as e:
        print(f"Failed to attach: {e}")
        sys.exit(1)
        
    script_path = os.path.join(os.path.dirname(__file__), 'trace_video.js')
    with open(script_path, 'r', encoding='utf-8') as f:
        code = f.read()
        
    script = session.create_script(code)
    script.on('message', on_message)
    script.load()
    
    print("Script loaded. Press Ctrl+C to exit.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        session.detach()
