class DiscordVoiceHook {
    constructor() {
        this.moduleName = 'discord_voice.node';
        this.mod = Process.findModuleByName(this.moduleName);
        if (!this.mod) {
            this.sendError(`Module ${this.moduleName} not found`);
            return;
        }
        
        this.exports = this.mod.enumerateExports();
        this.map_scanned = false;
        
        this.vectorBeginOffset = null;
        this.vectorEndOffset = null;
        this.voiceCtxOffset = null;
        this.vtableAddr = null;
        this.audioSsrcOffset = null;
        this.activeConnectionPtr = null;
        this.ssrcAttempts = new Set();
        
        // Video specific mappings
        this.videoSsrcMap = new Map(); // ssrc -> userId
        this.decoderToUserId = new Map(); // decoderPtr -> userId
    }

    sendError(msg) {
        send({ type: 'error', description: msg });
        throw new Error(msg); 
    }

    init() {
        if (!this.mod) return;
        
        this.resolveOffsetsDynamically();
        
        if (this.vectorBeginOffset === null || this.vectorEndOffset === null || this.voiceCtxOffset === null) {
            this.sendError("Failed to dynamically resolve all required struct offsets. Version might be unsupported.");
        }
        
        this.hookConnectUser();
        this.hookDisconnectUser();
        this.hookSetRemoteUserSpeaking();
        this.hookGetStats();
        
        // Video SSRC Correlation Hooks
        this.resolveVideoReceiveStream2VTable();
        this.hookCreateVideoReceiveStream();
        this.hookCreateAndRegisterExternalDecoder();
        this.hookH264Decoder();
        
        // Find VTable and hook InsertPacket *before* heap scan so we can correlate SSRC
        this.findConnectionVTable();
        this.findActiveConnection();
        this.hookInsertPacket();
        
        // Schedule video heap scan a bit later to allow audio mapping to complete
        const _this = this;
        setTimeout(function() {
            _this.performVideoHeapScan();
        }, 3000);

        send({ type: 'status', message: 'Hooks initialized successfully. Awaiting packet to correlate SSRC offset...' });
    }

    resolveVideoReceiveStream2VTable() {
        send({ type: 'status', message: 'Resolving VideoReceiveStream2 VTable...' });
        
        const strAddr = this.findFunctionByStringRef("~VideoReceiveStream2: ");
        if (!strAddr) {
            send({ type: 'status', message: 'Could not find ~VideoReceiveStream2: string ref.' });
            return;
        }

        // Trace backward from ~VideoReceiveStream2 destructor start to find lea rax, [vtable]; mov [rcx], rax
        // The start of the destructor is strAddr.
        // Actually findFunctionByStringRef returns the start of the function!
        let cursor = strAddr;
        let vtable = null;
        for (let i = 0; i < 50; i++) {
            try {
                const b0 = cursor.readU8();
                const b1 = cursor.add(1).readU8();
                const b2 = cursor.add(2).readU8();
                
                // lea rax, [rip+disp] -> 48 8d 05 ?? ?? ?? ??
                // mov [rcx], rax -> 48 89 01
                if (b0 === 0x48 && b1 === 0x8D && b2 === 0x05) {
                    const nextB0 = cursor.add(7).readU8();
                    const nextB1 = cursor.add(8).readU8();
                    const nextB2 = cursor.add(9).readU8();
                    if (nextB0 === 0x48 && nextB1 === 0x89 && nextB2 === 0x01) {
                        const disp = cursor.add(3).readS32();
                        vtable = cursor.add(7).add(disp);
                        break;
                    }
                }
                cursor = cursor.add(1);
            } catch (e) {
                break;
            }
        }

        if (vtable) {
            this.videoStreamVTable = vtable;
            send({ type: 'status', message: `Successfully resolved VideoReceiveStream2 VTable at ${vtable}` });
        } else {
            send({ type: 'status', message: 'Could not resolve VideoReceiveStream2 VTable.' });
        }
    }

