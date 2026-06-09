import frida
import time
from dave_recorder.core.process_manager import ProcessManager

def run():
    ptbs = [i for i in ProcessManager.get_discord_instances() if i.flavor == 'PTB']
    if not ptbs:
        print("No PTB")
        return
    ptb = ptbs[0]
    s = frida.attach(ptb.voice_pid)
    
    js = """
    try {
        const targetString = 'unknown RTP payload type';
        const stringPattern = targetString.split('').map(c => c.charCodeAt(0).toString(16).padStart(2, '0')).join(' ');
        send('Pattern: ' + stringPattern);
        Memory.scanSync(Process.findModuleByName('discord_voice.node').base, 1000, stringPattern);
        send('Scan successful');
    } catch(e) {
        send('Error: ' + e.message);
    }
    """
    sc = s.create_script(js)
    sc.on('message', lambda m,d: print(m))
    sc.load()
    time.sleep(1)

if __name__ == '__main__':
    run()