"""System, developer environment, and project scanners for TuxHarbor."""

from tuxharbor.scanners.windows_apps import (
    detect_system_hardware,
    get_demo_apps,
    scan_installed_apps,
)
from tuxharbor.scanners.dev_tools import scan_dev_environment
from tuxharbor.scanners.projects import scan_projects_folders, detect_suggested_project_dirs

__all__ = [
    "scan_installed_apps",
    "detect_system_hardware",
    "get_demo_apps",
    "scan_dev_environment",
    "scan_projects_folders",
    "detect_suggested_project_dirs",
]
