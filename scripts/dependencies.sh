#!/bin/sh
set -eu
. /etc/os-release
case "$ID ${ID_LIKE:-}" in
  ubuntu*|pop*)
    apt-get update
    exec apt-get install -y build-essential rustc cargo git python3 curl ca-certificates clang libclang-dev cmake pkg-config libfontconfig-dev libfreetype-dev libxkbcommon-dev libxkbcommon-x11-dev libwayland-dev libinput-dev libseat-dev libdisplay-info-dev libei-dev libgbm-dev libegl1-mesa-dev libdrm-dev libpixman-1-dev libudev-dev libsystemd-dev libdbus-1-dev libpulse-dev libdav1d-dev libssl-dev libxcb1-dev libx11-dev
    ;;
  fedora*)
    exec dnf install rust cargo git python3 curl gcc gcc-c++ clang clang-devel cmake pkgconf-pkg-config fontconfig-devel freetype-devel libxkbcommon-devel wayland-devel libinput-devel libseat-devel libdisplay-info-devel libei-devel mesa-libgbm-devel mesa-libEGL-devel libdrm-devel pixman-devel systemd-devel dbus-devel pulseaudio-libs-devel libdav1d-devel openssl-devel libxcb-devel libX11-devel
    ;;
  arch*|*" arch"*)
    exec pacman -S --needed base-devel rust git python curl clang cmake pkgconf fontconfig freetype2 libxkbcommon wayland libinput seatd libdisplay-info mesa libdrm pixman libei libxcb libx11 systemd-libs dbus libpulse dav1d openssl
    ;;
  *) printf '%s\n' 'Supported build systems: Arch, Fedora, Ubuntu and Pop!_OS.' >&2; exit 1 ;;
esac
