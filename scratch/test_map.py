import frida
import time
from dave_recorder.core.process_manager import ProcessManager

def test_map():
    instances = ProcessManager.get_discord_instances()
    if not instances:
        return
    ptb = next((i for i in instances if i.flavor == 'PTB'), instances[-1])
    s = frida.attach(ptb.voice_pid)
    
    js = """
    const exports = Process.findModuleByName('discord_voice.node').enumerateExports();
    let addr = null;
    for(let i=0; i<exports.length; i++) {
        if(exports[i].name.includes('GetStats') && exports[i].name.includes('Connection')) {
            addr = exports[i].address;
            break;
        }
    }
    
    let done = false;
    Interceptor.attach(addr, {
        onEnter: function(args) {
            if(done) return;
            done = true;
            try {
                const ctx = args[0].add(32).readPointer();
                const mapHead = ctx.add(288).readPointer();
                send('Map head: ' + mapHead);
                let node = mapHead.readPointer(); // _Next
                let count = 0;
                while(!node.equals(mapHead) && count < 20) {
                    count++;
                    let ssrc = node.add(16).readU32();
                    let userPtr = node.add(24).readPointer();
                    
                    let cap = userPtr.add(32+24).readU32();
                    let sz = userPtr.add(32+16).readU32();
                    let ptr = (cap < 16) ? userPtr.add(32) : userPtr.add(32).readPointer();
                    let str = ptr.readUtf8String(sz);
                    
                    send('SSRC: ' + ssrc + ' -> UserID: ' + str);
                    
                    node = node.readPointer(); // next node
                }
            } catch(e) {
                send('Error: ' + e);
            }
        }
    });
    """
    sc = s.create_script(js)
    sc.on('message', lambda m,d: print(m))
    sc.load()
    time.sleep(2)

if __name__ == '__main__':
    test_map()