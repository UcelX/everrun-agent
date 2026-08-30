from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EnvironmentSnapshot:
    values: dict[str, str]


@dataclass(frozen=True)
class EnvironmentValidation:
    changed: tuple[str, ...]
    stale: tuple[str, ...]
    safe: bool


def validate_environment(
    previous: EnvironmentSnapshot,
    current: EnvironmentSnapshot,
    dependencies: dict[str, tuple[str, ...]],
) -> EnvironmentValidation:
    changed = tuple(
        sorted(
            key for key in previous.values if previous.values.get(key) != current.values.get(key)
        )
    )
    stale: list[str] = []
    invalid = set(changed)
    progressed = True
    while progressed:
        progressed = False
        for component, requirements in dependencies.items():
            if component not in invalid and any(required in invalid for required in requirements):
                invalid.add(component)
                stale.append(component)
                progressed = True
    return EnvironmentValidation(changed, tuple(stale), not changed and not stale)