    performVideoHeapScan() {
        if (!this.videoStreamVTable) return;
        
        send({ type: 'status', message: 'Performing heap scan for active VideoReceiveStream2 instances...' });
        const ranges = Process.enumerateRanges('rw-');
        const vtablePtr = this.videoStreamVTable.toMatchPattern();

        let foundCount = 0;
        for (let i = 0; i < ranges.length; i++) {
            try {
                const matches = Memory.scanSync(ranges[i].base, ranges[i].size, vtablePtr);
                for (let m = 0; m < matches.length; m++) {
                    const instancePtr = matches[m].address;
                    
                    // Found a stream. Now scan its inside for a known video SSRC.
                    let foundSsrc = null;
                    for (let offset = 0; offset < 5000; offset += 4) {
                        try {
                            const val = instancePtr.add(offset).readU32();
                            if (this.videoSsrcMap.has(val)) {
                                foundSsrc = val;
                                break;
                            }
                        } catch (e) {}
                    }
                    
                    if (foundSsrc) {
                        foundCount++;
                        const userId = this.videoSsrcMap.get(foundSsrc);
                        send({ type: 'status', message: `Heap Scan: Stream at ${instancePtr} mapped to SSRC ${foundSsrc} (User ${userId})` });
                        
                        // Now scan the same stream for decoder pointers
                        for (let offset = 0; offset < 5000; offset += 8) {
                            try {
                                const ptr = instancePtr.add(offset).readPointer();
                                if (!ptr.isNull() && ptr.compare(this.mod.base) > 0) {
                                    try {
                                        const vtable = ptr.readPointer();
                                        const rdataRanges = this.mod.enumerateRanges('r--');
                                        let isRdata = false;
                                        for (let r = 0; r < rdataRanges.length; r++) {
                                            const rBase = rdataRanges[r].base;
                                            const rEnd = rBase.add(rdataRanges[r].size);
                                            if (vtable.compare(rBase) >= 0 && vtable.compare(rEnd) < 0) {
                                                isRdata = true;
                                                break;
                                            }
                                        }
                                        
                                        if (isRdata) {
                                            if (!this.decoderToUserId.has(ptr.toString())) {
                                                this.decoderToUserId.set(ptr.toString(), foundSsrc);
                                                send({ type: 'mapping', ssrc: foundSsrc, userId: userId, method: 'VideoHeapScan', decoder: ptr.toString() });
                                            }
                                        }
                                    } catch (e) {}
                                }
                            } catch (e) {}
                        }
                    }
                }
            } catch (e) {
                // Expected when Memory.scanSync hits unreadable pages
            }
        }
        send({ type: 'status', message: `Video heap scan complete. Found ${foundCount} active streams.` });
    }

    findActiveConnection() {
        if (!this.vtableAddr) return;
        const ranges = Process.enumerateRanges('rw-');
        const vtablePtr = this.vtableAddr.toMatchPattern();

        for (let i = 0; i < ranges.length; i++) {
            try {
                const matches = Memory.scanSync(ranges[i].base, ranges[i].size, vtablePtr);
                for (let m = 0; m < matches.length; m++) {
                    const instancePtr = matches[m].address;
                    if (this.validateConnectionInstance(instancePtr)) {
                        this.activeConnectionPtr = instancePtr;
                        send({ type: 'status', message: `Active Connection found at ${instancePtr}` });
                        return;
                    }
                }
            } catch (e) {
                if (!e.message || !e.message.includes('access violation')) {
                    throw e;
                }
            }
        }
    }

    tryResolveSsrcOffset(interceptedSsrc) {
        if (this.audioSsrcOffset !== null || !this.activeConnectionPtr) return;
        
        if (!this.ssrcAttempts) this.ssrcAttempts = new Set();
        if (this.ssrcAttempts.has(interceptedSsrc)) return;
        this.ssrcAttempts.add(interceptedSsrc);
        
        try {
            const voiceCtx = this.activeConnectionPtr.add(this.voiceCtxOffset).readPointer();
            const vecBegin = voiceCtx.add(this.vectorBeginOffset).readPointer();
            const vecEnd = voiceCtx.add(this.vectorEndOffset).readPointer();
            const numUsers = vecEnd.sub(vecBegin).toInt32() / 16;
            
            // Safer hex pattern generation using ArrayBuffer
            const buffer = new ArrayBuffer(4);
            const view = new DataView(buffer);
            view.setUint32(0, interceptedSsrc, true); // Little endian
            const bytes = new Uint8Array(buffer);
            let pattern = Array.from(bytes).map(b => b.toString(16).padStart(2, '0')).join(' ');
            
            send({ type: 'status', message: `Attempting data correlation for SSRC ${interceptedSsrc} with pattern [${pattern}] across ${numUsers} users.` });
            
            for (let i = 0; i < numUsers; i++) {
                const pUser = vecBegin.add(i * 16).readPointer();
                if (pUser.isNull()) continue;
                
                try {
                    // User object is ~8KB, so 0x2500 is enough
                    const matches = Memory.scanSync(pUser, 0x2500, pattern); 
                    for (let m = 0; m < matches.length; m++) {
                        const offsetCandidate = matches[m].address.sub(pUser).toInt32();
                        
                        let validCount = 0;
                        let invalidCount = 0;
                        for (let k = 0; k < numUsers; k++) {
                            const otherUser = vecBegin.add(k * 16).readPointer();
                            if (otherUser.isNull()) continue;
                            try {
                                const otherSsrc = otherUser.add(offsetCandidate).readU32();
                                // SSRC 0 is valid for users who haven't spoken or are muted
                                if (otherSsrc === 0 || (otherSsrc > 100 && otherSsrc < 4000000000)) validCount++;
                                else invalidCount++;
                            } catch(e) {
                                if (!e.message || !e.message.includes('access violation')) {
                                    throw e;
                                }
                                invalidCount++;
                            }
                        }
                        
                        if (validCount > invalidCount) {
                            this.audioSsrcOffset = offsetCandidate;
                            send({ type: 'status', message: `Data Correlation SUCCESS: audioSsrc offset resolved to 0x${this.audioSsrcOffset.toString(16)}` });
                            this.extractUsers(this.activeConnectionPtr);
                            return;
                        }
                    }
                } catch(e) {
                }
            }
        } catch(e) {
        }
    }

