#!/usr/bin/env python3
"""Verify backdrop-reactive facet highlights in the isolated compositor."""
import json
import os
from pathlib import Path
import time

from PIL import Image, ImageChops, ImageGrab, ImageStat

ROOT = Path(__file__).resolve().parents[1]
RUN = Path(os.environ['CRYSTAL_QA_DIR'])
ASSETS = Path(os.environ.get('CRYSTAL_QA_ASSETS_DIR', ROOT / 'assets'))
REPORTS = Path(os.environ.get('CRYSTAL_QA_REPORT_DIR', ROOT / 'logs'))
STATE = json.loads((RUN / 'state.json').read_text())
CONFIG = RUN / 'config/cosmic/com.system76.CosmicComp/v1'
BACKGROUND = RUN / 'config/cosmic/com.system76.CosmicBackground/v1/all'
KEYS = ['crystal_enabled', 'crystal_everyday', 'crystal_blur_amount',
        'crystal_refraction', 'crystal_density', 'crystal_thickness',
        'crystal_reactive_highlights', 'crystal_reactive_intensity',
        'crystal_visual_strength']
saved = {key: (CONFIG / key).read_bytes() if (CONFIG / key).exists() else None
         for key in KEYS}
old_background = BACKGROUND.read_bytes()
results = []
measurements = {}
ASSETS.mkdir(parents=True, exist_ok=True)
REPORTS.mkdir(parents=True, exist_ok=True)


def setting(key, value):
    (CONFIG / key).write_text(str(value).lower() + '\n')
    time.sleep(0.6)


def capture(name):
    image = ImageGrab.grab(xdisplay=STATE['display']).convert('RGB')
    image.save(ASSETS / (name + '.png'))
    return image


def difference(a, b, box):
    return sum(ImageStat.Stat(ImageChops.difference(a.crop(box), b.crop(box))).mean) / 3


def origin(image):
    points = [(x, y) for y in range(image.height) for x in range(image.width)
              if image.getpixel((x, y)) == (11, 14, 20)]
    assert points, 'Test surface title bar not found'
    return min(x for x, _ in points), min(y for _, y in points)


def wallpaper(name, kind, shift=0):
    base = (18, 20, 24) if kind != 'bright' else (238, 242, 248)
    image = Image.new('RGB', (1280, 900), base)
    if kind == 'colorful':
        pixels = image.load()
        for y in range(image.height):
            for x in range(image.width):
                band = (((x + shift) // 36) + ((y + shift // 2) // 48)) % 3
                pixels[x, y] = ((235, 92, 55), (35, 195, 180), (62, 70, 210))[band]
    path = RUN / (name + '.png')
    image.save(path)
    BACKGROUND.write_text('(output: "all", source: Path(' + json.dumps(str(path)) +
        '), filter_by_theme: false, rotation_frequency: 300, filter_method: Lanczos, scaling_mode: Zoom, sampling_method: Alphanumeric)\n')
    time.sleep(0.8)


def check(name, condition):
    results.append({'test': name, 'passed': bool(condition)})
    if not condition:
        raise AssertionError(name)


def clipped_fraction(image, box):
    pixels = image.crop(box).getdata()
    return sum(min(pixel) >= 252 for pixel in pixels) / len(pixels)


try:
    setting('crystal_enabled', True)
    setting('crystal_everyday', False)
    setting('crystal_blur_amount', 35)
    setting('crystal_refraction', 150)
    setting('crystal_density', 100)
    setting('crystal_thickness', 40)
    wallpaper('reactive-colorful', 'colorful')
    setting('crystal_visual_strength', 0)
    setting('crystal_reactive_highlights', False)
    disabled = capture('reactive-disabled')
    left, top = origin(disabled)
    body = (left + 150, top + 180, left + 720, top + 450)
    header = (left + 20, top + 8, left + 800, top + 80)

    setting('crystal_reactive_highlights', True)
    setting('crystal_reactive_intensity', 45)
    subtle = capture('reactive-strength-subtle')
    measurements['subtle_reactive_difference'] = difference(disabled, subtle, body)
    check('Reactive highlights alter patterned backdrop facets',
          measurements['subtle_reactive_difference'] > 0.03)
    check('Reactive highlights leave opaque foreground pixels unchanged',
          difference(disabled, subtle, header) == 0)
    check('Reactive highlights are stable without backdrop damage',
          difference(subtle, capture('reactive-stable'), body) < 0.05)

    setting('crystal_visual_strength', 1)
    vivid = capture('reactive-strength-vivid')
    setting('crystal_visual_strength', 2)
    extreme = capture('reactive-strength-extreme')
    setting('crystal_visual_strength', 255)
    check('Visual strength is bounded at Extreme',
          difference(extreme, capture('reactive-strength-clamped'), body) < 0.05)
    measurements['subtle_to_vivid_difference'] = difference(subtle, vivid, body)
    measurements['vivid_to_extreme_difference'] = difference(vivid, extreme, body)
    check('Vivid changes actual optics from Subtle',
          measurements['subtle_to_vivid_difference'] > 0.10)
    check('Extreme changes actual optics beyond Vivid',
          measurements['vivid_to_extreme_difference'] > 0.10)
    check('Vivid preserves opaque foreground pixels', difference(subtle, vivid, header) == 0)

    setting('crystal_reactive_intensity', 0)
    zero = capture('reactive-zero')
    setting('crystal_reactive_intensity', 100)
    maximum = capture('reactive-maximum')
    check('Reactive intensity changes live rendering', difference(zero, maximum, body) > 0.05)
    setting('crystal_reactive_intensity', 255)
    check('Reactive intensity is bounded at 100 percent',
          difference(maximum, capture('reactive-clamped'), body) < 0.05)

    setting('crystal_visual_strength', 1)
    wallpaper('reactive-flat-dark', 'dark')
    setting('crystal_reactive_intensity', 45)
    flat_enabled = capture('reactive-flat-enabled')
    setting('crystal_reactive_highlights', False)
    flat_disabled = capture('reactive-flat-disabled')
    measurements['flat_dark_difference'] = difference(flat_enabled, flat_disabled, body)
    check('Dark uniform backdrops keep reactive highlights subtle',
          measurements['flat_dark_difference'] < measurements['subtle_reactive_difference'])

    wallpaper('reactive-flat-bright', 'bright')
    setting('crystal_reactive_highlights', True)
    bright = capture('reactive-backdrop-bright')
    measurements['bright_clipped_fraction'] = clipped_fraction(bright, body)
    check('Bright backdrop retains highlight detail instead of clipping broadly',
          measurements['bright_clipped_fraction'] < 0.20)

    wallpaper('reactive-motion-a', 'colorful', 0)
    movement_a = capture('reactive-motion-a')
    wallpaper('reactive-motion-b', 'colorful', 29)
    movement_b = capture('reactive-motion-b')
    check('Stationary glass responds after backdrop content changes',
          difference(movement_a, movement_b, body) > 3.0)

    (REPORTS / 'reactive-highlight-results.json').write_text(
        json.dumps({'checks': results, 'measurements': measurements}, indent=2) + '\n')
    print(json.dumps({'checks': results, 'measurements': measurements}, indent=2))
finally:
    BACKGROUND.write_bytes(old_background)
    for key, content in saved.items():
        if content is None:
            (CONFIG / key).unlink(missing_ok=True)
        else:
            (CONFIG / key).write_bytes(content)
    time.sleep(0.8)
