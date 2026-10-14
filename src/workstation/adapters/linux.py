"""Linux platform adapter."""
import subprocess, platform
from workstation.adapters.base import PlatformAdapter

class LinuxAdapter(PlatformAdapter):
    name = "linux"

    def get_firewall_status(self) -> dict:
        # Check ufw
        r = subprocess.run(["which", "ufw"], capture_output=True, text=True)
        if r.returncode == 0:
            r = subprocess.run(["ufw", "status"], capture_output=True, text=True, timeout=5)
            active = "active" in r.stdout.lower()
            return {"status": "supported", "platform": "linux", "ufw_active": active}
        # Check firewalld
        r = subprocess.run(["which", "firewalld"], capture_output=True, text=True)
        if r.returncode == 0:
            return {"status": "supported", "platform": "linux", "firewalld": "available"}
        return {"status": "unsupported", "platform": "linux", "reason": "no ufw or firewalld found"}

    def get_startup_items(self) -> list:
        items = []
        # systemd user services
        r = subprocess.run(["systemctl", "--user", "list-unit-files", "--type=service"],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            for line in r.stdout.splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 2 and parts[1] == "enabled":
                    items.append({"type": "systemd-user", "unit": parts[0]})
        # cron
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            items.append({"type": "crontab", "entries": len([l for l in r.stdout.splitlines() if l and not l.startswith("#")])})
        return items

    def get_system_logs(self, lines: int = 50) -> str:
        r = subprocess.run(["journalctl", "-n", str(lines), "--no-pager"],
                           capture_output=True, text=True, timeout=10)
        return r.stdout[:2000] if r.returncode == 0 else r.stderr[:500]

    def get_package_manager(self) -> str:
        # Detect
        for pm in ["apt", "dnf", "pacman", "zypper"]:
            r = subprocess.run(["which", pm], capture_output=True, text=True)
            if r.returncode == 0:
                return pm
        return ""