    findExport(keyword1, keyword2) {
        for (let i = 0; i < this.exports.length; i++) {
            const name = this.exports[i].name;
            if (name.includes(keyword1) && name.includes(keyword2)) {
                return this.exports[i].address;
            }
        }
        return null;
    }

    findFunctionByPrologue(pattern) {
        const textRanges = this.mod.enumerateRanges('r-x');
        for (const range of textRanges) {
            try {
                const matches = Memory.scanSync(range.base, range.size, pattern);
                if (matches.length > 0) {
                    return matches[0].address;
                }
            } catch (e) {
                if (!e.message || !e.message.includes('access violation')) {
                    throw e;
                }
            }
        }
        return null;
    }

    findFunctionByStringRef(patternStr) {
        let pattern = "";
        for (let i = 0; i < patternStr.length; i++) {
            let hex = patternStr.charCodeAt(i).toString(16);
            if (hex.length === 1) hex = "0" + hex;
            pattern += hex + " ";
        }
        pattern = pattern.trim();
        
        const ranges = this.mod.enumerateRanges('r--');
        let strAddr = null;
        for (const range of ranges) {
            try {
                const matches = Memory.scanSync(range.base, range.size, pattern);
                if (matches.length > 0) {
                    strAddr = matches[0].address;
                    break;
                }
            } catch (e) {
                if (!e.message || !e.message.includes('access violation')) {
                    throw e;
                }
            }
        }
        
        if (!strAddr) return null;
        
        const textRanges = this.mod.enumerateRanges('r-x');
        for (const range of textRanges) {
            try {
                let cursor = range.base;
                let end = range.base.add(range.size).sub(7);
                while (cursor.compare(end) < 0) {
                    const b0 = cursor.readU8();
                    const b1 = cursor.add(1).readU8();
                    const b2 = cursor.add(2).readU8();
                    
                    let isLea = false;
                    if (b0 === 0x48 && b1 === 0x8D && (b2 === 0x15 || b2 === 0x0D || b2 === 0x1D)) isLea = true;
                    if (b0 === 0x4C && b1 === 0x8D && (b2 === 0x05 || b2 === 0x0D || b2 === 0x15 || b2 === 0x1D)) isLea = true;
                    
                    if (isLea) {
                        const disp = cursor.add(3).readS32();
                        const target = cursor.add(7).add(disp);
                        if (target.equals(strAddr)) {
                            let funcStart = cursor;
                            for (let i = 0; i < 1000; i++) {
                                funcStart = funcStart.sub(1);
                                if (funcStart.readU8() === 0xCC && funcStart.add(1).readU8() !== 0xCC) {
                                    return funcStart.add(1);
                                }
                            }
                        }
                    }
                    cursor = cursor.add(1);
                }
            } catch (e) {
                if (!e.message || !e.message.includes('access violation')) {
                    throw e;
                }
            }
        }
        return null;
    }

    extractUsers(connPtr) {
        if (this.map_scanned) return;
        
        try {
            if (connPtr.isNull()) return;
            
            const voiceCtx = connPtr.add(this.voiceCtxOffset).readPointer();
            if (voiceCtx.isNull()) return;
            
            const vecBegin = voiceCtx.add(this.vectorBeginOffset).readPointer();
            const vecEnd = voiceCtx.add(this.vectorEndOffset).readPointer();
            
            if (vecBegin.isNull() || vecEnd.isNull()) return;
            
            const numUsers = vecEnd.sub(vecBegin).toInt32() / 16;
            
            if (numUsers > 0 && numUsers < 1000) {
                if (this.audioSsrcOffset === null) return;
                
                send({ type: 'status', message: `Extracting ${numUsers} users from C++ std::vector...` });
                let foundAny = false;
                for (let i = 0; i < numUsers; i++) {
                    const pUser = vecBegin.add(i * 16).readPointer();
                    if (pUser.isNull()) continue;
                    
                    const strObj = pUser.add(32);
                    let userId = "";
                    try {
                        userId = this.readStdString(strObj);
                    } catch(e) {
                        continue;
                    }
                    
                    let ssrc = 0;
                    try {
                        ssrc = pUser.add(this.audioSsrcOffset).readU32();
                    } catch (e) {
                        ssrc = 0;
                    }
                    
                    if (/^\d+$/.test(userId)) {
                        send({ type: 'mapping', ssrc: ssrc, userId: userId, method: 'VectorScan' });
                        foundAny = true;
                        
                        // Extract video SSRCs via heuristic
                        this.extractVideoSsrcs(pUser, userId);
                    }
                }
                if (foundAny) {
                    this.map_scanned = true;
                    send({ type: 'status', message: 'Vector extraction complete.' });
                }
            }
        } catch(e) {
            // Silently fail for heap scan
        }
    }

