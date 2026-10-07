"""Stage canonical SDK contracts in both wheels and source distributions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    """Include the one canonical contract tree without a checked-in copy.

    A source distribution must rebuild without a checkout of the whole SDK
    workspace. During an sdist build this hook maps canonical repository files
    into the Python package path. During a wheel build from that sdist those
    staged files already exist in the package, so no external path is needed.
    """

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        package_contracts = Path(self.root) / "src/syntara_plugin/contracts"
        required = ("schemas", "fixtures", "proto")
        if all((package_contracts / name).is_dir() for name in required):
            return

        canonical_contracts = Path(self.root).parents[3] / "contracts"
        for name in required:
            source = canonical_contracts / name
            if not source.is_dir():
                raise RuntimeError(f"canonical contract directory is missing: {source}")
            build_data["force_include"][str(source)] = f"src/syntara_plugin/contracts/{name}"
