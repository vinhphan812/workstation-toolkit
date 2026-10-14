from workstation.adapters.windows import WindowsAdapter
from workstation.adapters.linux import LinuxAdapter
from workstation.adapters.macos import MacOSAdapter

def test_adapters_have_expected_interface():
    for adapter in [WindowsAdapter(), LinuxAdapter(), MacOSAdapter()]:
        assert adapter.name
        assert callable(adapter.get_firewall_status)
        assert callable(adapter.get_startup_items)
        assert callable(adapter.get_system_logs)
        assert callable(adapter.get_package_manager)
