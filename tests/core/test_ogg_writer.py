import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'src'))

from core.ogg_writer import OggOpusWriter

def test_ogg_writer(tmp_path):
    filename = tmp_path / "test.opus"
    writer = OggOpusWriter(str(filename), 12345)
    
    # 1 byte payload: TOC byte for Opus (stereo, 20ms)
    payload = b"\xfc\xff\xfe" 
    writer.write_packet(payload)
    writer.close()
    
    assert filename.exists()
    content = filename.read_bytes()
    
    assert content.startswith(b"OggS")
    assert b"OpusHead" in content
    assert b"OpusTags" in content
    assert payload in content

def test_ogg_writer_set_filename(tmp_path):
    filename1 = tmp_path / "test1.opus"
    filename2 = tmp_path / "test2.opus"
    
    writer = OggOpusWriter(str(filename1), 12345)
    writer.write_packet(b"\xfc\xff\xfe")
    
    assert filename1.exists()
    assert not filename2.exists()
    
    writer.set_filename(str(filename2))
    
    assert not filename1.exists()
    assert filename2.exists()
    
    # Write another packet after rename
    writer.write_packet(b"\xfc\xff\xfe")
    writer.close()
    
    content = filename2.read_bytes()
    assert content.startswith(b"OggS")
    assert b"OpusHead" in content

def test_ogg_writer_garbage_collection(tmp_path):
    import gc
    filename = str(tmp_path / "test_gc.opus")
    writer = OggOpusWriter(filename, 12345)
    
    # Keep a reference to the internal file object
    file_obj = writer.file
    assert not file_obj.closed
    
    # Delete the writer object and force garbage collection
    del writer
    gc.collect()
    
    # The __del__ method should have been called and closed the file
    assert file_obj.closed