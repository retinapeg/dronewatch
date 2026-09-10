#!/usr/bin/env python3
"""Render labelled 2D Viso inputs from the existing demo's sensor observations.

The symbols are synthetic test artwork, not ground-truth classifications.
Only pipeline_input observations are read. No outputs are sent to the tracker.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dronewatch.synthetic.generator import (
    FaultSpec, T_ZERO, VISO_FOV_CENTRE_DEG, VISO_FOV_HALF_DEG,
    VISO_MAX_RANGE_M, VISO_SENSOR_LOCATION, pipeline_input,
)
from dronewatch.tracks.cueing import plan_camera_cues
from dronewatch.tracks.frames import build_timeline
from dronewatch.tracks.site import MonitoredSite
from dronewatch.tracks.tracker import TrackerConfig

WIDTH, HEIGHT, FPS, DURATION = 960, 540, 15, 8
BOUNDS = (-1600.0, 1600.0, 0.0, 2200.0)
RECT = (70, 68, 890, 480)


def font(size):
    for path in ['/System/Library/Fonts/Monaco.ttf',
                 '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf']:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def pixel(x, y):
    xmin, xmax, ymin, ymax = BOUNDS
    left, top, right, bottom = RECT
    return (left + (x - xmin) / (xmax - xmin) * (right - left),
            bottom - (y - ymin) / (ymax - ymin) * (bottom - top))


def existing_inputs(cues=None):
    """Mirror preview.get_tracks' two-pass cued-camera construction exactly."""
    faults = FaultSpec.parse('radar:40-70;backup:viso')
    if cues is None:
        obs, scans = pipeline_input('operator_demo', seed=42, count=6,
                                    duration_s=90, faults=replace(faults, backup=None))
        radar = build_timeline(obs, t_zero=T_ZERO, duration_s=90,
                               site=MonitoredSite(), scans=scans,
                               admit=['radar-north'], config=TrackerConfig(drop_after_s=45))
        cues = plan_camera_cues(radar['frames'], VISO_SENSOR_LOCATION,
                                rest_deg=VISO_FOV_CENTRE_DEG)
    faults = replace(faults, viso_cues=tuple((c['t'], c['centre_deg']) for c in cues))
    obs, _ = pipeline_input('operator_demo', seed=42, count=6,
                            duration_s=90, faults=faults)
    # Deduplicate transport retries; a duplicated report is one camera symbol.
    seen = set()
    scans = {}
    for observation in obs:
        if observation.sensor_id != 'viso-eo' or observation.position is None:
            continue
        if observation.observation_id in seen:
            continue
        seen.add(observation.observation_id)
        t = round((observation.observed_at - T_ZERO).total_seconds())
        scans.setdefault(t, []).append((observation.position.latitude,
                                        observation.position.longitude))
    # Associate artwork between observed frames by nearest previous location.
    # This is a presentation key only, with no use of entity IDs or true classes.
    artwork = {}
    next_key = 0
    for t in sorted(scans):
        used = set()
        styled = []
        for x, y in sorted(scans[t]):
            candidates = [(math.hypot(x - previous[0], y - previous[1]), key)
                          for key, previous in artwork.items()
                          if key not in used and t - previous[2] <= 20]
            distance, key = min(candidates, default=(1e9, -1))
            if distance > 350:
                key, next_key = next_key, next_key + 1
            used.add(key)
            artwork[key] = (x, y, t)
            styled.append((x, y, 'DRONE' if key % 2 == 0 else 'MISSILE'))
        scans[t] = styled
    return scans, cues


def quadcopter(draw, x, y, color):
    for dx in [-11, 11]:
        for dy in [-9, 9]:
            draw.line((x, y, x + dx, y + dy), fill=color, width=3)
            draw.ellipse((x + dx - 6, y + dy - 6, x + dx + 6, y + dy + 6),
                         fill=(15, 30, 40), outline=color, width=2)
    draw.rounded_rectangle((x - 5, y - 8, x + 5, y + 8), radius=3, fill=color)


def missile(draw, x, y, color):
    draw.polygon([(x, y - 19), (x + 5, y - 8), (x + 5, y + 11),
                  (x + 12, y + 17), (x + 3, y + 14), (x, y + 18),
                  (x - 3, y + 14), (x - 12, y + 17), (x - 5, y + 11),
                  (x - 5, y - 8)], fill=color)


