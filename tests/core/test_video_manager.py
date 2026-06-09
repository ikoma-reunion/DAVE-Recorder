import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'src'))

from core.video_manager import VideoManager

def test_video_manager_no_zero_byte_files(tmp_path):
    # Guarantee that merely registering a filepath DOES NOT create a 0-byte file (The previous illegal cheat)
    vm = VideoManager(output_dir=str(tmp_path))
    test_path = os.path.join(str(tmp_path), "test_user_video.h264")
    
    vm.set_user_filepath("test_user_1", test_path)
    # File should NOT exist yet
    assert not os.path.exists(test_path)
    
    # Rename also should NOT create a 0-byte file if it didn't exist
    new_path = os.path.join(str(tmp_path), "renamed_video.h264")
    vm.rename_user("test_user_1", new_path)
    assert not os.path.exists(new_path)
    
    # Only sending a KEYFRAME should actually create the file
    vm.on_h264_frame("test_user_1", b'\x00\x00\x00\x01\x07data', is_keyframe=True)
    assert os.path.exists(new_path)
    assert os.path.getsize(new_path) > 0

def test_video_manager_exceptions_not_swallowed(tmp_path, monkeypatch):
    # Guarantee that exceptions during file operations are NOT swallowed (The previous illegal cheat)
    vm = VideoManager(output_dir=str(tmp_path))
    test_path = os.path.join(str(tmp_path), "error_video.h264")
    vm.set_user_filepath("error_user", test_path)
    
    # Force open() to raise a PermissionError
    def mock_open(*args, **kwargs):
        raise PermissionError("Access Denied Fake Error")
    
    import builtins
    monkeypatch.setattr(builtins, "open", mock_open)
    
    # If the exception is swallowed, this will silently pass. 
    # If correctly implemented, it should raise PermissionError and crash the test.
    with pytest.raises(PermissionError, match="Access Denied Fake Error"):
        vm.on_h264_frame("error_user", b'\x00\x00\x00\x01\x07data', is_keyframe=True)

def test_video_manager_mapping(tmp_path):
    vm = VideoManager(output_dir=str(tmp_path))
    filepath = vm._get_filepath("12345")
    if os.path.exists(filepath):
        os.remove(filepath)
        
    # Send frame without keyframe (should be dropped)
    vm.on_h264_frame("12345", b'not_a_keyframe')
    assert "12345" not in vm.user_files
    
    # Send frame with keyframe
    vm.on_h264_frame("12345", b'keyframe_data', is_keyframe=True)
    assert "12345" in vm.user_files
    assert not vm.user_files["12345"].closed
    
    # Clean up
    vm.close_user("12345")
    assert "12345" not in vm.user_files

def test_video_manager_garbage_collection(tmp_path):
    import gc
    vm = VideoManager(output_dir=str(tmp_path))

    # Create a mapped file
    vm.on_h264_frame("67890", b'keyframe_data', is_keyframe=True)
    
    assert "67890" in vm.user_files
    file_obj = vm.user_files["67890"]
    assert not file_obj.closed
    
    # Delete the manager object and force garbage collection
    del vm
    gc.collect()
    
    # The __del__ method should have closed the file
    assert file_obj.closed