    extractVideoSsrcs(pUser, userId) {
        // Scan User object for std::vector<uint32_t> containing video SSRCs
        for (let offset = 0; offset < 0x2500; offset += 8) {
            try {
                const p1 = pUser.add(offset).readPointer();
                const p2 = pUser.add(offset + 8).readPointer();
                const p3 = pUser.add(offset + 16).readPointer();
                
                if (p1.isNull() || p2.isNull() || p3.isNull()) continue;
                
                const size = p2.sub(p1).toInt32();
                if (size > 0 && size <= 32 && (size % 4) === 0) {
                    const cap = p3.sub(p1).toInt32();
                    if (cap >= size && cap < 1000) {
                        let valid = true;
                        let ssrcs = [];
                        for (let i = 0; i < size; i += 4) {
                            const s = p1.add(i).readU32();
                            if (s > 100 && s < 4000000000) {
                                ssrcs.push(s);
                            } else {
                                valid = false;
                                break;
                            }
                        }
                        
                        if (valid) {
                            for (let s of ssrcs) {
                                if (!this.videoSsrcMap.has(s)) {
                                    this.videoSsrcMap.set(s, userId);
                                    send({ type: 'mapping', ssrc: s, userId: userId, method: 'HeuristicVideoVector' });
                                }
                            }
                        }
                    }
                }
            } catch (e) {
                if (!e.message || !e.message.includes('access violation')) {
                    throw e;
                }
            }
        }
    }

    resolveUnknownDecoder(decoderPtrStr) {
        if (this.decoderToUserId.has(decoderPtrStr)) return;
        
        send({ type: 'status', message: `Attempting to resolve unknown decoder ${decoderPtrStr} via heap scan...` });
        const decPtr = ptr(decoderPtrStr);
        const pattern = decPtr.toMatchPattern();
        
        const ranges = Process.enumerateRanges('rw-');
        for (let i = 0; i < ranges.length; i++) {
            try {
                const matches = Memory.scanSync(ranges[i].base, ranges[i].size, pattern);
                for (let m = 0; m < matches.length; m++) {
                    const matchAddr = matches[m].address;
                    // matchAddr is where the decoder pointer is stored.
                    // Scan around it (-0x1000 to +0x1000) for a known video SSRC
                    const startScan = matchAddr.sub(0x1000);
                    for (let offset = 0; offset < 0x2000; offset += 4) {
                        try {
                            const val = startScan.add(offset).readU32();
                            if (this.videoSsrcMap.has(val)) {
                                const userId = this.videoSsrcMap.get(val);
                                this.decoderToUserId.set(decoderPtrStr, val); // map decoder to SSRC
                                send({ type: 'mapping', ssrc: val, userId: userId, method: 'DecoderHeapScan', decoder: decoderPtrStr });
                                return; // found it
                            }
                        } catch (e) {
                            if (!e.message || !e.message.includes('access violation')) {
                                throw e;
                            }
                        }
                    }
                }
            } catch (e) {
                if (!e.message || !e.message.includes('access violation')) {
                    throw e;
                }
            }
        }
    }

