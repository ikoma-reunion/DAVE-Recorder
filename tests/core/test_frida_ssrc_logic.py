import frida
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'src'))

def test_frida_ssrc_logic():
    """
    This test completely validates the JS logic of `tryResolveSsrcOffset` by loading 
    the actual voice_hook.js into the current Python test process via Frida.
    It builds a fake C++ std::vector structure in memory and ensures the majority-vote logic 
    (validCount > invalidCount) works correctly when 7 out of 8 users have an SSRC of 0 (muted/silent).
    """
    session = frida.attach(os.getpid())
    
    script_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'src', 'frida_scripts', 'voice_hook.js')
    with open(script_path, 'r', encoding='utf-8') as f:
        js_code = f.read().replace("hooker.init();", "// hooker.init();")

    # We prepend a custom script to mock Frida globals and append the rpc.exports
    test_js = """
    try {
        const originalFindModuleByName = Process.findModuleByName;
        Process.findModuleByName = function(name) {
            if (name === 'discord_voice.node') {
                return {
                    base: ptr("0x1000000"),
                    size: 0x2000000,
                    enumerateExports: function() { return []; },
                    enumerateRanges: function(prot) { return []; }
                };
            }
            return originalFindModuleByName ? originalFindModuleByName(name) : null;
        };
    """ + js_code + """
        rpc.exports = {
            testSsrcResolution: function() {
                const conn = Memory.alloc(0x1000);
                const voiceCtx = Memory.alloc(0x1000);
                conn.add(32).writePointer(voiceCtx);
                const numUsers = 8;
                const vectorBegin = Memory.alloc(numUsers * 16);
                const vectorEnd = vectorBegin.add(numUsers * 16);
                voiceCtx.add(0).writePointer(vectorBegin);
                voiceCtx.add(8).writePointer(vectorEnd);
                const users = [];
                for(let i=0; i<numUsers; i++) {
                    const u = Memory.alloc(0x2500);
                    users.push(u);
                    vectorBegin.add(i * 16).writePointer(u);
                    if (i === 0) {
                        u.add(0x1e70).writeU32(12545);
                    } else {
                        u.add(0x1e70).writeU32(0);
                    }
                }
                const h = new DiscordVoiceHook();
                h.activeConnectionPtr = conn;
                h.voiceCtxOffset = 32;
                h.vectorBeginOffset = 0;
                h.vectorEndOffset = 8;
                h.tryResolveSsrcOffset(12545);
                return h.audioSsrcOffset;
            }
        };
    } catch(e) {
        send("GLOBAL LOAD ERROR: " + e.stack);
    }
    """
    
    script = session.create_script(test_js)
    
    def on_message(message, data):
        if message['type'] == 'send':
            print("FRIDA MSG:", message['payload'])
            
    script.on('message', on_message)
    script.load()
    
    # Run the test
    resolved_offset = script.exports_sync.test_ssrc_resolution()
    session.detach()
    
    assert resolved_offset == 0x1e70, f"The JS logic failed! It returned offset {resolved_offset} instead of 0x1e70. The majority-vote bug is present!"
