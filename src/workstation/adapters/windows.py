"""Windows platform adapter."""
import subprocess, platform
from workstation.adapters.base import PlatformAdapter

class WindowsAdapter(PlatformAdapter):
    name = "windows"

    def get_firewall_status(self) -> dict:
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-NetFirewallProfile | Select-Object Name,Enabled | ConvertTo-Json"],
                capture_output=True, text=True, timeout=15,
            )
            if r.returncode == 0:
                import json
                profiles = json.loads(r.stdout)
                if isinstance(profiles, dict):
                    profiles = [profiles]
                return {
                    "status": "supported",
                    "platform": "windows",
                    "profiles": {p["Name"]: p["Enabled"] for p in profiles},
                    "all_off": all(not p["Enabled"] for p in profiles),
                }
        except Exception:
            pass
        return {"status": "error", "platform": "windows", "profiles": {}}

    def get_startup_items(self) -> list:
        items = []
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_StartupCommand | Select-Object Name,Location,Command | ConvertTo-Json"],
                capture_output=True, text=True, timeout=15,
            )
            if r.returncode == 0:
                import json
                data = json.loads(r.stdout)
                if isinstance(data, dict):
                    data = [data]
                items = [{"name": i.get("Name",""), "location": i.get("Location",""), "command": i.get("Command","")} for i in data]
        except Exception:
            pass
        return items

    def get_system_logs(self, lines: int = 50) -> str:
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"Get-EventLog -LogName System -Newest {lines} | Select-Object TimeGenerated,EntryType,Source,Message | ConvertTo-Json"],
                capture_output=True, text=True, timeout=20,
            )
            if r.returncode == 0:
                return r.stdout[:2000]
        except Exception:
            pass
        return ""

    def get_package_manager(self) -> str:
        return "winget"  # or "choco" if installed
