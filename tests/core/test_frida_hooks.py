import frida
import time
import os
import pytest
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'src'))

from core.process_manager import ProcessManager

def test_frida_dynamic_resolution():
    """
    This test verifies that the Frida hook script can successfully
    dynamically resolve the XREF signatures and export addresses
    without crashing or relying on hardcoded offsets.
    """
    instances = ProcessManager.get_discord_instances()
    if not instances:
        pytest.skip("No Discord instances running to test against.")
        
    inst = instances[-1]
    
    try:
        session = frida.attach(inst.voice_pid)
    except Exception as e:
        pytest.skip(f"Failed to attach Frida for test: {e}")
        
    script_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'src', 'frida_scripts', 'voice_hook.js')
    
    with open(script_path, 'r', encoding='utf-8') as f:
        js_code = f.read()
        
    wrapper_js = js_code + """
    send({ type: 'test_result', begin: hooker.vectorBeginOffset, end: hooker.vectorEndOffset, ctx: hooker.voiceCtxOffset });
    """
    
    script = session.create_script(wrapper_js)
    
    result_data = {}
    error_occurred = False
    
    def on_message(message, data):
        nonlocal result_data, error_occurred
        if message['type'] == 'send':
            payload = message['payload']
            if payload['type'] == 'error':
                error_occurred = True
                print("Test Error:", payload['description'])
            elif payload['type'] == 'test_result':
                result_data['begin'] = payload['begin']
                result_data['end'] = payload['end']
                result_data['ctx'] = payload['ctx']
    
    script.on('message', on_message)
    script.load()
    
    time.sleep(2)
    session.detach()
    
    assert not error_occurred, "Frida script threw an error during dynamic resolution."
    
    assert 'begin' in result_data and result_data['begin'] is not None, "vectorBeginOffset was not resolved."
    assert 'end' in result_data and result_data['end'] is not None, "vectorEndOffset was not resolved."
    assert 'ctx' in result_data and result_data['ctx'] is not None, "voiceCtxOffset was not resolved."
    
    assert result_data['end'] > result_data['begin'], "Invalid vector offsets resolved."