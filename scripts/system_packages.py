"""Native package queries used by builds, installers and upgrade guards."""
import platform
import json
from pathlib import Path
import re
import subprocess

SUPPORTED = ("1.10.0", "1.11.0")


def distribution():
    release = platform.freedesktop_os_release()
    distro = release.get("ID", "")
    if distro == "fedora":
        return "fedora"
    if distro in ('ubuntu', 'pop'):
        return 'ubuntu'
    if distro == "arch" or "arch" in release.get("ID_LIKE", "").split():
        return "arch"
    raise RuntimeError("COSMIC Crystal supports Arch, Fedora, Ubuntu and Pop!_OS")


def manager(distro=None):
    return {"arch": "pacman", "fedora": "rpm", "ubuntu": "dpkg"}[distro or distribution()]


def query_command(name, backend):
    if backend == "pacman":
        return ["pacman", "-Q", name]
    if backend == "rpm":
        return ["rpm", "-q", "--qf", "%{NAME} %{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\\n", name]
    if backend == 'dpkg':
        return ['dpkg-query', '-W', '-f', '${binary:Package} ${Version}\\n', name]
    raise ValueError("Unknown package backend: " + backend)


def query(name, backend=None):
    result = subprocess.run(query_command(name, backend or manager()), capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"Install the native {name} package first")
    value = result.stdout.strip()
    upstream_version(name, value)
    return value


def upstream_version(name, package):
    # System76's compositor packages use 0.1~TIMESTAMP~24.04~COMMIT rather
    # than the epoch version. Match the upstream commit recorded in the .deb.
    if name == 'cosmic-comp':
        pins = json.loads((Path(__file__).resolve().parents[1] / 'release.json').read_text())['source_versions']
        for version, commits in pins.items():
            if re.search(r'~' + re.escape(commits['comp'][:7]) + r'(?:$|[-+])', package):
                return version
    match = re.fullmatch(re.escape(name) + r" (?:[0-9]+:)?([0-9]+\.[0-9]+\.[0-9]+)(?:[-~+][^\s]+)?", package)
    if not match:
        raise RuntimeError("Unsupported package version: " + package)
    return match[1]


def installed_version(backend=None):
    versions = {upstream_version(name, query(name, backend)) for name in ("cosmic-settings", "cosmic-comp")}
    if len(versions) != 1 or next(iter(versions)) not in SUPPORTED:
        raise RuntimeError("Install matching COSMIC Settings and compositor packages at 1.10.0 or 1.11.0")
    return versions.pop()
