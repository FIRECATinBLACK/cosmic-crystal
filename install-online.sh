#!/bin/sh
set -eu
CRYSTAL_TAG=v0.8.0
CRYSTAL_TEMP=$(mktemp -d -t cosmic-crystal.XXXXXXXX)
trap 'rm -rf "$CRYSTAL_TEMP"' EXIT HUP INT TERM
curl -fL --retry 3 "https://github.com/motixo/cosmic-crystal/archive/refs/tags/$CRYSTAL_TAG.tar.gz" -o "$CRYSTAL_TEMP/installer.tar.gz"
tar -xzf "$CRYSTAL_TEMP/installer.tar.gz" -C "$CRYSTAL_TEMP"
if [ "${1:-}" = "--uninstall" ]; then
    shift
    "$CRYSTAL_TEMP/cosmic-crystal-${CRYSTAL_TAG#v}/uninstall.sh" "$@"
else
    "$CRYSTAL_TEMP/cosmic-crystal-${CRYSTAL_TAG#v}/install.sh" "$@"
fi
