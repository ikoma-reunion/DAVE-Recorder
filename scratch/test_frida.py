import sys
import os
import time
import frida
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from core.process_manager import ProcessManager

def on_message(message, data):
    print(message)

if __name__ == "__main__":
    pm = ProcessManager()
    ptbs = [i for i in pm.get_discord_instances() if i.flavor == "PTB" and i.is_valid()]
    if not ptbs:
        print("No PTB")
        sys.exit(1)
    
    inst = ptbs[0]
    session = frida.attach(inst.voice_pid)
    
    code = """
    console.log("Process type:", typeof Process);
    const m = Process.getModuleByName('discord_voice.node');
    console.log("discord_voice.node base:", m.base);
    console.log("getExportByName type:", typeof m.getExportByName);
    """
    script = session.create_script(code)
    script.on('message', on_message)
    script.load()
    time.sleep(1)
    session.detach()