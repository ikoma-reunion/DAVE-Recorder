import frida
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'src'))
from core.process_manager import ProcessManager

def test_video_hook_patterns():
    ptbs = [i for i in ProcessManager.get_discord_instances() if i.flavor == 'PTB']
    if not ptbs:
        print("No PTB running. Skipping test.")
        return
        
    ptb = ptbs[0]
    session = frida.attach(ptb.voice_pid)
    
    js = """
    const mod = Process.findModuleByName('discord_voice.node');
    if (!mod) {
        send('Error: discord_voice.node not found');
    } else {
        const targetString = "avcodec_send_packet error: ";
        const stringPattern = targetString.split('').map(c => c.charCodeAt(0).toString(16).padStart(2, '0')).join(' ');
        let strAddr = null;
        
        const rdataRanges = mod.enumerateRanges('r--');
        for (let i = 0; i < rdataRanges.length; i++) {
            const matches = Memory.scanSync(rdataRanges[i].base, rdataRanges[i].size, stringPattern);
            if (matches.length > 0) {
                strAddr = matches[0].address;
                send('Found string at ' + strAddr);
                break;
            }
        }
        
        if (strAddr) {
            const textRanges = mod.enumerateRanges('r-x');
            let xrefAddr = null;
            const leaPattern = "4C 8D 05"; // lea r8, [rip + disp32] (or lea rdx)
            // Or lea r8, [rip + disp32] is 4C 8D 05
            // But let's scan for lea r8/rdx/rcx
            for (let i = 0; i < textRanges.length; i++) {
                let cursor = textRanges[i].base;
                let end = textRanges[i].base.add(textRanges[i].size).sub(7);
                while (cursor.compare(end) < 0) {
                    if (cursor.readU8() === 0x4C && cursor.add(1).readU8() === 0x8D && cursor.add(2).readU8() === 0x05) {
                        const disp = cursor.add(3).readS32();
                        const target = cursor.add(7).add(disp);
                        if (target.equals(strAddr)) {
                            xrefAddr = cursor;
                            break;
                        }
                    }
                    cursor = cursor.add(1);
                }
                if (xrefAddr) break;
            }
            
            if (xrefAddr) {
                send('Found XREF at ' + xrefAddr);
                let addr = null;
                let cursor = xrefAddr;
                for (let i = 0; i < 4000; i++) {
                    cursor = cursor.sub(1);
                    // Prologue: push r15, push r14, push r12, push rsi, push rdi, push rbp, push rbx -> 41 57 41 56 41 54 56 57 55 53
                    if (cursor.readU8() === 0x41 && cursor.add(1).readU8() === 0x57 && cursor.add(2).readU8() === 0x41 && cursor.add(3).readU8() === 0x56) {
                        addr = cursor;
                        break;
                    }
                }
                if (addr) {
                    send('Found H264DecoderImpl::Decode at ' + addr);
                } else {
                    send('Failed to find prologue');
                }
            } else {
                send('Failed to find XREF');
            }
        } else {
            send('String not found');
        }
        
        // Test SetVideoOutputSink
        const exports = mod.enumerateExports();
        let sinkFound = false;
        for (let i = 0; i < exports.length; i++) {
            if (exports[i].name.includes('SetVideoOutputSink')) {
                send('Found SetVideoOutputSink at ' + exports[i].address + ' : ' + exports[i].name);
                sinkFound = true;
                break;
            }
        }
        if (!sinkFound) {
            send('SetVideoOutputSink not found in exports');
        }
    }
    """
    
    script = session.create_script(js)
    
    def on_message(message, data):
        if message['type'] == 'send':
            print(f"FRIDA: {message['payload']}")
        else:
            print(f"FRIDA ERROR: {message}")
            
    script.on('message', on_message)
    script.load()
    time.sleep(2)
    session.detach()
    
if __name__ == '__main__':
    test_video_hook_patterns()
