import psutil
import frida
import logging

class DiscordInstance:
    def __init__(self, flavor, exe_path):
        self.flavor = flavor
        self.exe_path = exe_path
        self.voice_pid = None
        self.renderer_pid = None

    def is_valid(self):
        return self.voice_pid is not None and self.renderer_pid is not None

    def __str__(self):
        return f"{self.flavor} (Voice PID: {self.voice_pid}, Renderer PID: {self.renderer_pid})"

class ProcessManager:
    _cached_voice_pids = {}

    @staticmethod
    def get_discord_instances():
        instances = {}
        pid_groups = {}
        
        for p in psutil.process_iter(['pid', 'name', 'exe', 'cmdline']):
            try:
                name = p.info['name']
                if not name or "discord" not in name.lower():
                    continue
                    
                exe_path = p.info['exe']
                cmdline = p.info['cmdline'] or []
                
                if not exe_path:
                    continue
                    
                if exe_path not in instances:
                    flavor = "Stable"
                    if "ptb" in name.lower():
                        flavor = "PTB"
                    elif "canary" in name.lower():
                        flavor = "Canary"
                    elif "development" in name.lower():
                        flavor = "Development"
                    instances[exe_path] = DiscordInstance(flavor, exe_path)
                    pid_groups[exe_path] = []
                    
                pid_groups[exe_path].append(p.info)
                
                inst = instances[exe_path]
                cmdline_str = " ".join(cmdline)
                
                if "--type=renderer" in cmdline_str:
                    if "--extension-process" not in cmdline_str and "background-page" not in cmdline_str and "crashpad" not in cmdline_str:
                        if inst.renderer_pid is None:
                            inst.renderer_pid = p.info['pid']

            except psutil.NoSuchProcess:
                continue
            except psutil.AccessDenied:
                continue
            except Exception as e:
                logging.getLogger(__name__).error(f"Unexpected error while iterating processes: {e}")
                continue
                
        valid_instances = []
        for exe_path, inst in instances.items():
            pids = pid_groups[exe_path]
            
            # Check cache first
            cached_pid = ProcessManager._cached_voice_pids.get(exe_path)
            if cached_pid is not None:
                if any(pinfo['pid'] == cached_pid for pinfo in pids):
                    inst.voice_pid = cached_pid
                    if inst.is_valid():
                        valid_instances.append(inst)
                    continue
                else:
                    del ProcessManager._cached_voice_pids[exe_path]

            for pinfo in pids:
                cmdline_str = " ".join(pinfo['cmdline'] or [])
                if "--type=gpu-process" in cmdline_str or "--type=crashpad-handler" in cmdline_str:
                    continue
                    
                try:
                    session = frida.attach(pinfo['pid'])
                    check_script = session.create_script("send(Process.findModuleByName('discord_voice.node') !== null);")
                    module_found = False
                    def on_check_message(message, data):
                        nonlocal module_found
                        if message['type'] == 'send':
                            module_found = message['payload']
                    check_script.on('message', on_check_message)
                    check_script.load()
                    session.detach()
                    
                    if module_found:
                        inst.voice_pid = pinfo['pid']
                        ProcessManager._cached_voice_pids[exe_path] = pinfo['pid']
                        break
                except Exception as e:
                    # Downgrade to DEBUG so it doesn't spam unless explicitly enabled
                    logging.debug(f"Skipping PID {pinfo['pid']} due to Frida attach error: {e}")
                    continue
                    
            if inst.is_valid():
                valid_instances.append(inst)
                
        return valid_instances