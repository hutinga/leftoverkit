"""Local cleanup settings, independent of repository content."""

from dataclasses import dataclass, fields
from pathlib import Path

from .repo import SafetyError, read_json


@dataclass(frozen=True)
class Settings:
    scratch_hours: int = 48
    worktree_hours: int = 72
    report_days: int = 7
    review_hours: int = 24
    retention_days: int = 14
    scan_limit: int = 25_000

    @classmethod
    def load(cls, state: Path) -> "Settings":
        data = read_json(state / "config.json", {})
        names = {field.name for field in fields(cls)}
        if not isinstance(data, dict) or not data.keys() <= names:
            raise SafetyError("Invalid settings or unknown key in config.json.")
        if any(type(value) is not int or not 0 < value <= 1_000_000 for value in data.values()):
            raise SafetyError("Cleanup settings must be positive integers no greater than 1,000,000.")
        return cls(**data)
