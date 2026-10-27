# COSMIC Crystal

A crystal glass effect for **COSMIC 1.10.0 and 1.11.0**, on **Arch Linux, Fedora, Ubuntu and Pop!_OS**.

Faceted light refraction, adjustable frost, thickness and density. Optional **reactive highlights** sample the real desktop behind each face, so restrained rim glints respond to local brightness, contrast, gradients and color. **Everyday mode** keeps reading areas calm and concentrates the effect near window edges. Works wherever COSMIC enables Frosted Glass.

![COSMIC Crystal](assets/screenshot.png)

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/motixo/cosmic-crystal/v0.8.0/install-online.sh | sh
```

Run as your desktop user, **without sudo**, then log out and back in. Open **Settings → Desktop → Appearance → COSMIC Crystal**.

Requires matching native `cosmic-comp` and `cosmic-settings` packages, `curl`, `tar`, and Python 3. Prebuilt downloads target x86_64, with glibc **2.44+ on Arch** or **2.42+ on Fedora**, or **2.39+ on Ubuntu/Pop!_OS (24.04+)**. The installer selects the matching archive, checks SHA-256, and saves previous launchers for removal. Keep `~/.local/bin` before `/usr/bin` in your login PATH.

## Build — Arch, Fedora, Ubuntu and Pop!_OS

```sh
git clone https://github.com/motixo/cosmic-crystal.git
cd cosmic-crystal
sudo sh scripts/dependencies.sh
./build-from-source.sh --jobs 4
```

The dependency script uses `pacman`, `dnf`, or `apt` for your distribution. Build and installation run as your normal user. Requires Rust 1.93+; sources are pinned to the installed COSMIC version.

On Ubuntu/Pop!_OS, install a newer Rust toolchain if `rustc --version` is below 1.93:

```sh
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
. "$HOME/.cargo/env"
```

Build without installing:

```sh
./build-from-source.sh --build-only --jobs 4
./install.sh --build-dir ./build
```

Use `--cosmic-version 1.11.0 --build-only` to build another supported version. Complete source archives, including Rust dependencies and an offline build script, are in [Releases](https://github.com/motixo/cosmic-crystal/releases).

## Reactive facet highlights

In **Settings → Desktop → Appearance → COSMIC Crystal**, enable **Reactive highlights**, choose a visual strength, and adjust **Reactive highlight intensity**. **Vivid** is the default. **Subtle** approximates the original restrained effect, while **Extreme** deliberately exaggerates gloss, refraction, curvature, color pickup, and internal depth. Setting highlight intensity to 0% or disabling the toggle removes backdrop-driven glints while leaving the selected preset's physical refraction and surface profile active. Everyday mode further reduces the effect in broad reading areas.

The implementation reuses Crystal's captured backdrop and performs five local samples oriented to each procedural facet. Presets change the lens curvature, optical depth, refraction reach, droplet-rim profile, response curve, color influence, specular concentration, and internal transmission—not final opacity alone. It does not use a timer, temporal history, or a full-screen analysis pass. Backdrop damage expands with the preset's scaled sampling radius so highlights update when content behind stationary glass changes. A sharp backdrop copy is retained while reactive highlights are enabled on frosted surfaces, adding one regional texture copy and the same five analysis fetches per affected fragment for every preset.

### Visual comparison protocol

1. Keep frost, thickness, refraction, density, highlight intensity, window size, and Everyday mode fixed.
2. Capture **Subtle**, **Vivid**, and **Extreme** over a dark uniform backdrop, a bright neutral backdrop, and a colorful high-contrast backdrop.
3. On the colorful backdrop, move the window by roughly one facet width or shift the backdrop pattern while the window remains stationary. Compare rim position, localized distortion, highlight color, and per-face motion.
4. Confirm dark uniform areas remain calm, bright areas retain gradation rather than turning into solid white, and opaque text/controls remain pixel-identical.
5. For repeatable nested-compositor captures, run `tests/verify_reactive_highlights.py` after starting `scripts/preview.py`; it writes named comparison PNGs and measurements to the configured QA directories.

To compare directly with the earlier implementation, select **Subtle** and keep the original 45% highlight intensity. The implementation uses spatial filtering but deliberately omits temporal accumulation to avoid ghosting, history textures, and continuous compositor redraws. Very small or fast backdrop changes therefore follow compositor damage immediately rather than easing across frames.

## Uninstall

```sh
curl -fsSL https://raw.githubusercontent.com/motixo/cosmic-crystal/v0.8.0/install-online.sh | sh -s -- --uninstall
```

Log out and back in. Previous launchers and unchanged preferences are restored.

GPL-3.0-only. Independent project; COSMIC is developed by System76 and its contributors.