def render(scans, cues, sim_time):
    image = Image.new('RGB', (WIDTH, HEIGHT), (12, 22, 32))
    draw = ImageDraw.Draw(image, 'RGBA')
    left, top, right, bottom = RECT
    draw.rectangle(RECT, fill=(16, 29, 40), outline=(52, 72, 84), width=1)
    for x in range(-1600, 1601, 400):
        px, _ = pixel(x, 0)
        draw.line((px, top, px, bottom), fill=(41, 59, 70), width=1)
        draw.text((px - 20, bottom + 5), str(x), font=font(10), fill=(135, 155, 168))
    for y in range(0, 2201, 400):
        _, py = pixel(0, y)
        draw.line((left, py, right, py), fill=(41, 59, 70), width=1)
        draw.text((left - 37, py - 5), str(y), font=font(10), fill=(135, 155, 168))

    # Same known camera calibration and tracker-produced pointing schedule.
    cue = next((c for c in reversed(cues) if c['t'] <= sim_time), cues[0])
    cx, cy = VISO_SENSOR_LOCATION
    points = [pixel(cx, cy)]
    for i in range(33):
        angle = math.radians(cue['centre_deg'] - VISO_FOV_HALF_DEG + 2 * VISO_FOV_HALF_DEG * i / 32)
        points.append(pixel(cx + VISO_MAX_RANGE_M * math.cos(angle),
                            cy + VISO_MAX_RANGE_M * math.sin(angle)))
    layer = Image.new('RGBA', image.size)
    layer_draw = ImageDraw.Draw(layer)
    layer_draw.polygon(points, fill=(69, 118, 128, 36))
    layer_draw.line(points + [points[0]], fill=(75, 120, 133, 135), width=1)
    # Clip the sector to the plotting area.
    image.paste(Image.alpha_composite(image.convert('RGBA'), layer).crop(RECT), (left, top))
    draw = ImageDraw.Draw(image, 'RGBA')
    camera_x, camera_y = pixel(cx, cy)
    draw.rectangle((camera_x - 5, camera_y - 4, camera_x + 5, camera_y + 4),
                   fill=(153, 186, 194))
    draw.text((camera_x + 11, camera_y - 7), 'VISION', font=font(12), fill=(168, 195, 204))

    for x, y, label in scans.get(int(sim_time), []):
        px, py = pixel(x, y)
        if not left + 20 <= px <= right - 20 or not top + 22 <= py <= bottom - 22:
            continue
        color = (123, 224, 218) if label == 'DRONE' else (248, 192, 108)
        (quadcopter if label == 'DRONE' else missile)(draw, px, py, color)
        width = draw.textlength(label, font=font(14))
        draw.rectangle((px - width / 2 - 5, py + 23, px + width / 2 + 5, py + 44),
                       fill=(12, 22, 32, 236))
        draw.text((px - width / 2, py + 25), label, font=font(14), fill=color)

    draw.text((24, 17), 'SYNTHETIC 2D SENSOR INPUT', font=font(19), fill=(222, 235, 239))
    draw.text((675, 20), f'SIM {sim_time:05.1f}s', font=font(17), fill=(197, 216, 224))
    draw.text((24, 514), 'RADAR OFF 40-70s  |  VISION FOV  |  LABELLED TEST SYMBOLS  |  LOCAL x/y (m)',
              font=font(12), fill=(163, 185, 198))
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--clip-id', default='schematic-02')
    parser.add_argument('--stills-only', action='store_true')
    parser.add_argument('--cues-json', type=Path,
                        help='Saved preview/tracks JSON or list of camera cues for exact replay alignment.')
    parser.add_argument('--ffmpeg', default=shutil.which('ffmpeg') or '/opt/homebrew/bin/ffmpeg')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    supplied_cues = None
    if args.cues_json:
        source = json.loads(args.cues_json.read_text())
        supplied_cues = source if isinstance(source, list) else source['sensors'][0]['cues']
    scans, cues = existing_inputs(supplied_cues)
    # Preserve only calibration, never track targets/reasons, so subsequent
    # offline renders use exactly the current demo's pointing schedule.
    (args.output / 'schematic-cues.json').write_text(json.dumps([
        {'t': c['t'], 'centre_deg': c['centre_deg']} for c in cues], indent=2) + '\n')
    if not args.clip_id.startswith('schematic-') or not args.clip_id.removeprefix('schematic-').isdigit():
        parser.error('--clip-id must be schematic- followed by digits')
    render(scans, cues, 58).save(args.output / f'{args.clip_id}.png')
    print(f'Ready {args.clip_id}.png at sim t=58', flush=True)
    if args.stills_only:
        return
    video = args.output / f'{args.clip_id}.mp4'
    process = subprocess.Popen([args.ffmpeg, '-hide_banner', '-loglevel', 'error', '-y',
                                '-f', 'rawvideo', '-vcodec', 'rawvideo', '-pix_fmt', 'rgb24',
                                '-s', f'{WIDTH}x{HEIGHT}', '-r', str(FPS), '-i', '-', '-an',
                                '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
                                '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(video)],
                               stdin=subprocess.PIPE)
    try:
        for frame_number in range(DURATION * FPS):
            sim_time = 40 + frame_number / (DURATION * FPS - 1) * 30
            process.stdin.write(render(scans, cues, sim_time).tobytes())
        process.stdin.close()
        if process.wait() != 0:
            raise RuntimeError('ffmpeg schematic rendering failed')
    except BaseException:
        process.kill()
        process.wait()
        raise
    path = args.output / 'manifest.json'
    manifest = json.loads(path.read_text()) if path.exists() else {
        'schema_version': 1, 'source': 'synthetic_sensor_renderer', 'synthetic': True, 'clips': []}
    item = {'clip_id': args.clip_id, 'file': video.name, 'still': f'{args.clip_id}.png',
            'duration_seconds': DURATION, 'fps': FPS, 'width': WIDTH, 'height': HEIGHT,
            'synthetic': True, 'scenario': 'operator_demo', 'seed': 42, 'count': 6,
            'mode': 'radar_off_30s_viso', 'sim_start_s': 40, 'sim_end_s': 70,
            'still_sim_time_s': 58, 'frame': 'LOCAL_SIM_METRES',
            't_zero': T_ZERO.isoformat(),
            'world_bounds': list(BOUNDS), 'pixel_rect': list(RECT)}
    manifest['clips'] = [item] + [c for c in manifest['clips'] if c['clip_id'] != item['clip_id']]
    path.write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'Ready {args.clip_id}.mp4 and manifest', flush=True)


if __name__ == '__main__':
    main()
