"""Publish reviewed preview assets only; never copy projects, config or registry.

Destination must be the catalog styles directory under this install. Each file
is validated before any write; existing app sample files are backed up first.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).parent))
from check_style_samples import inspect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--install', type=Path, required=True)
    args = parser.parse_args()
    ffprobe = shutil.which('ffprobe') or str(args.install / 'runtime/bin/ffprobe.exe')
    measured = inspect(args.source, ffprobe)
    if not measured['ok']:
        print(json.dumps(measured, ensure_ascii=False, indent=2))
        return 1
    target = args.install.resolve() / 'remotion-composer/public/styles'
    backup_root = Path(__file__).resolve().parents[2] / '.tmp'
    backup = Path(tempfile.mkdtemp(prefix='style-catalog-before-', dir=backup_root))
    target.mkdir(parents=True, exist_ok=True)
    for row in measured['samples']:
        for suffix in ('.mp4', '.png'):
            name = row['id'] + suffix
            old = target / name
            if old.is_file():
                shutil.copy2(old, backup / name)
            source = args.source / name
            staged = target / (name + '.new')
            shutil.copy2(source, staged)
            staged.replace(old)
    receipt = {'kind': 'authored-style-demonstrations', 'duration': 5,
               'resolution': [720, 1280], 'fps': 30, 'samples': measured['samples']}
    manifest = target / 'samples.json'
    if manifest.exists():
        shutil.copy2(manifest, backup / manifest.name)
    manifest.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'ok': True, 'count': len(measured['samples']), 'catalog': str(target), 'backup': str(backup)}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
