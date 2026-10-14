"""macOS platform adapter."""
import subprocess
from workstation.adapters.base import PlatformAdapter

class MacOSAdapter(PlatformAdapter):
    name = "darwin"

    def get_firewall_status(self) -> dict:
        r = subprocess.run(["/usr/libexec/ApplicationFirewall/socketfilterfw", "--getglobalstate"],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            return {"status": "supported", "platform": "darwin", "raw": r.stdout.strip()}
        return {"status": "unsupported", "platform": "darwin"}

    def get_startup_items(self) -> list:
        items = []
        r = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            items.append({"type": "launchd", "count": len(r.stdout.splitlines())})
        return items

    def get_system_logs(self, lines: int = 50) -> str:
        r = subprocess.run(["log", "show", "--last", "1h", "--predicate", "TRUEPREDICATE",
                             f"--lines={lines}"],
                            capture_output=True, text=True, timeout=15)
        return r.stdout[:2000] if r.returncode == 0 else r.stderr[:500]

    def get_package_manager(self) -> str:
        r = subprocess.run(["which", "brew"], capture_output=True, text=True)
        return "brew" if r.returncode == 0 else ""
