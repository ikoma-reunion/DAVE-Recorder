import frida
import time
from dave_recorder.core.process_manager import ProcessManager

def run():
    instances = ProcessManager.get_discord_instances()
    ptb_inst = next((inst for inst in instances if inst.flavor == "PTB"), None)
    if not ptb_inst:
        print("No PTB instance found")
        return
        
    print(f"Attaching to PTB Voice PID: {ptb_inst.voice_pid}")
    s = frida.attach(ptb_inst.voice_pid)
    
    js = """
    const mod = Process.findModuleByName('discord_voice.node');
    const exports = mod.enumerateExports();
    let addr = null;
    for(let i=0; i<exports.length; i++) {
        if(exports[i].name.includes('SetRemoteUserSpeaking') && exports[i].name.includes('Connection')) {
            addr = exports[i].address;
            break;
        }
    }
    
    if (addr) {
        send('Found SetRemoteUserSpeaking at ' + addr);
        Interceptor.attach(addr, {
            onEnter: function(args) {
                send('Speaking event fired!');
            }
        });
    } else {
        send('Not found');
    }
    """
    sc = s.create_script(js)
    sc.on('message', lambda m,d: print(m))
    sc.load()
    print("Speak in Discord...")
    time.sleep(5)

if __name__ == '__main__':
    run()