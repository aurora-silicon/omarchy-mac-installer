#!/usr/bin/env python3
"""The Macs every Omarchy Mac catalog must enable, and the ones it must refuse.

`supported-models.json` is the single list: every M1, M2 and M3 Mac the
pinned engine can inspect, and the MacBook Neo. A catalog that offers any Mac
offers every M1, M2 and M3 Mac, so a release or preview can never ship a
subset by accident. A channel with no Mac release yet (an empty catalog) is
the only exception. `refused` names each board that stays out and why.
`developer` names each board only a developer build's sealed catalog may add,
with its own image; channel catalogs never carry one, so check-catalog
rejects it like any unknown board.

`hardware_profiles` names the supported Macs that boot only an image built
with their own hardware profile (the MacBook Neo: `neo`); every other
supported Mac takes the one legacy image. A catalog may leave such a Mac out
(edge offers it only while its image has evidence, rc and stable never do),
and when it lists one, that Mac's payload is its own: no image is shared
between hardware profiles. `untested` marks the supported Macs no image has
been qualified on yet, with the note a catalog shows for each.

Usage:
  supported_models.py check-catalog FILE   exit 1 unless FILE covers every Mac
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

MANIFEST = Path(__file__).resolve().with_name("supported-models.json")
LEGACY = "legacy"
PROFILES = (LEGACY, "neo")


def load(path: Path = MANIFEST) -> tuple[list[str], dict[str, str]]:
    document = json.loads(path.read_text())
    if document.get("schema_version") != 1:
        raise SystemExit(f"{path}: unsupported schema")
    supported, refused = document["supported"], document["refused"]
    if len(set(supported)) != len(supported):
        raise SystemExit(f"{path}: supported lists a Mac twice")
    if set(supported) & set(refused):
        raise SystemExit(f"{path}: a Mac is both supported and refused")
    if set(document.get("developer", {})) & (set(supported) | set(refused)):
        raise SystemExit(f"{path}: a developer board is also supported or refused")
    profiles = document.get("hardware_profiles", {})
    if not isinstance(profiles, dict) or not all(
        profile in PROFILES and profile != LEGACY for profile in profiles.values()
    ):
        raise SystemExit(f"{path}: hardware_profiles maps each Mac to a non-legacy profile")
    if set(profiles) - set(supported):
        raise SystemExit(f"{path}: hardware_profiles names unsupported Macs")
    return supported, refused


def developer_boards(path: Path = MANIFEST) -> dict[str, str]:
    """The boards only a developer build's sealed catalog may add, with why."""
    load(path)
    return dict(json.loads(path.read_text()).get("developer", {}))


def hardware_profile(identifier: str, path: Path = MANIFEST) -> str:
    """The hardware profile of the image a supported Mac boots."""
    supported, _ = load(path)
    if identifier not in supported:
        raise SystemExit(f"{identifier} is not a supported Mac")
    return json.loads(path.read_text()).get("hardware_profiles", {}).get(identifier, LEGACY)


def required(path: Path = MANIFEST) -> list[str]:
    """The Macs every catalog that offers any Mac must enable: every M1, M2
    and M3 Mac, all on the legacy image."""
    supported, _ = load(path)
    return [identifier for identifier in supported if hardware_profile(identifier, path) == LEGACY]


def untested(path: Path = MANIFEST) -> dict[str, str]:
    """Supported Macs no Omarchy image has been qualified on yet, each with
    the note a catalog shows for it."""
    supported, _ = load(path)
    notes = json.loads(path.read_text()).get("untested", {})
    if not isinstance(notes, dict) or not all(
        isinstance(note, str) and note for note in notes.values()
    ):
        raise SystemExit(f"{path}: untested maps each Mac to a note")
    stray = set(notes) - set(supported)
    if stray:
        raise SystemExit(f"{path}: untested names unsupported Macs: {', '.join(sorted(stray))}")
    return notes


def device_class(identifier: str) -> str:
    """apple,j314s -> j314sap, the engine's name for the board."""
    return identifier.removeprefix("apple,") + "ap"


def admitted(installer_data: object) -> list[str]:
    """The supported Macs an image's installer_data.json lets the engine
    install on: its one Omarchy target admits a Mac whose device class is in
    allowed_device_classes (when that is set) and not in
    excluded_device_classes."""
    supported, _ = load()
    os_list = installer_data.get("os_list") if isinstance(installer_data, dict) else None
    targets = [
        target for target in os_list or []
        if isinstance(target, dict) and target.get("omarchy_target") == "apple-silicon-full-os"
    ]
    if len(targets) != 1:
        raise ValueError("installer_data.json must hold exactly one Omarchy full-OS target")
    allowed = targets[0].get("allowed_device_classes")
    excluded = targets[0].get("excluded_device_classes", [])
    if not (allowed is None or isinstance(allowed, list)) or not isinstance(excluded, list):
        raise ValueError("installer_data.json device class lists must be lists")
    return [
        identifier for identifier in supported
        if (allowed is None or device_class(identifier) in allowed) and device_class(identifier) not in excluded
    ]


def coverage_errors(identifiers: list[str]) -> list[str]:
    """Why IDENTIFIERS (the Macs a catalog enables) is not a supported set
    holding every M1, M2 and M3 Mac."""
    supported, refused = load()
    errors = []
    missing = [identifier for identifier in required() if identifier not in identifiers]
    if missing:
        errors.append(
            "every M1, M2 and M3 Mac must be enabled; missing "
            + ", ".join(missing)
        )
    for identifier in identifiers:
        if identifier in refused:
            errors.append(f"{identifier} is refused: {refused[identifier]}")
        elif identifier not in supported:
            errors.append(
                f"{identifier} is not in scripts/supported-models.json; "
                "add it there, with its engine and device-tree support, first"
            )
    return errors


def payload_errors(models: list[dict]) -> list[str]:
    """Why MODELS share a payload across hardware profiles: the legacy image
    must not claim a Neo, and a Neo image must not claim an M1, M2 or M3."""
    supported, _ = load()
    profiles: dict[object, dict[str, list[str]]] = {}
    for model in models:
        identifier = model.get("deviceIdentifier")
        if identifier in supported:
            profiles.setdefault(model.get("payloadDigest"), {}).setdefault(
                hardware_profile(identifier), []).append(identifier)
    return [
        f"payload {digest} is shared by "
        + " and ".join(f"{profile} Macs ({', '.join(boards)})" for profile, boards in sorted(groups.items()))
        + "; each hardware profile needs its own image"
        for digest, groups in profiles.items()
        if len(groups) > 1
    ]


def catalog_errors(catalog: dict) -> list[str]:
    models = catalog.get("models")
    if not isinstance(models, list):
        return ["the catalog has no models list"]
    if not models:
        return []
    enabled = [model for model in models if model.get("status") == "enabled"]
    errors = [
        f"{model.get('deviceIdentifier')} is listed but {model.get('status')}"
        for model in models
        if model.get("status") != "enabled"
    ]
    return (errors + coverage_errors([model.get("deviceIdentifier") for model in enabled])
            + payload_errors(enabled))


def main(arguments: list[str]) -> int:
    if len(arguments) != 2 or arguments[0] != "check-catalog":
        print(__doc__.strip().splitlines()[-1].strip(), file=sys.stderr)
        return 64
    errors = catalog_errors(json.loads(Path(arguments[1]).read_text()))
    for error in errors:
        print(f"catalog model coverage: {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
