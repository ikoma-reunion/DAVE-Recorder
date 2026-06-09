class Tracer {
    constructor() {
        this.module = Process.getModuleByName('discord_voice.node');
        this.base = this.module.base;
        this.exports = this.module.enumerateExports();
        this.videoSsrcMap = new Map(); // ssrc -> userId
        this.decoderToUserId = new Map(); // decoderPtr -> userId
        
        this.initHooks();
    }
    
    readStdString(ptr) {
        const isSmall = ptr.add(24).readU8() < 16;
        if (isSmall) {
            return ptr.readUtf8String();
        } else {
            return ptr.readPointer().readUtf8String();
        }
    }
    
    findExport(keyword1, keyword2) {
        for (let i = 0; i < this.exports.length; i++) {
            const name = this.exports[i].name;
            if (name.includes(keyword1) && (!keyword2 || name.includes(keyword2))) {
                return this.exports[i].address;
            }
        }
        return null;
    }
    
    findFunctionByPrologue(pattern) {
        const textRanges = this.module.enumerateRanges('r-x');
        for (const range of textRanges) {
            try {
                const matches = Memory.scanSync(range.base, range.size, pattern);
                if (matches.length > 0) {
                    return matches[0].address;
                }
            } catch(e) {
                console.log("Error scanning r-x:", e.message);
            }
        }
        return null;
    }

    initHooks() {
        this.hookConnectUser();
        this.hookCreateVideoReceiveStream();
        this.hookCreateAndRegisterExternalDecoder();
    }

    hookCreateVideoReceiveStream() {
        const pattern = "41 57 41 56 41 55 41 54 56 57 55 53 48 81 ec 98 01 00 00";
        const funcAddr = this.findFunctionByPrologue(pattern);
        if (!funcAddr) {
            console.log("CreateVideoReceiveStream prologue not found dynamically");
            return;
        }
        
        const _this = this;
        Interceptor.attach(funcAddr, {
            onEnter: function(args) {
                this.configPtr = args[1];
                let foundSsrc = null;
                for (let i=0; i<256; i+=4) {
                    try {
                        const val = this.configPtr.add(i).readU32();
                        if (val > 100 && val < 4000000000) {
                            if (_this.videoSsrcMap.has(val)) {
                                foundSsrc = val;
                                console.log(`  -> Found video SSRC ${val} in Config@+0x${i.toString(16)}`);
                                break;
                            }
                        }
                    } catch(e) {}
                }
                this.foundSsrc = foundSsrc;
            },
            onLeave: function(retval) {
                if (this.foundSsrc && !retval.isNull()) {
                    _this.decoderToUserId.set(retval.toString(), this.foundSsrc);
                    console.log(`[MAP] Stream ${retval} -> SSRC ${this.foundSsrc}`);
                }
            }
        });
        console.log(`Hooked CreateVideoReceiveStream at ${funcAddr}`);
    }

    hookCreateAndRegisterExternalDecoder() {
        const instAddr = this.findFunctionByString("VideoReceiveStream2::CreateAndRegisterExternalDecoder");
        if (!instAddr) {
            console.log("CreateAndRegisterExternalDecoder string ref not found");
            return;
        }
        
        const _this = this;
        Interceptor.attach(instAddr, {
            onEnter: function(args) {
                this.stream = args[0];
            },
            onLeave: function(retval) {
                if (_this.decoderToUserId.has(this.stream.toString())) {
                    const ssrc = _this.decoderToUserId.get(this.stream.toString());
                    const userId = _this.videoSsrcMap.get(ssrc);
                    
                    // Scan stream object to find the decoder pointer
                    for (let i=0; i<2000; i+=8) {
                        try {
                            const ptr = this.stream.add(i).readPointer();
                            if (!ptr.isNull() && ptr.compare(_this.base) > 0) {
                                try {
                                    const vtable = ptr.readPointer();
                                    const vtableOffset = vtable.sub(_this.base).toInt32();
                                    if (vtableOffset >= 0xBC0000 && vtableOffset <= 0xBD0000) {
                                        console.log(`[FINAL MAP] Decoder ${ptr} (vtable 0x${vtableOffset.toString(16)}) -> SSRC ${ssrc} -> User ${userId}`);
                                        _this.decoderToUserId.set(ptr.toString(), userId);
                                    }
                                } catch(e) {}
                            }
                        } catch(e) {}
                    }
                }
            }
        });
        console.log(`Hooked CreateAndRegisterExternalDecoder at ${instAddr}`);
    }

    hookConnectUser() {
        const addr = this.findExport('ConnectUser', 'Connection@voice');
        if (!addr) {
            console.log("ConnectUser export not found");
            return;
        }
        
        const _this = this;
        Interceptor.attach(addr, {
            onEnter: function(args) {
                const userId = _this.readStdString(args[1]);
                const audioSsrc = args[2].toUInt32();
                const videoSsrcVector = args[3]; 
                
                const vecStart = videoSsrcVector.readPointer();
                const vecEnd = videoSsrcVector.add(8).readPointer();
                const numSsrcs = vecEnd.sub(vecStart).toInt32() / 4;
                
                let ssrcs = [];
                for (let i = 0; i < numSsrcs; i++) {
                    const ssrc = vecStart.add(i * 4).readU32();
                    ssrcs.push(ssrc);
                    _this.videoSsrcMap.set(ssrc, userId);
                }
                
                console.log(`\n[ConnectUser] userId: ${userId}, audioSSRC: ${audioSsrc}, videoSSRCs: [${ssrcs.join(', ')}]`);
            }
        });
        console.log("Hooked ConnectUser");
    }

    hookH264Decoder(errStr) {
        const funcAddr = this.findFunctionByString(errStr);
        if (!funcAddr) {
            console.log(`Decoder for string "${errStr}" not found dynamically`);
            return;
        }
        
        const _this = this;
        let lastReported = Date.now();
        
        Interceptor.attach(funcAddr, {
            onEnter: function(args) {
                const decoderPtr = args[0];
                const now = Date.now();
                
                if (now - lastReported < 1000) return;
                lastReported = now;
                
                console.log(`\n[Decode] string="${errStr}" decoderPtr: ${decoderPtr}`);
                
                let foundSsrcs = [];
                for (let i=0; i<0x2000; i+=4) { // Scan 8KB of decoder object
                    try {
                        const val = decoderPtr.add(i).readU32();
                        if (_this.videoSsrcMap.has(val) && val > 100) {
                            foundSsrcs.push(`KNOWN(${val})@obj+0x${i.toString(16)}`);
                        }
                    } catch(e) {}
                }
                
                if (foundSsrcs.length > 0) {
                    console.log(`  -> SUCCESS! Found SSRC in Decoder Object: ${foundSsrcs.join(', ')}`);
                } else {
                    console.log(`  -> FAILED to find any known SSRC in the decoder object.`);
                }
            }
        });
        console.log(`Hooked Decoder for "${errStr}" at ${funcAddr}`);
    }
}

setTimeout(() => {
    new Tracer();
}, 1000);