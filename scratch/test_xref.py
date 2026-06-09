import frida
import time
from dave_recorder.core.process_manager import ProcessManager

def test_xref():
    instances = ProcessManager.get_discord_instances()
    if not instances:
        return
    ptb = next((i for i in instances if i.flavor == 'PTB'), instances[-1])
    s = frida.attach(ptb.voice_pid)
    
    js = """
    function run() {
        const pattern = '48 8D 0D ?? ?? ?? ??';
        const targetString = 'unknown RTP payload type';
        const stringPattern = targetString.split('').map(c => c.charCodeAt(0).toString(16).padStart(2, '0')).join(' ');
        
        const strMatch = Memory.scanSync(Process.findModuleByName('discord_voice.node').base, 14000000, stringPattern);
        if(strMatch.length === 0) {
            send('String not found');
            return;
        }
        const strAddr = strMatch[0].address;
        send('String found at: ' + strAddr);
        
        const matches = Memory.scanSync(Process.findModuleByName('discord_voice.node').base, 14000000, pattern);
        let xref = null;
        for(let i=0; i<matches.length; i++) {
            let m = matches[i];
            let target = m.address.add(7).add(m.address.add(3).readS32());
            if(target.equals(strAddr)) {
                xref = m.address;
                break;
            }
        }
        
        if (xref) {
            send('Found xref at ' + xref);
            let cursor = xref;
            let found = false;
            for(let i=0;i<2000;i++){
                cursor = cursor.sub(1);
                if(cursor.readU8()===0x41 && cursor.add(1).readU8()===0x57) {
                    send('Found 41 57 at ' + cursor + ' (distance: ' + xref.sub(cursor) + ')');
                    found = true;
                    break;
                }
            }
            if(!found) send('Prologue not found in 2000 bytes');
        } else {
            send('XREF not found');
        }
    }
    run();
    """
    sc = s.create_script(js)
    sc.on('message', lambda m,d: print(m))
    sc.load()
    time.sleep(2)

if __name__ == '__main__':
    test_xref()