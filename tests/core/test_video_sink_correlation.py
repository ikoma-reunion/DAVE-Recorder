import frida
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'src'))
from core.process_manager import ProcessManager

def test_video_sink_correlation():
    ptbs = [i for i in ProcessManager.get_discord_instances() if i.flavor == 'PTB']
    if not ptbs:
        print("No PTB running.")
        return
        
    session = frida.attach(ptbs[0].voice_pid)
    
    js = """
    const mod = Process.findModuleByName('discord_voice.node');
    
    // Resolve H264DecoderImpl::Decode
    const targetString = "avcodec_send_packet error: ";
    const stringPattern = targetString.split('').map(c => c.charCodeAt(0).toString(16).padStart(2, '0')).join(' ');
    let strAddr = null;
    const rdataRanges = mod.enumerateRanges('r--');
    for (let i = 0; i < rdataRanges.length; i++) {
        const matches = Memory.scanSync(rdataRanges[i].base, rdataRanges[i].size, stringPattern);
        if (matches.length > 0) {
            strAddr = matches[0].address; break;
        }
    }
    
    let decodeAddr = null;
    if (strAddr) {
        const textRanges = mod.enumerateRanges('r-x');
        let xrefAddr = null;
        for (let i = 0; i < textRanges.length; i++) {
            let cursor = textRanges[i].base;
            let end = textRanges[i].base.add(textRanges[i].size).sub(7);
            while (cursor.compare(end) < 0) {
                if (cursor.readU8() === 0x4C && cursor.add(1).readU8() === 0x8D && cursor.add(2).readU8() === 0x05) {
                    const disp = cursor.add(3).readS32();
                    const target = cursor.add(7).add(disp);
                    if (target.equals(strAddr)) { xrefAddr = cursor; break; }
                }
                cursor = cursor.add(1);
            }
            if (xrefAddr) break;
        }
        if (xrefAddr) {
            let cursor = xrefAddr;
            for (let i = 0; i < 4000; i++) {
                cursor = cursor.sub(1);
                if (cursor.readU8() === 0x41 && cursor.add(1).readU8() === 0x57 && cursor.add(2).readU8() === 0x41 && cursor.add(3).readU8() === 0x56) {
                    decodeAddr = cursor; break;
                }
            }
        }
    }
    
    if (decodeAddr) {
        Interceptor.attach(decodeAddr, {
            onEnter: function(args) {
                const decoderInstance = args[0];
                const encodedImage = args[1];
                const size = encodedImage.add(144).readU32();
                send('Decode called! Decoder: ' + decoderInstance + ' Size: ' + size);
            }
        });
    }
    
    // Resolve SetVideoOutputSink
    const exports = mod.enumerateExports();
    let sinkAddr = null;
    for (let i = 0; i < exports.length; i++) {
        if (exports[i].name.includes('SetVideoOutputSink')) {
            sinkAddr = exports[i].address; break;
        }
    }
    
    function readStdString(strObj) {
        const capacity = strObj.add(24).readU32();
        const size = strObj.add(16).readU32();
        if (capacity < 16) {
            return strObj.readUtf8String(size);
        } else {
            return strObj.readPointer().readUtf8String(size);
        }
    }
    
    if (sinkAddr) {
        Interceptor.attach(sinkAddr, {
            onEnter: function(args) {
                const userId = readStdString(args[1]);
                send('SetVideoOutputSink called! UserID: ' + userId);
            }
        });
    }
    """
    
    script = session.create_script(js)
    def on_message(m, d):
        if m['type'] == 'send':
            print(f"[FRIDA] {m['payload']}")
    script.on('message', on_message)
    script.load()
    print("Waiting for video events... (Enable a camera stream in Discord!)")
    time.sleep(15)
    session.detach()

if __name__ == '__main__':
    test_video_sink_correlation()
