import frida
import time
from dave_recorder.core.process_manager import ProcessManager

def run():
    instances = ProcessManager.get_discord_instances()
    stable_inst = next((inst for inst in instances if inst.flavor == "Stable"), None)
    if not stable_inst:
        print("No Stable instance found")
        return
        
    s = frida.attach(stable_inst.voice_pid)
    
    js = """
    const mod = Process.findModuleByName('discord_voice.node');
    const exports = mod.enumerateExports();
    let getStatsAddr = null;
    for(let i=0; i<exports.length; i++) {
        if(exports[i].name.includes('GetStats') && exports[i].name.includes('Connection')) {
            getStatsAddr = exports[i].address;
            break;
        }
    }
    
    let done = false;
    Interceptor.attach(getStatsAddr, {
        onEnter: function(args) {
            if(done) return;
            done = true;
            try {
                const ctx = args[0].add(32).readPointer();
                const vB = ctx.add(1256).readPointer();
                const vE = ctx.add(1264).readPointer();
                const n = vE.sub(vB).toInt32() / 8;
                send('Users in vector: ' + n);
                for(let i=0; i<n; i++) {
                    let p = vB.add(i*8).readPointer();
                    try {
                        let cap = p.add(32+24).readU32();
                        let sz = p.add(32+16).readU32();
                        let str = '';
                        let ptr = (cap < 16) ? p.add(32) : p.add(32).readPointer();
                        
                        try {
                            str = ptr.readUtf8String(sz);
                            send('User ' + i + ': "' + str + '" (size: ' + sz + ', cap: ' + cap + ')');
                        } catch(parseErr) {
                            // Dump raw bytes
                            let raw = ptr.readByteArray(sz > 64 ? 64 : sz);
                            let hex = [];
                            let view = new Uint8Array(raw);
                            for(let j=0; j<view.length; j++) hex.push(view[j].toString(16).padStart(2, '0'));
                            send('User ' + i + ' RAW HEX: ' + hex.join(' ') + ' (size: ' + sz + ', cap: ' + cap + ')');
                        }
                    } catch(e) {
                        send('User ' + i + ' access error: ' + e);
                    }
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
    time.sleep(5)

if __name__ == '__main__':
    run()