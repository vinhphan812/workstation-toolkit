"""Base adapter interface."""
from abc import ABC, abstractmethod

class PlatformAdapter(ABC):
    name: str

    @abstractmethod
    def get_firewall_status(self) -> dict:
        """Return firewall status. Return None if unsupported."""

    @abstractmethod
    def get_startup_items(self) -> list:
        """Return startup processes/tasks."""

    @abstractmethod
    def get_system_logs(self, lines: int = 50) -> str:
        """Return recent system log entries."""

    @abstractmethod
    def get_package_manager(self) -> str:
        """Return the OS package manager name, or ''."""
