import struct

class OggOpusWriter:
    """A minimal pure-Python Ogg Opus file writer."""
    def __init__(self, filename, ssrc):
        self.filename = filename
        self.file = open(self.filename, "wb")
        self.ssrc = ssrc
        self.page_seq = 0
        self.granule_pos = 0
        self.crc_table = self._generate_crc_table()
        self.headers_written = False

    def set_filename(self, new_filename):
        if self.filename == new_filename:
            return
        self.file.close()
        import os
        os.rename(self.filename, new_filename)
        self.filename = new_filename
        self.file = open(self.filename, "ab")

    def _write_headers(self, is_stereo):
        channels = 2 if is_stereo else 1
        
        # Ogg Opus Header (OpusHead)
        opus_head = struct.pack("<8sBBHIHB", b"OpusHead", 1, channels, 0, 48000, 0, 0)
        self._write_page(opus_head, bof=True)
        
        # Ogg Opus Comment Header (OpusTags)
        vendor = b"dave_recorder_gui"
        opus_tags = struct.pack("<8sI", b"OpusTags", len(vendor)) + vendor + struct.pack("<I", 0)
        self._write_page(opus_tags)
        
        self.headers_written = True

    def _generate_crc_table(self):
        table = []
        for i in range(256):
            crc = i << 24
            for _ in range(8):
                if crc & 0x80000000:
                    crc = (crc << 1) ^ 0x04C11DB7
                else:
                    crc <<= 1
            table.append(crc & 0xFFFFFFFF)
        return table

    def _crc32(self, data):
        crc = 0
        for byte in data:
            crc = (crc << 8) ^ self.crc_table[((crc >> 24) ^ byte) & 0xFF]
            crc &= 0xFFFFFFFF
        return crc

    def _write_page(self, payload, bof=False, eof=False):
        header_type = 0
        if bof:
            header_type |= 0x02
        if eof:
            header_type |= 0x04
        
        header_base = struct.pack("<4sBBqII", b"OggS", 0, header_type, self.granule_pos, self.ssrc, self.page_seq)
        
        segments = []
        remain = len(payload)
        while remain >= 255:
            segments.append(255)
            remain -= 255
        segments.append(remain)
        
        segment_table = struct.pack("B", len(segments)) + bytes(segments)
        header_with_zero_crc = header_base + struct.pack("<I", 0) + segment_table
        page_data = header_with_zero_crc + payload
        
        crc = self._crc32(page_data)
        page_data = page_data[:22] + struct.pack("<I", crc) + page_data[26:]
        
        self.file.write(page_data)
        self.file.flush()
        self.page_seq += 1

    def write_packet(self, payload):
        if len(payload) == 0:
            return
            
        toc = payload[0]
        if not self.headers_written:
            # Check the stereo flag in the Opus TOC byte (bit 2)
            is_stereo = (toc & 0x04) != 0
            self._write_headers(is_stereo)
            
        # Assuming 20ms frames at 48kHz = 960 samples
        samples = 960 
        
        self.granule_pos += samples
        self._write_page(payload)

    def close(self):
        try:
            if hasattr(self, 'file') and not self.file.closed:
                self.file.close()
        except Exception as e:
            import traceback
            import sys
            print(f"Error closing OggOpusWriter file: {e}\n{traceback.format_exc()}", file=sys.stderr)
            sys.exit(1)

    def __del__(self):
        try:
            if hasattr(self, 'file') and not self.file.closed:
                self.file.close()
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Error in OggOpusWriter destructor: {e}")