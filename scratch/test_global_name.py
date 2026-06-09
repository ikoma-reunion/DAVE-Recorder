import frida
import time
from dave_recorder.core.process_manager import ProcessManager

def extract_names():
    instances = ProcessManager.get_discord_instances()
    if not instances:
        print("No discord instances found.")
        return
    inst = instances[-1] # Usually PTB or Canary
    print(f"Attaching to {inst.flavor} Renderer PID: {inst.renderer_pid}")
    try:
        s = frida.attach(inst.renderer_pid)
    except Exception as e:
        print("Failed to attach:", e)
        return
        
    js_code = """
    const p8 = '"global_name"';
    const ranges = Process.enumerateRanges('rw-');
    let names = new Set();
    
    for (let i=0; i<ranges.length; i++) {
        let r = ranges[i];
        try {
            let pattern = Memory.allocUtf8String(p8).readByteArray(p8.length);
            let matches = Memory.scanSync(r.base, r.size, pattern);
            matches.forEach(m => {
                try {
                    let context = m.address.readUtf8String(150);
                    let nameMatch = context.match(/"global_name"\\s*:\\s*"([^"]+)"/);
                    if (nameMatch) {
                        names.add(nameMatch[1]);
                    }
                } catch(e) {}
            });
        } catch(e) {}
    }
    
    // Also try UTF-16
    const p16 = '22 00 67 00 6c 00 6f 00 62 00 61 00 6c 00 5f 00 6e 00 61 00 6d 00 65 00 22 00';
    for (let i=0; i<ranges.length; i++) {
        let r = ranges[i];
        try {
            let matches16 = Memory.scanSync(r.base, r.size, p16);
            matches16.forEach(m => {
                try {
                    let context = m.address.readUtf16String(150);
                    let nameMatch = context.match(/"global_name"\\s*:\\s*"([^"]+)"/);
                    if (nameMatch) {
                        names.add(nameMatch[1]);
                    }
                } catch(e) {}
            });
        } catch(e) {}
    }

    send('Names found: ' + Array.from(names).join(', '));
    """
    sc = s.create_script(js_code)
    sc.on('message', lambda m,d: print(m))
    sc.load()
    time.sleep(3)

if __name__ == '__main__':
    extract_names()