    resolveOffsetsDynamically() {
        send({ type: 'status', message: 'Starting fully dynamic offset resolution via XREF tracing...' });
        
        const targetString = "ConnectUser(): Unable to find user ";
        const stringPattern = targetString.split('').map(c => c.charCodeAt(0).toString(16).padStart(2, '0')).join(' ');
        let strAddr = null;
        
        const rdataRanges = this.mod.enumerateRanges('r--');
        for (let i = 0; i < rdataRanges.length; i++) {
            const matches = Memory.scanSync(rdataRanges[i].base, rdataRanges[i].size, stringPattern);
            if (matches.length > 0) {
                strAddr = matches[0].address;
                break;
            }
        }
        
        if (!strAddr) {
            this.sendError("Dynamic Resolution Failed: Target string not found.");
        }

        const textRanges = this.mod.enumerateRanges('r-x');
        let xrefAddr = null;
        
        for (let i = 0; i < textRanges.length; i++) {
            const base = textRanges[i].base;
            const size = textRanges[i].size;
            let cursor = base;
            while (cursor.compare(base.add(size).sub(7)) < 0) {
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

        if (!xrefAddr) {
            this.sendError("Dynamic Resolution Failed: Could not find XREF to target string.");
        }

        // Trace backwards to gather all called functions
        let cursor = xrefAddr;
        const vectorIterPattern = "4C 8B B1 ?? ?? 00 00 4C 8B B9 ?? ?? 00 00 4D 39 FE";
        let vectorBegin = null;
        let vectorEnd = null;
        
        for (let i = 0; i < 500; i++) {
            cursor = cursor.sub(1);
            if (cursor.readU8() === 0xE8) {
                try {
                    let insn = Instruction.parse(cursor);
                    if (insn.mnemonic === 'call') {
                        let funcAddr = ptr(insn.operands[0].value);
                        // Scan the first 0x1000 bytes of this function for our vector pattern
                        const matches = Memory.scanSync(funcAddr, 0x1000, vectorIterPattern);
                        if (matches.length > 0) {
                            const matchAddr = matches[0].address;
                            vectorBegin = matchAddr.add(3).readU32();
                            vectorEnd = matchAddr.add(10).readU32();
                            break; // Found it!
                        }
                    }
                } catch (e) {
                if (!e.message || !e.message.includes('access violation')) {
                    throw e;
                }
            }
            }
        }

        if (vectorBegin !== null && vectorEnd === vectorBegin + 8) {
            this.vectorBeginOffset = vectorBegin;
            this.vectorEndOffset = vectorEnd;
            this.voiceCtxOffset = 32; 
            send({ type: 'status', message: `Dynamic resolution successful: Vector Offsets [${this.vectorBeginOffset}, ${this.vectorEndOffset}]` });
        } else {
            this.sendError("Dynamic Resolution Failed: Could not resolve C++ std::vector offsets via signature scan.");
        }

        // Resolve Connection VTable via clustering
        this.findConnectionVTable();
    }

    findConnectionVTable() {
        send({ type: 'status', message: 'Identifying Connection VTable via method clustering...' });
        const targets = [
            this.findExport('ConnectUser', 'Connection@voice'),
            this.findExport('DisconnectUser', 'Connection@voice'),
            this.findExport('GetStats', 'Connection@voice')
        ].filter(addr => addr !== null);

        if (targets.length < 2) {
            send({ type: 'status', message: 'Warning: Not enough exports found for reliable VTable clustering.' });
            return;
        }

        const rdataRanges = this.mod.enumerateRanges('r--');
        let clusters = [];

        for (let i = 0; i < rdataRanges.length; i++) {
            const range = rdataRanges[i];
            for (let t = 0; t < targets.length; t++) {
                const targetAddr = targets[t];
                // Pointer on 64-bit system is 8 bytes
                const pattern = targetAddr.toMatchPattern();
                const matches = Memory.scanSync(range.base, range.size, pattern);
                for (let m = 0; m < matches.length; m++) {
                    clusters.push(matches[m].address);
                }
            }
        }

        if (clusters.length === 0) {
            send({ type: 'status', message: 'Warning: No pointers to Connection methods found in .rdata.' });
            return;
        }

        // Sort by address and find the tightest group
        clusters.sort((a, b) => a.compare(b));
        
        for (let i = 0; i < clusters.length; i++) {
            for (let j = i + 1; j < clusters.length; j++) {
                const diff = clusters[j].sub(clusters[i]).toInt32();
                if (diff > 0 && diff < 1024) {
                    // This is likely a VTable. In MSVC, the VTable address used in instances
                    // is usually the very beginning of the pointer array.
                    this.vtableAddr = clusters[i].sub(clusters[i].toInt32() % 8); // Align
                    // Backtrack a bit to find the start of the VTable
                    for (let k = 0; k < 20; k++) {
                        const prev = this.vtableAddr.sub(8);
                        const val = prev.readPointer();
                        // If it points into the code section of our module, it's likely still the VTable
                        if (val.compare(this.mod.base) >= 0 && val.compare(this.mod.base.add(this.mod.size)) < 0) {
                            this.vtableAddr = prev;
                        } else {
                            break;
                        }
                    }
                    send({ type: 'status', message: `Heuristic VTable identified at: ${this.vtableAddr}` });
                    return;
                }
            }
        }
    }

    performHeapScan() {
        if (!this.vtableAddr) return;
        if (this.map_scanned) return;

        send({ type: 'status', message: 'Performing heap scan for active Connection instances...' });
        const ranges = Process.enumerateRanges('rw-');
        const vtablePtr = this.vtableAddr.toMatchPattern();

        for (let i = 0; i < ranges.length; i++) {
            const range = ranges[i];
            try {
                const matches = Memory.scanSync(range.base, range.size, vtablePtr);
                for (let m = 0; m < matches.length; m++) {
                    const instancePtr = matches[m].address;
                    // Validate instance
                    if (this.validateConnectionInstance(instancePtr)) {
                        send({ type: 'status', message: `Found valid Connection instance at ${instancePtr}` });
                        this.extractUsers(instancePtr);
                        if (this.map_scanned) return; // Stop after first successful extraction
                    }
                }
            } catch (e) {
                // Ignore range access errors
            }
        }
    }

    validateConnectionInstance(ptr) {
        try {
            const voiceCtx = ptr.add(this.voiceCtxOffset).readPointer();
            if (voiceCtx.isNull()) return false;
            
            // Check if voiceCtx is in a valid memory region
            try {
                Memory.queryProtection(voiceCtx);
            } catch(e) { return false; }

            const vecBegin = voiceCtx.add(this.vectorBeginOffset).readPointer();
            const vecEnd = voiceCtx.add(this.vectorEndOffset).readPointer();
            
            if (vecBegin.isNull() || vecEnd.isNull()) return false;
            
            const diff = vecEnd.sub(vecBegin).toInt32();
            if (diff < 0 || diff > 16000 || (diff % 16) !== 0) return false;
            
            const numUsers = diff / 16;
            if (numUsers === 0) return false;

            // Check first user's ID
            const firstUser = vecBegin.readPointer();
            if (firstUser.isNull()) return false;
            const userId = this.readStdString(firstUser.add(32));
            return /^\d+$/.test(userId); // Must be a Snowflake
        } catch (e) {
            return false;
        }
    }

    extractUsers(connPtr) {
        if (this.map_scanned) return;
        
        try {
            if (connPtr.isNull()) return;
            
            const voiceCtx = connPtr.add(this.voiceCtxOffset).readPointer();
            if (voiceCtx.isNull()) return;
            
            const vecBegin = voiceCtx.add(this.vectorBeginOffset).readPointer();
            const vecEnd = voiceCtx.add(this.vectorEndOffset).readPointer();
            
            if (vecBegin.isNull() || vecEnd.isNull()) return;
            
            const numUsers = vecEnd.sub(vecBegin).toInt32() / 16;
            
            if (numUsers > 0 && numUsers < 1000) {
                if (this.audioSsrcOffset === null) return; // Wait for dynamic resolution
                
                send({ type: 'status', message: `Extracting ${numUsers} users from C++ std::vector...` });
                let foundAny = false;
                for (let i = 0; i < numUsers; i++) {
                    const pUser = vecBegin.add(i * 16).readPointer();
                    if (pUser.isNull()) continue;
                    
                    const strObj = pUser.add(32);
                    let userId = "";
                    try {
                        userId = this.readStdString(strObj);
                    } catch(e) {
                        continue;
                    }
                    
                    let ssrc = 0;
                    try {
                        ssrc = pUser.add(this.audioSsrcOffset).readU32();
                    } catch (e) {
                        ssrc = 0;
                    }
                    
                    if (/^\d+$/.test(userId)) {
                        send({ type: 'mapping', ssrc: ssrc, userId: userId, method: 'VectorScan' });
                        foundAny = true;
                    }
                }
                if (foundAny) {
                    this.map_scanned = true;
                    send({ type: 'status', message: 'Vector extraction complete.' });
                }
            }
        } catch(e) {
            // Silently fail for heap scan
        }
    }

    readStdString(strObj) {
        const capacity = strObj.add(24).readU32();
        const size = strObj.add(16).readU32();
        
        if (capacity < 16) {
            return strObj.readUtf8String(size);
        } else {
            const strPtr = strObj.readPointer();
            return strPtr.readUtf8String(size);
        }
    }

    hookGetStats() {
        const addr = this.findExport('GetStats', 'Connection@voice');
        if (!addr) {
            this.sendError("Could not resolve GetStats dynamically.");
            return;
        }

        const _this = this;
        Interceptor.attach(addr, {
            onEnter: function(args) {
                if (!_this.activeConnectionPtr) {
                    _this.activeConnectionPtr = args[0];
                    send({ type: 'status', message: `Active Connection pointer captured from GetStats: ${_this.activeConnectionPtr}` });
                }
                _this.extractUsers(args[0]);
            }
        });
    }

    hookCreateVideoReceiveStream() {
        const funcAddr = this.findFunctionByStringRef("Call::CreateVideoReceiveStream");
        if (!funcAddr) {
            send({ type: 'status', message: "CreateVideoReceiveStream string ref not found dynamically" });
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
                                break;
                            }
                        }
                    } catch (e) {
                if (!e.message || !e.message.includes('access violation')) {
                    throw e;
                }
            }
                }
                this.foundSsrc = foundSsrc;
            },
            onLeave: function(retval) {
                if (this.foundSsrc && !retval.isNull()) {
                    _this.decoderToUserId.set(retval.toString(), this.foundSsrc);
                    send({ type: 'status', message: `[MAP] Stream ${retval} -> SSRC ${this.foundSsrc}` });
                }
            }
        });
        send({ type: 'status', message: `Hooked CreateVideoReceiveStream at ${funcAddr}` });
    }

    hookCreateAndRegisterExternalDecoder() {
        const funcAddr = this.findFunctionByStringRef("VideoReceiveStream2::CreateAndRegisterExternalDecoder");
        if (!funcAddr) {
            send({ type: 'status', message: "CreateAndRegisterExternalDecoder string ref not found dynamically" });
            return;
        }
        
        const _this = this;
        Interceptor.attach(funcAddr, {
            onEnter: function(args) {
                this.stream = args[0];
            },
            onLeave: function(retval) {
                if (_this.decoderToUserId.has(this.stream.toString())) {
                    const ssrc = _this.decoderToUserId.get(this.stream.toString());
                    const userId = _this.videoSsrcMap.get(ssrc);
                    
                    for (let i=0; i<2000; i+=8) {
                        try {
                            const ptr = this.stream.add(i).readPointer();
                            if (!ptr.isNull() && ptr.compare(_this.mod.base) > 0) {
                                try {
                                    const vtable = ptr.readPointer();
                                    
                                    // Dynamically check if vtable is in an r-- (read-only data) range
                                    const ranges = _this.mod.enumerateRanges('r--');
                                    let isRdata = false;
                                    for (let r = 0; r < ranges.length; r++) {
                                        const rBase = ranges[r].base;
                                        const rEnd = rBase.add(ranges[r].size);
                                        if (vtable.compare(rBase) >= 0 && vtable.compare(rEnd) < 0) {
                                            isRdata = true;
                                            break;
                                        }
                                    }
                                    
                                    if (isRdata) {
                                        _this.decoderToUserId.set(ptr.toString(), userId);
                                        send({ type: 'mapping', ssrc: ssrc, userId: userId, method: 'VideoDecoder', decoder: ptr.toString() });
                                    }
                                } catch (e) {
                if (!e.message || !e.message.includes('access violation')) {
                    throw e;
                }
            }
                            }
                        } catch (e) {
                if (!e.message || !e.message.includes('access violation')) {
                    throw e;
                }
            }
                    }
                }
            }
        });
        send({ type: 'status', message: `Hooked CreateAndRegisterExternalDecoder at ${funcAddr}` });
    }

    hookConnectUser() {
        const addr = this.findExport('ConnectUser', 'Connection@voice');
        if (!addr) {
            this.sendError("Could not resolve ConnectUser dynamically.");
            return;
        }
        
        const _this = this;
        Interceptor.attach(addr, {
            onEnter: function(args) {
                try {
                    const ssrc = args[2].toInt32();
                    const userId = _this.readStdString(args[1]);
                    send({ type: 'mapping', ssrc: ssrc, userId: userId, method: 'ConnectUser' });
                } catch(e) {
                    _this.sendError("ConnectUser Error: " + e.stack);
                }
            }
        });
    }

    hookDisconnectUser() {
        const addr = this.findExport('DisconnectUser', 'Connection@voice');
        if (!addr) {
            this.sendError("Could not resolve DisconnectUser dynamically.");
            return;
        }
        
        const _this = this;
        Interceptor.attach(addr, {
            onEnter: function(args) {
                try {
                    const userId = _this.readStdString(args[1]);
                    send({ type: 'disconnect', userId: userId });
                } catch(e) {
                    _this.sendError("DisconnectUser Error: " + e.stack);
                }
            }
        });
    }

    hookSetRemoteUserSpeaking() {
        const addr = this.findExport('SetRemoteUserSpeaking', 'Connection@voice');
        if (!addr) {
            this.sendError("Could not resolve SetRemoteUserSpeaking dynamically.");
            return;
        }

        const _this = this;
        Interceptor.attach(addr, {
            onEnter: function(args) {
                try {
                    const userId = _this.readStdString(args[1]);
                    const ssrc = args[2].toUInt32();
                    const is_speaking = args[3].toInt32() !== 0;
                    
                    if (ssrc > 0) {
                        send({ type: 'mapping', ssrc: ssrc, userId: userId });
                    }
                    send({ type: 'speaking', userId: userId, is_speaking: is_speaking });
                } catch(e) {
                    _this.sendError("SetRemoteUserSpeaking Error: " + e.stack);
                }
            }
        });
    }

    hookSetVideoOutputSink() {
        const addr = this.findExport('SetVideoOutputSink', 'Discord');
        if (!addr) {
            this.sendError("Could not resolve SetVideoOutputSink dynamically.");
            return;
        }
        
        const _this = this;
        Interceptor.attach(addr, {
            onEnter: function(args) {
                try {
                    const userId = _this.readStdString(args[1]);
                    send({ type: 'video_sink', userId: userId });
                } catch(e) {
                    _this.sendError("SetVideoOutputSink Error: " + e.stack);
                }
            }
        });
    }

    hookH264Decoder() {
        const decoders = [
            { name: 'H264DecoderImpl', errStr: 'avcodec_send_packet error: ' },
            { name: 'ElectronVideoDecoder', errStr: 'ElectronVideoDecoder::Decode SubmitBuffer failed' }
        ];

        const _this = this;

        for (let idx = 0; idx < decoders.length; idx++) {
            const dec = decoders[idx];
            send({ type: 'status', message: `Resolving ${dec.name}::Decode via XREF...` });
            
            const addr = this.findFunctionByStringRef(dec.errStr);

            if (!addr) {
                send({ type: 'status', message: `Could not resolve ${dec.name}::Decode dynamically.` });
                continue;
            }

            send({ type: 'status', message: `Successfully resolved ${dec.name}::Decode at ${addr}` });

            Interceptor.attach(addr, {
                onEnter: function(args) {
                    try {
                        const decoderInstance = args[0];
                        const encodedImage = args[1];

                        const encodedDataObj = encodedImage.add(136).readPointer();
                        if (encodedDataObj.isNull()) {
                            send({ type: 'status', message: `[Decode] ${dec.name}: encodedDataObj is null at offset 136` });
                            return;
                        }

                        const dataVtable = encodedDataObj.readPointer();
                        const dataFunc = new NativeFunction(dataVtable.add(24).readPointer(), 'pointer', ['pointer']);
                        const dataPtr = dataFunc(encodedDataObj);
                        if (dataPtr.isNull()) {
                            send({ type: 'status', message: `[Decode] ${dec.name}: dataPtr is null` });
                            return;
                        }

                        const size = encodedImage.add(144).readU32();
                        const frameType = encodedImage.add(24).readU32();
                        const is_keyframe = (frameType === 3 || frameType === 1);

                        if (size > 0 && size < 1000000) {
                            const h264Payload = dataPtr.readByteArray(size);
                            const decStr = decoderInstance.toString();
                            const userId = _this.decoderToUserId.has(decStr) ? _this.decoderToUserId.get(decStr) : null;
                            if (userId) {
                                send({ type: 'h264_frame', userId: userId, is_keyframe: is_keyframe }, h264Payload);
                            } else {
                                _this.resolveUnknownDecoder(decStr);
                                const newUserId = _this.decoderToUserId.has(decStr) ? _this.decoderToUserId.get(decStr) : null;
                                if (newUserId) {
                                    send({ type: 'h264_frame', userId: newUserId, is_keyframe: is_keyframe }, h264Payload);
                                } else {
                                    send({ type: 'h264_frame', decoder: decStr, is_keyframe: is_keyframe }, h264Payload);
                                }
                            }
                        } else {
                            send({ type: 'status', message: `[Decode] ${dec.name}: Invalid size ${size}` });
                        }
                    } catch(e) {
                        send({ type: 'status', message: `[Decode] ${dec.name} Error: ` + e.message });
                    }
                }
            });
        }
    }

    hookInsertPacket() {
        send({ type: 'status', message: 'Resolving InsertPacketInternal via XREF...' });
        const targetString = "SplitAudio unknown payload type";
        const stringPattern = targetString.split('').map(c => c.charCodeAt(0).toString(16).padStart(2, '0')).join(' ');
        let stringMatches = [];
        
        const rdataRanges = this.mod.enumerateRanges('r--');
        for (let i = 0; i < rdataRanges.length; i++) {
            const matches = Memory.scanSync(rdataRanges[i].base, rdataRanges[i].size, stringPattern);
            for(let j=0; j<matches.length; j++) {
                stringMatches.push(matches[j].address);
            }
        }

        if (stringMatches.length === 0) {
            this.sendError("Could not resolve InsertPacketInternal: String not found.");
            return;
        }

        const textRanges = this.mod.enumerateRanges('r-x');
        let xrefAddr = null;
        
        const leaPattern = "4C 8D 05";
        for (let i = 0; i < textRanges.length; i++) {
            const matches = Memory.scanSync(textRanges[i].base, textRanges[i].size, leaPattern);
            for (let j = 0; j < matches.length; j++) {
                const matchAddr = matches[j].address;
                const disp = matchAddr.add(3).readS32();
                const target = matchAddr.add(7).add(disp);
                
                for(let k=0; k<stringMatches.length; k++) {
                    if (target.equals(stringMatches[k])) {
                        xrefAddr = matchAddr;
                        break;
                    }
                }
                if (xrefAddr) break;
            }
            if (xrefAddr) break;
        }

        if (!xrefAddr) {
            this.sendError("Could not resolve InsertPacketInternal: XREF not found.");
            return;
        }

        let addr = null;
        let cursor = xrefAddr;
        for (let i = 0; i < 4000; i++) {
            cursor = cursor.sub(1);
            if (cursor.readU8() === 0x41 && cursor.add(1).readU8() === 0x57 && cursor.add(2).readU8() === 0x41 && cursor.add(3).readU8() === 0x56) {
                addr = cursor;
                break;
            }
        }

        if (!addr) {
            this.sendError("Could not resolve InsertPacketInternal via XREF backward trace.");
            return;
        }

        send({ type: 'status', message: 'Successfully resolved InsertPacketInternal at ' + addr });

        const _this = this;
        Interceptor.attach(addr, {
            onEnter: function(args) {
                try {
                    const ssrc = args[1].add(8).readU32();
                    
                    if (_this.audioSsrcOffset === null) {
                        _this.tryResolveSsrcOffset(ssrc);
                    }
                    
                    const dataPtr = args[2].readPointer();
                    const dataSize = args[2].add(8).readU32();
                    
                    if (dataSize > 0 && dataSize < 2000) {
                        const payload = dataPtr.readByteArray(dataSize);
                        send({ type: 'payload', ssrc: ssrc }, payload);
                    }
                } catch(e) {
                    _this.sendError("InsertPacketInternal Error: " + e.stack);
                }
            }
        });
    }
}

const hooker = new DiscordVoiceHook();
hooker.init();