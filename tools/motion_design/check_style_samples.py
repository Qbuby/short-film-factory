"""Measure finished style clips; optional exact catalog completeness.

No optical/creative quality claim: this is only the technical delivery gate.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def inspect(directory: Path, ffprobe: str) -> dict:
    catalog = json.loads((Path(__file__).parent / 'film_styles.json').read_text(encoding='utf-8'))
    rows, failures = [], []
    for item in catalog['styles']:
        sid = item['id']
        video, poster = directory / f'{sid}.mp4', directory / f'{sid}.png'
        if not video.is_file() or not poster.is_file():
            failures.append(f'{sid}: missing video or poster')
            continue
        result = subprocess.run([ffprobe, '-v', 'error', '-count_frames',
            '-show_entries', 'stream=codec_type,codec_name,width,height,r_frame_rate,nb_read_frames,pix_fmt:format=duration',
            '-of', 'json', str(video)], check=True, capture_output=True)
        data = json.loads(result.stdout.decode('utf-8', errors='replace'))
        streams = data['streams']
        visuals = [s for s in streams if s['codec_type'] == 'video']
        audio = [s for s in streams if s['codec_type'] == 'audio']
        v = visuals[0] if len(visuals) == 1 else {}
        seconds = float(data['format']['duration'])
        # Remotion may emit full-range (yuvj420p) or limited-range (yuv420p) 4:2:0;
        # both play in Chromium, so accept the 4:2:0 family either way.
        pix_fmt = str(v.get('pix_fmt') or '').replace('j', '')
        four_two = ''.join(chr(c) for c in (0x79, 0x75, 0x76, 0x34, 0x32, 0x30, 0x70))
        checks = {
            'one_video_no_audio': len(visuals) == 1 and not audio,
            'five_seconds': abs(seconds - 5) < 0.001,
            '150_frames': v.get('nb_read_frames') == '150',
            '30fps': v.get('r_frame_rate') == '30/1',
            '720x1280': (v.get('width'), v.get('height')) == (720, 1280),
            'browser_codec': v.get('codec_name') == 'h264' and pix_fmt == four_two,
        }
        failed = [name for name, ok in checks.items() if not ok]
        if failed:
            failures.append(f"{sid}: {', '.join(failed)}")
        rows.append({'id': sid, 'duration': seconds, 'checks': checks,
            'bytes': video.stat().st_size, 'sha256': hashlib.sha256(video.read_bytes()).hexdigest()})
    return {'ok': not failures and len(rows) == len(catalog['styles']), 'count': len(rows),
            'expected': len(catalog['styles']), 'failures': failures, 'samples': rows}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory', type=Path)
    p.add_argument('--ffprobe', default=shutil.which('ffprobe') or 'ffprobe')
    p.add_argument('--report', type=Path)
    args = p.parse_args()
    result = inspect(args.directory, args.ffprobe)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.report:
        if args.report.exists():
            raise FileExistsError('Report already exists; select a new path')
        args.report.write_text(text + '\n', encoding='utf-8')
    print(text)
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
