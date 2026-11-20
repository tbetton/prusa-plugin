#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWED_FILES = {".lua", ".json", ".stl", ".svg", ".png", ".md", ".txt"}
PLUGIN_ID = re.compile(r"[a-z0-9][a-z0-9-]*(?:\.[a-z0-9][a-z0-9-]*)+")
VERSION = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)
FOLDER = re.compile(r"[a-z0-9][a-z0-9._-]*")


def validate_bundle(folder):
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError(f"{folder.relative_to(ROOT)} must be a bundle directory")
    manifest = folder / "manifest.json"
    if manifest.is_symlink():
        raise ValueError(f"{manifest.relative_to(ROOT)} must be a regular file")
    fields = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(fields, dict):
        raise ValueError(f"{manifest.relative_to(ROOT)} must contain a JSON object")
    for field in ("id", "name", "version", "author", "license", "min_slicer_version"):
        if not isinstance(fields.get(field), str) or not fields[field].strip():
            raise ValueError(f"{manifest.relative_to(ROOT)} is missing {field}")
    if not PLUGIN_ID.fullmatch(fields["id"]):
        raise ValueError(f"{manifest.relative_to(ROOT)} needs a reverse-DNS ID")
    for field in ("version", "min_slicer_version"):
        if not VERSION.fullmatch(fields[field]):
            raise ValueError(f"{manifest.relative_to(ROOT)} has an invalid {field}")
    required_apis = fields.get("required_apis")
    if not isinstance(required_apis, dict) or not required_apis:
        raise ValueError(f"{manifest.relative_to(ROOT)} needs at least one required API")
    if any(not isinstance(version, str) or not VERSION.fullmatch(version)
           for version in required_apis.values()):
        raise ValueError(f"{manifest.relative_to(ROOT)} has an invalid API version")

    lua_count = 0
    for file in sorted(folder.rglob("*")):
        path = file.relative_to(ROOT)
        if file.is_symlink() or file.name.startswith("."):
            raise ValueError(f"{path} must be visible and must not be a symlink")
        if file.is_dir():
            continue
        if not file.is_file() or file.suffix not in ALLOWED_FILES:
            raise ValueError(f"{path} has a file type the Marketplace does not accept")
        if file.suffix == ".lua":
            lua_count += 1
    if not lua_count:
        raise ValueError(f"{folder.relative_to(ROOT)} has no Lua file")
    return fields


def release_bundle(tag):
    name, separator, version = tag.partition("/v")
    if not separator or not FOLDER.fullmatch(name) or not VERSION.fullmatch(version):
        raise ValueError("use a release tag like my-plugin/v0.1.0")
    folder = ROOT / "plugins" / name
    fields = validate_bundle(folder)
    if fields["version"] != version:
        raise ValueError(f"{tag} does not match manifest version {fields['version']}")
    if fields["author"] == "example-author":
        raise ValueError("set your Prusa Marketplace author ID before publishing")
    return folder.relative_to(ROOT)


def main():
    parser = argparse.ArgumentParser(description="Validate PrusaSlicer plugin bundles.")
    parser.add_argument("--tag", help="Validate one release and print its bundle path.")
    args = parser.parse_args()
    try:
        if args.tag is not None:
            print(release_bundle(args.tag))
            return
        template = ROOT / "templates" / "project-plugin"
        validate_bundle(template)
        print(f"OK {template.relative_to(ROOT)}")
        ids = set()
        for folder in sorted((ROOT / "plugins").iterdir()):
            if folder.name == ".gitkeep":
                continue
            if not FOLDER.fullmatch(folder.name):
                raise ValueError(f"{folder.relative_to(ROOT)} needs a lowercase folder name")
            fields = validate_bundle(folder)
            if fields["id"] in ids:
                raise ValueError(f"duplicate plugin ID {fields['id']}")
            ids.add(fields["id"])
            print(f"OK {folder.relative_to(ROOT)}")
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
