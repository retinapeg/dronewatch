#!/usr/bin/env python3
"""Render repeatable synthetic camera inputs, never synthetic inference results.

Requires Python 3, Pillow, NumPy and ffmpeg. Assets are generated locally; no
models, remote assets, class labels or bounding boxes are included in the media.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import shutil
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

WIDTH, HEIGHT = 960, 540
FPS, DURATION = 15, 8
CAMERA = np.array([0.0, -16.0, 4.2])
FORWARD = np.array([0.0, 36.0, 2.8])
FORWARD /= np.linalg.norm(FORWARD)
RIGHT = np.array([1.0, 0.0, 0.0])
UP = np.cross(RIGHT, FORWARD)
FOCAL = 800.0
SUN = np.array([-0.5, -0.65, 1.0])
SUN /= np.linalg.norm(SUN)


def project(points):
    points = np.asarray(points, dtype=float) - CAMERA
    depth = points @ FORWARD
    x = WIDTH / 2 + FOCAL * (points @ RIGHT) / depth
    y = HEIGHT / 2 - FOCAL * (points @ UP) / depth
    return np.column_stack((x, y)), depth


def box(center, size, color):
    center, size = np.array(center), np.array(size) / 2
    vertices = np.array([(x, y, z) for x in [-1, 1]
                         for y in [-1, 1] for z in [-1, 1]]) * size + center
    return [(vertices[list(indices)], color) for indices in
            [(0, 4, 6, 2), (1, 3, 7, 5), (0, 1, 5, 4),
             (2, 6, 7, 3), (0, 2, 3, 1), (4, 5, 7, 6)]]


def cylinder(center, radius, height, color, segments=16):
    cx, cy, cz = center
    ring = [(cx + radius * math.cos(i * math.tau / segments),
             cy + radius * math.sin(i * math.tau / segments))
            for i in range(segments)]
    lower = np.array([(x, y, cz - height / 2) for x, y in ring])
    upper = np.array([(x, y, cz + height / 2) for x, y in ring])
    faces = [(upper, color), (lower[::-1], color)]
    for i in range(segments):
        j = (i + 1) % segments
        faces.append((np.array([lower[i], lower[j], upper[j], upper[i]]), color))
    return faces


def ellipsoid(center, radii, color):
    faces = []
    center, radii = np.array(center), np.array(radii)
    rings, segs = 8, 20
    for j in range(rings):
        for i in range(segs):
            points = []
            for a, b in [(j, i), (j, i + 1), (j + 1, i + 1), (j + 1, i)]:
                lat, lon = math.pi * a / rings, math.tau * b / segs
                points.append(center + radii * np.array([
                    math.sin(lat) * math.cos(lon), math.sin(lat) * math.sin(lon),
                    math.cos(lat)]))
            faces.append((np.array(points), color))
    return faces


def beam(a, b, width, height, color):
    a, b = np.array(a), np.array(b)
    angle = math.atan2(b[1] - a[1], b[0] - a[0])
    c, s = math.cos(angle), math.sin(angle)
    rot = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
    return [(vertices @ rot.T + (a + b) / 2, shade)
            for vertices, shade in box((0, 0, 0),
                                       (np.linalg.norm(b - a), width, height), color)]


def paint_faces(image, faces):
    draw = ImageDraw.Draw(image, 'RGBA')
    projected = []
    for vertices, color in faces:
        coords, depth = project(vertices)
        if depth.min() < 0.5:
            continue
        normal = np.cross(vertices[1] - vertices[0], vertices[2] - vertices[0])
        norm = np.linalg.norm(normal)
        light = 0.65 + 0.35 * max(0, np.dot(normal / max(norm, 1e-9), SUN))
        alpha = color[3] if len(color) == 4 else 255
        shade = tuple(int(min(255, v * light)) for v in color[:3]) + (alpha,)
        projected.append((float(depth.mean()), coords, shade))
    for _, coords, color in sorted(projected, key=lambda f: f[0], reverse=True):
        draw.polygon([tuple(v) for v in coords], fill=color)


def ground_poly(image, points, fill):
    coords, _ = project(points)
    ImageDraw.Draw(image, 'RGBA').polygon([tuple(p) for p in coords], fill=fill)


def world_line(image, points, fill, width=1):
    coords, _ = project(points)
    ImageDraw.Draw(image, 'RGBA').line([tuple(p) for p in coords], fill=fill, width=width)


def background():
    rng = np.random.default_rng(140921)
    yy = np.arange(HEIGHT)[:, None, None] / HEIGHT
    sky = np.array([131, 172, 199])[None, None, :] * (1 - yy)
    sky = sky + np.array([222, 229, 227])[None, None, :] * yy
    sky = np.repeat(sky, WIDTH, axis=1)
    sky = np.clip(sky + rng.normal(0, 0.6, (HEIGHT, WIDTH, 1)), 0, 255)
    image = Image.fromarray(sky.astype('uint8'))

    clouds = Image.new('RGBA', image.size)
    draw = ImageDraw.Draw(clouds)
    for x, y, radius in [(100, 105, 80), (340, 60, 64), (770, 108, 110)]:
        for _ in range(10):
            dx, dy = rng.normal(0, radius / 2), rng.normal(0, 11)
            draw.ellipse((x + dx - radius, y + dy - 17,
                          x + dx + radius, y + dy + 17), fill=(252, 253, 249, 36))
    image = Image.alpha_composite(image.convert('RGBA'), clouds.filter(ImageFilter.GaussianBlur(13))).convert('RGB')

    # Grass apron, asphalt service lane, runway and distant hangars.
    ground_poly(image, [(-300, -10, 0), (300, -10, 0), (300, 900, 0), (-300, 900, 0)],
                (121, 130, 100, 255))
    ground_poly(image, [(-90, -10, .01), (90, -10, .01), (90, 9, .01), (-90, 9, .01)],
                (115, 119, 116, 255))
    ground_poly(image, [(-100, 30, .01), (100, 30, .01), (100, 54, .01), (-100, 54, .01)],
                (91, 99, 100, 255))
    for x in range(-90, 100, 12):
        ground_poly(image, [(x, 42, .02), (x + 6, 42, .02), (x + 6, 42.45, .02), (x, 42.45, .02)],
                    (211, 212, 194, 255))
    for y in [9.4, 10.1]:
        world_line(image, [(-80, y, .03), (80, y, .03)], (218, 200, 106, 255), 2)
    buildings = []
    for x, y, w, h in [(-42, 93, 32, 8), (12, 100, 30, 7), (48, 108, 26, 9)]:
        buildings += box((x, y, h / 2), (w, 24, h), (190, 193, 184))
        buildings += box((x, y, h + .18), (w + .8, 24.8, .36), (82, 96, 99))
        buildings += box((x, y - 12.02, h * .38), (w * .72, .06, h * .68), (72, 88, 93))
        for xx in np.arange(x - w / 2, x + w / 2, 2):
            buildings += box((xx, y - 12.04, h * .77), (.06, .07, h * .3), (116, 128, 127))
    buildings += box((38, 80, 8), (3, 3, 16), (170, 178, 173))
    buildings += box((38, 80, 16), (6, 6, 2), (73, 99, 110))
    buildings += box((38, 80, 17.2), (7, 7, .45), (65, 78, 83))
    paint_faces(image, buildings)

    # Chain-link perimeter: transparency helps retain the camera scene behind it.
    for x in np.arange(-38, 39, .58):
        world_line(image, [(x, 16, .1), (x + 2.9, 16, 3)], (70, 82, 79, 77))
        world_line(image, [(x, 16, .1), (x - 2.9, 16, 3)], (70, 82, 79, 77))
    for z in [.12, 3.0, 3.35]:
        world_line(image, [(-40, 16, z), (40, 16, z)], (82, 90, 84, 255), 2)
    for x in range(-40, 41, 4):
        world_line(image, [(x, 16, 0), (x, 16, 3.5)], (91, 100, 94, 255), 3)
        world_line(image, [(x, 16, 3.5), (x, 15.7, 3.8)], (91, 100, 94, 255), 2)
    # Foreground road texture is deterministic and does not encode detections.
    draw = ImageDraw.Draw(image, 'RGBA')
    for _ in range(1600):
        x, y = int(rng.integers(0, WIDTH)), int(rng.integers(410, HEIGHT))
        draw.point((x, y), fill=(235, 229, 214, int(rng.integers(10, 36))))
    return image


def drone_mesh():
    faces = []
    # Four arms and motor pods, articulated landing struts, camera gimbal.
    for x in [-1, 1]:
        for y in [-1, 1]:
            pos = (x * .91, y * .78, .02)
            faces += beam((x * .20, y * .19, -.03), pos, .16, .14, (74, 81, 86))
            faces += cylinder(pos, .13, .18, (52, 61, 69))
            faces += cylinder((pos[0], pos[1], .13), .075, .065, (183, 187, 185))
            faces += box((x * .57, y * .42, -.22), (.055, .07, .4), (91, 101, 106))
    for x in [-1, 1]:
        faces += box((x * .57, -.02, -.44), (.07, 1.2, .055), (66, 76, 82))
    faces += ellipsoid((0, 0, .035), (.47, .57, .22), (220, 223, 217))
    faces += ellipsoid((0, -.03, -.12), (.36, .42, .13), (62, 74, 82))
    faces += box((0, .07, .19), (.34, .48, .075), (191, 199, 197))
    faces += box((0, -.34, -.28), (.20, .13, .19), (123, 136, 143))
    faces += ellipsoid((0, -.44, -.36), (.13, .14, .12), (44, 52, 57))
    faces += box((0, -.569, -.36), (.105, .015, .09), (18, 36, 47))
    faces += box((0, -.58, -.35), (.04, .007, .034), (68, 114, 145))
    for x in [-1, 1]:
        faces += box((x * .31, -.32, .07), (.10, .13, .028), (159, 52, 37))
        faces += box((x * .90, -.82, -.035), (.10, .03, .055), (235, 67, 38))
        faces += box((x * .90, .82, -.035), (.10, .03, .055), (52, 172, 108))
    return faces


BASE_DRONE = drone_mesh()


def moving_drone(t, index, variant):
    progress = t / DURATION
    if index == 0:
        position = np.array([-13.4 + 27.0 * progress, 4.5 + 2 * math.sin(t * .45),
                             8.1 + .45 * math.sin(t * .7)])
        yaw, bank, scale = -.3 + .35 * math.sin(t * .35), -.08, 1.22
    else:
        position = np.array([14.5 - 27.8 * progress, 12 + 1.5 * math.sin(t * .5),
                             9.8 + .35 * math.cos(t * .7)])
        yaw, bank, scale = .45 + .25 * math.sin(t * .6), .09, 1.15
    c, s = math.cos(yaw), math.sin(yaw)
    yaw_rot = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
    c, s = math.cos(bank), math.sin(bank)
    bank_rot = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    rotation = yaw_rot @ bank_rot
    faces = [(vertices * scale @ rotation.T + position, color)
             for vertices, color in BASE_DRONE]
    # Semi-transparent rotor disks plus a faint blurred blade pair. These are
    # geometry, never a detector overlay; rotation varies with the frame.
    for x in [-1, 1]:
        for y in [-1, 1]:
            center = np.array([x * .91, y * .78, .18])
            ring = np.array([center + np.array([.61 * math.cos(a), .61 * math.sin(a), 0])
                             for a in np.linspace(0, math.tau, 32, endpoint=False)])
            faces.append((ring * scale @ rotation.T + position, (83, 96, 101, 37)))
            for delta in [0, .15, .3]:
                angle = t * 88 + x + y + delta
                direction = np.array([math.cos(angle), math.sin(angle), 0])
                perpendicular = np.array([-math.sin(angle), math.cos(angle), 0])
                vertices = np.array([center + u * direction + v * perpendicular
                                     for u, v in [(-.61, -.025), (.61, -.025),
                                                  (.61, .025), (-.61, .025)]])
                faces.append((vertices * scale @ rotation.T + position, (41, 48, 53, 85)))
    return faces, position


def font(size):
    for candidate in ['/System/Library/Fonts/Monaco.ttf',
                      '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf']:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default(size=size)


def frame(base, t, variant):
    image = base.copy()
    faces = []
    count = [0, 1, 2][variant]
    for index in range(count):
        mesh, position = moving_drone(t, index, variant)
        faces.extend(mesh)
        shadow = Image.new('RGBA', image.size)
        shadow_points = []
        for a in np.linspace(0, math.tau, 36, endpoint=False):
            shadow_points.append((position[0] + 1.4 * math.cos(a) + 3,
                                  position[1] + .65 * math.sin(a) + 2, .05))
        ground_poly(shadow, shadow_points, (18, 29, 29, 52))
        image = Image.alpha_composite(image.convert('RGBA'), shadow.filter(ImageFilter.GaussianBlur(5))).convert('RGB')
    paint_faces(image, faces)
    # A tiny camera softness integrates the rendered geometry with the scene.
    image = image.filter(ImageFilter.GaussianBlur(.28))
    draw = ImageDraw.Draw(image, 'RGBA')
    draw.rounded_rectangle((15, 14, 226, 45), radius=3, fill=(12, 27, 34, 167))
    draw.text((25, 21), 'SYNTHETIC CAMERA', font=font(17), fill=(232, 239, 239, 240))
    draw.rounded_rectangle((15, HEIGHT - 40, 245, HEIGHT - 14), radius=3, fill=(12, 27, 34, 145))
    draw.text((25, HEIGHT - 35), f'CAM 01  /  00:00:{int(t):02d}', font=font(14), fill=(224, 232, 231, 240))
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('data/viso-feed'))
    parser.add_argument('--ffmpeg', default=shutil.which('ffmpeg') or '/opt/homebrew/bin/ffmpeg')
    parser.add_argument('--stills-only', action='store_true', help='Render QA stills without videos.')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    base = background()
    manifest = {'schema_version': 1, 'source': 'procedural_camera_renderer',
                'synthetic': True, 'clips': []}
    # Make a useful inference input available before rendering the controls.
    for variant in [1, 2, 0]:
        clip_id = f'clip-{variant + 1:02d}'
        still = args.output / f'{clip_id}.png'
        frame(base, DURATION * .44, variant).save(still)
        if not args.stills_only:
            video = args.output / f'{clip_id}.mp4'
            command = [args.ffmpeg, '-hide_banner', '-loglevel', 'error', '-y',
                       '-f', 'rawvideo', '-vcodec', 'rawvideo', '-pix_fmt', 'rgb24',
                       '-s', f'{WIDTH}x{HEIGHT}', '-r', str(FPS), '-i', '-',
                       '-an', '-c:v', 'libx264', '-preset', 'fast', '-crf', '20',
                       '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(video)]
            process = subprocess.Popen(command, stdin=subprocess.PIPE)
            try:
                for i in range(FPS * DURATION):
                    process.stdin.write(frame(base, i / FPS, variant).tobytes())
                process.stdin.close()
                if process.wait() != 0:
                    raise RuntimeError(f'ffmpeg failed while rendering {clip_id}')
            except BaseException:
                process.kill()
                process.wait()
                raise
        manifest['clips'].append({'clip_id': clip_id, 'file': f'{clip_id}.mp4',
                                  'still': still.name, 'duration_seconds': DURATION,
                                  'fps': FPS, 'width': WIDTH, 'height': HEIGHT,
                                  'synthetic': True})
        print(f'Rendered {clip_id}', flush=True)
    if not args.stills_only:
        manifest['clips'].sort(key=lambda clip: clip['clip_id'])
        (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    main()
