#!/usr/bin/env python3
"""Build a complete source release with its vendored Rust dependencies."""
import argparse
import json
from pathlib import Path

import build

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--jobs', type=int, default=4)
args = parser.parse_args()
if args.jobs < 1:
    parser.error('--jobs must be positive')
record = ROOT / 'source-bundle.json'
if not record.exists():
    parser.error('Extract a complete source archive from GitHub Releases first')
version = json.loads(record.read_text())['cosmic_version']
sources = {kind: ROOT / 'sources' / kind for kind in ('comp', 'settings')}
for kind, directory in sources.items():
    config = (ROOT / 'vendor' / (kind + '.toml')).read_text()
    config = config.replace('@VENDOR@', str(ROOT / 'vendor' / kind))
    (directory / '.cargo').mkdir(exist_ok=True)
    (directory / '.cargo/config.toml').write_text(config)
build.compile_sources(sources, ROOT / 'build', version, args.jobs, offline=True)
print('Build ready. Run ./install.sh --build-dir ./build')
