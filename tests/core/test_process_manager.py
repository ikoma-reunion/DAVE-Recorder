import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'src'))

from core.process_manager import ProcessManager

def test_process_manager():
    # Only run this if real Discord is running, otherwise it's just empty list
    instances = ProcessManager.get_discord_instances()
    assert isinstance(instances, list)
    for inst in instances:
        assert inst.flavor in ["Stable", "PTB", "Canary", "Development"]
        assert inst.voice_pid > 0
        assert inst.renderer_pid > 0

def test_process_manager_caching(monkeypatch):
    # Reset cache
    ProcessManager._cached_voice_pids = {}
    
    mock_psutil_process_iter = MagicMock()
    
    class MockProcess:
        def __init__(self, pid, name, exe, cmdline):
            self.info = {
                'pid': pid,
                'name': name,
                'exe': exe,
                'cmdline': cmdline
            }
            
    mock_processes = [
        MockProcess(100, "Discord.exe", "C:\\Discord\\Discord.exe", ["--type=renderer"]), # Renderer
        MockProcess(200, "Discord.exe", "C:\\Discord\\Discord.exe", ["--type=gpu-process"]), # Ignored
        MockProcess(300, "Discord.exe", "C:\\Discord\\Discord.exe", ["--type=utility"]), # Will fail attach
        MockProcess(400, "Discord.exe", "C:\\Discord\\Discord.exe", ["--type=utility"])  # Voice process
    ]
    
    mock_psutil_process_iter.return_value = mock_processes
    monkeypatch.setattr("core.process_manager.psutil.process_iter", mock_psutil_process_iter)
    
    mock_frida_attach = MagicMock()
    
    class MockSession:
        def create_script(self, code):
            script = MagicMock()
            def load():
                # Simulate payload message
                if self.pid == 400:
                    script.on.call_args[0][1]({'type': 'send', 'payload': True}, None)
                else:
                    script.on.call_args[0][1]({'type': 'send', 'payload': False}, None)
            script.load = load
            return script
        def detach(self):
            pass
            
    def side_effect(pid):
        if pid == 300:
            raise Exception("Frida attach error")
        session = MockSession()
        session.pid = pid
        return session
        
    mock_frida_attach.side_effect = side_effect
    monkeypatch.setattr("core.process_manager.frida.attach", mock_frida_attach)
    
    # Call 1
    instances = ProcessManager.get_discord_instances()
    assert len(instances) == 1
    assert instances[0].voice_pid == 400
    assert instances[0].renderer_pid == 100
    
    assert mock_frida_attach.call_count == 3 # 100, 300, 400
    
    mock_frida_attach.reset_mock()
    
    # Call 2
    instances = ProcessManager.get_discord_instances()
    assert len(instances) == 1
    assert instances[0].voice_pid == 400
    
    assert mock_frida_attach.call_count == 0 # Should use cache
    
    # Simulate process died (400 is gone)
    mock_processes.pop()
    mock_frida_attach.reset_mock()
    
    instances = ProcessManager.get_discord_instances()
    assert len(instances) == 0
    assert mock_frida_attach.call_count == 2 # 100, 300 again