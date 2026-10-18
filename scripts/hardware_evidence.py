#!/usr/bin/env python3
"""A recorded install of one image on one real Mac, the gate for an image the
VM acceptance harness cannot boot.

The harness (omarchy-mac-pkgs tools/acceptance/mac-image) boots an image on
QEMU's virt machine with a generic Arch Linux ARM kernel and an M1 Pro root
compatible. It runs nothing a board-specific image boots with (m1n1, Stage 1,
the Aurora kernel), so it says nothing about a MacBook Neo image. A Neo image
is installed on a Neo by hand instead, and the tester records it:

  {"kind": "hardware-install", "image": "omarchy-mac-edge-<date>-<set id>",
   "image_sha256": "<the payload zip's sha256>", "board": "apple,j700",
   "installer_version": "2.3.0", "tester": "<who installed it>",
   "result": "pass", "recorded_at": "<optional>", "notes": "<optional>"}

It is an explicit workflow input that the release pipeline's dispatcher
supplies and the catalog-release approver reviews, never something a job
writes. Only edge takes one, and only for a board whose image has its own
hardware profile (scripts/supported-models.json `hardware_profiles`).
docs/catalog-release.md describes the format.

Usage:
  hardware_evidence.py describe FILE   check FILE's form for edge and print
                                       its image= and sha256=
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import supported_models  # noqa: E402

KIND = "hardware-install"
CHANNELS = ("edge",)
REQUIRED = frozenset({"kind", "image", "image_sha256", "board", "installer_version", "tester", "result"})
OPTIONAL = frozenset({"recorded_at", "notes"})
SHA256 = re.compile(r"^[0-9a-f]{64}$")
VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
IMAGE_NAME = re.compile(r"^omarchy-mac-([a-z]+)-[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9a-f]{12}$")


def version(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def check(document: object, image: str, image_sha256: str, channel: str) -> dict:
    """Raise ValueError unless DOCUMENT records a passing install of exactly
    IMAGE (whose payload is IMAGE_SHA256) on a board with its own image, for
    CHANNEL edge."""
    if channel not in CHANNELS:
        raise ValueError(f"hardware evidence is accepted for {' and '.join(CHANNELS)} only, not {channel}")
    if not isinstance(document, dict):
        raise ValueError("the hardware evidence record must be a JSON object")
    missing = REQUIRED - set(document)
    if missing:
        raise ValueError(f"the hardware evidence record has no {', '.join(sorted(missing))}")
    unknown = set(document) - REQUIRED - OPTIONAL
    if unknown:
        raise ValueError(f"the hardware evidence record has unknown keys {', '.join(sorted(unknown))}")
    if document["kind"] != KIND:
        raise ValueError(f"the hardware evidence record's kind must be {KIND}")
    recorded = document["image_sha256"]
    if not isinstance(recorded, str) or not SHA256.match(recorded):
        raise ValueError("the hardware evidence record's image_sha256 must be 64 lowercase hex digits")
    if recorded != image_sha256:
        raise ValueError(f"the hardware evidence is for image sha256 {recorded}, not {image_sha256}")
    if not isinstance(image, str) or not IMAGE_NAME.match(image) or IMAGE_NAME.match(image).group(1) != channel:
        raise ValueError(f"{image!r} is not an image name for {channel} (omarchy-mac-{channel}-<YYYY.MM.DD>-<set id>)")
    if document["image"] != image:
        raise ValueError(f"the hardware evidence is for image {document['image']!r}, not {image}")
    board = document["board"]
    if not isinstance(board, str):
        raise ValueError("the hardware evidence record's board must be a board identifier")
    profiles = {identifier: supported_models.hardware_profile(identifier)
                for identifier in supported_models.load()[0]}
    if profiles.get(board, supported_models.LEGACY) == supported_models.LEGACY:
        raise ValueError(f"hardware evidence is only for a Mac with its own image, not {board!r}; "
                         "M1, M2 and M3 images pass VM acceptance")
    if not isinstance(document["installer_version"], str) or not VERSION.match(document["installer_version"]):
        raise ValueError("the hardware evidence record's installer_version must look like X.Y.Z")
    tester = document["tester"]
    if not isinstance(tester, str) or not 0 < len(tester.strip()) <= 200:
        raise ValueError("the hardware evidence record must name its tester")
    if document["result"] != "pass":
        raise ValueError(f"the hardware evidence for {image_sha256} did not pass (result: {document['result']!r})")
    for key in OPTIONAL & set(document):
        if not isinstance(document[key], str) or len(document[key]) > 2000:
            raise ValueError(f"the hardware evidence record's {key} must be a short string")
    return document


def main(arguments: list[str]) -> int:
    if len(arguments) != 2 or arguments[0] != "describe":
        print(__doc__.split("Usage:\n", 1)[1].rstrip(), file=sys.stderr)
        return 64
    try:
        document = json.loads(Path(arguments[1]).read_text())
        if not isinstance(document, dict):
            raise ValueError("the hardware evidence record must be a JSON object")
        check(document, document.get("image"), document.get("image_sha256"), "edge")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        print(f"hardware evidence: refused: {error}", file=sys.stderr)
        return 1
    print(f"image={document['image']}")
    print(f"sha256={document['image_sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
