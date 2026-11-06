from __future__ import annotations

import shutil
import subprocess

from .models import ActionResult, ServiceInfo


class ServiceManager:
    def available(self) -> bool:
        return bool(shutil.which("systemctl"))

    def list_services(self) -> list[ServiceInfo]:
        if not self.available():
            return []
        command = [
            "systemctl",
            "show",
            "--type=service",
            "--all",
            "--no-pager",
            "--property=Id,Description,LoadState,ActiveState,SubState,UnitFileState",
        ]
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, check=False, timeout=12
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        blocks = completed.stdout.strip().split("\n\n")
        services: list[ServiceInfo] = []
        for block in blocks:
            values = {}
            for line in block.splitlines():
                if "=" in line:
                    key, value = line.split("=", 1)
                    values[key] = value
            name = values.get("Id", "")
            if not name:
                continue
            services.append(
                ServiceInfo(
                    name=name,
                    description=values.get("Description", ""),
                    load_state=values.get("LoadState", "unknown"),
                    active_state=values.get("ActiveState", "unknown"),
                    sub_state=values.get("SubState", "unknown"),
                    enabled_state=values.get("UnitFileState", "unknown"),
                )
            )
        return sorted(services, key=lambda item: item.name.casefold())

    def perform(self, service: ServiceInfo, action: str) -> ActionResult:
        if action not in {"start", "stop"}:
            return ActionResult(False, f"Unsupported service action: {action}")
        if not service.name.endswith(".service") or "/" in service.name:
            return ActionResult(False, "Invalid service name")
        command = ["systemctl", action, service.name]
        if shutil.which("pkexec"):
            command.insert(0, "pkexec")
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, check=False, timeout=90
            )
        except subprocess.TimeoutExpired:
            return ActionResult(False, "The authorization or service action timed out.")
        except OSError as error:
            return ActionResult(False, f"Could not run systemctl: {error}")
        if completed.returncode == 0:
            return ActionResult(True, f"{service.name} {action} completed")
        message = (completed.stderr or completed.stdout).strip()
        if "dismissed" in message.lower() or completed.returncode == 126:
            message = "Authorization was cancelled."
        return ActionResult(False, message or f"Could not {action} {service.name}")
