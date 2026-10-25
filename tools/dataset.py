"""Small, explicit dataset preparation tools. No downloads or training jobs."""
import argparse
import csv
import json
import random
import shutil
import struct
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Iterable, Protocol


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def image_size(path):
    """Read PNG/JPEG dimensions without introducing a base-app dependency."""
    with Path(path).open("rb") as stream:
        header = stream.read(24)
        if header[:8] == b"\x89PNG\r\n\x1a\n" and header[12:16] == b"IHDR":
            width, height = struct.unpack(">II", header[16:24])
        elif header[:2] == b"\xff\xd8":
            stream.seek(2)
            while True:
                marker = stream.read(1)
                if not marker:
                    raise ValueError("JPEG has no readable frame header")
                if marker != b"\xff":
                    continue
                marker = stream.read(1)
                while marker == b"\xff":
                    marker = stream.read(1)
                if not marker or marker in (b"\xd9", b"\xda"):
                    raise ValueError("JPEG has no readable frame header")
                code = marker[0]
                if code in (0, 1) or 0xD0 <= code <= 0xD8:
                    continue
                length_bytes = stream.read(2)
                if len(length_bytes) != 2:
                    raise ValueError("truncated JPEG")
                length = struct.unpack(">H", length_bytes)[0]
                if length < 2:
                    raise ValueError("invalid JPEG segment")
                if code in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                            0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    frame = stream.read(5)
                    if len(frame) != 5:
                        raise ValueError("truncated JPEG frame")
                    height, width = struct.unpack(">HH", frame[1:5])
                    break
                stream.seek(length - 2, 1)
        else:
            raise ValueError("only PNG/JPEG images are supported by this validator")
    if width <= 0 or height <= 0:
        raise ValueError("image dimensions must be positive")
    return width, height


def inspect_voc(annotations, images, classes=None, coordinate_origin=1):
    """Validate actual image headers and VOC boxes, returning data plus diagnostics.

    VOC traditionally uses one-based inclusive coordinates. Specify origin=0
    explicitly for exporters using zero-based half-open coordinates.
    """
    annotations, images = Path(annotations).resolve(), Path(images).resolve()
    if not annotations.is_dir() or not images.is_dir():
        raise ValueError("annotations and images must be existing directories")
    report = {"errors": [], "warnings": [], "class_counts": {},
              "image_dimensions": {}, "empty_labels": 0, "annotation_count": 0}
    rows, referenced, counts = [], set(), Counter()
    xml_paths = sorted(annotations.rglob("*.xml"))
    if not xml_paths:
        report["errors"].append("no VOC XML annotations found")
    for xml_path in xml_paths:
        report["annotation_count"] += 1
        try:
            if xml_path.stat().st_size > 5_000_000:
                raise ValueError("annotation exceeds 5 MB")
            root = ET.parse(xml_path).getroot()
            filename = root.findtext("filename")
            if not filename:
                raise ValueError("missing filename")
            image = (images / filename).resolve()
            if images not in image.parents:
                raise ValueError("filename escapes the images directory")
            if image in referenced:
                raise ValueError("duplicate annotation for image " + filename)
            referenced.add(image)
            if not image.is_file():
                raise ValueError("missing image: " + filename)
            actual = image_size(image)
            declared = (int(root.findtext("size/width", "0")),
                        int(root.findtext("size/height", "0")))
            report["image_dimensions"][filename] = list(actual)
            if declared != actual:
                raise ValueError("XML dimensions %s differ from image %s" % (declared, actual))
            width, height = actual
            boxes = []
            objects = root.findall("object")
            if not objects:
                report["empty_labels"] += 1
                report["warnings"].append(str(xml_path) + ": empty label (background image)")
            for obj in objects:
                name = (obj.findtext("name") or "").strip()
                if not name:
                    raise ValueError("object has no class name")
                counts[name] += 1
                if classes is not None and name not in classes:
                    raise ValueError("unknown class %r; specify the real class names" % name)
                raw = [float(obj.findtext("bndbox/" + key, "nan"))
                       for key in ("xmin", "ymin", "xmax", "ymax")]
                x1, y1, x2, y2 = raw
                if coordinate_origin == 1:
                    x1, y1 = x1 - 1, y1 - 1
                if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
                    raise ValueError("invalid, negative or out-of-bounds box: %s" % raw)
                boxes.append({"class_name": name, "bbox": [x1, y1, x2, y2]})
            rows.append({"image": image, "relative": image.relative_to(images),
                         "width": width, "height": height, "boxes": boxes})
        except (ValueError, OSError, ET.ParseError, struct.error) as exc:
            report["errors"].append(str(xml_path) + ": " + str(exc))
    for image in sorted(images.rglob("*")):
        if image.is_file() and image.suffix.lower() in IMAGE_SUFFIXES and image.resolve() not in referenced:
            report["errors"].append("missing annotation: " + str(image))
    report["class_counts"] = dict(counts)
    return report, rows


def convert_voc(annotations, images, output, classes, every_n=1, coordinate_origin=1):
    if every_n < 1 or not classes or len(classes) != len(set(classes)):
        raise ValueError("every_n must be positive and classes must be unique/nonempty")
    report, rows = inspect_voc(annotations, images, classes, coordinate_origin)
    if report["errors"]:
        raise ValueError(json.dumps(report, indent=2))
    output = Path(output).resolve()
    labels = output / "labels"
    selected = rows[::every_n]
    targets = [row["relative"].with_suffix(".txt") for row in selected]
    if len(targets) != len(set(targets)):
        raise ValueError("image basenames collide after conversion to .txt labels")
    labels.mkdir(parents=True, exist_ok=True)
    with (output / "manifest.csv").open("w", newline="") as manifest:
        writer = csv.DictWriter(manifest, fieldnames=["image", "label", "source_video"])
        writer.writeheader()
        for row in selected:
            target = labels / row["relative"].with_suffix(".txt")
            target.parent.mkdir(parents=True, exist_ok=True)
            lines = []
            for box in row["boxes"]:
                x1, y1, x2, y2 = box["bbox"]
                values = ((x1 + x2) / (2 * row["width"]), (y1 + y2) / (2 * row["height"]),
                          (x2 - x1) / row["width"], (y2 - y1) / row["height"])
                lines.append(str(classes.index(box["class_name"])) + " " +
                             " ".join("%.8f" % value for value in values))
            target.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
            writer.writerow({"image": str(row["image"]), "label": str(target), "source_video": ""})
    (output / "classes.txt").write_text("\n".join(classes) + "\n", encoding="utf-8")
    report["converted_images"] = len(selected)
    (output / "validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def split_by_video(manifest, output, train_fraction=0.8, seed=42):
    """Never infer video identity from adjacent frame names."""
    if not 0 < train_fraction < 1:
        raise ValueError("train_fraction must be between 0 and 1")
    manifest = Path(manifest).resolve()
    with manifest.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    groups, seen = {}, set()
    for row in rows:
        video = (row.get("source_video") or "").strip()
        if not video or not row.get("image") or not row.get("label"):
            raise ValueError("each manifest row needs image, label and explicit source_video")
        image = (manifest.parent / row["image"]).resolve()
        label = (manifest.parent / row["label"]).resolve()
        if not image.is_file() or not label.is_file():
            raise ValueError("manifest references a missing image or annotation")
        if image in seen:
            raise ValueError("duplicate image in manifest: " + str(image))
        seen.add(image)
        groups.setdefault(video, []).append((image, label))
    if len(groups) < 2:
        raise ValueError("at least two source videos are required for a leakage-safe split")
    videos = sorted(groups)
    random.Random(seed).shuffle(videos)
    cut = max(1, min(len(videos) - 1, int(len(videos) * train_fraction)))
    assignments = {"train": videos[:cut], "val": videos[cut:]}
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    for split, names in assignments.items():
        paths = []
        for group_index, video in enumerate(names):
            for frame_index, (image, label) in enumerate(groups[video]):
                # A canonical images/labels layout makes the lists YOLO-ready.
                stem = "video%04d_frame%07d" % (group_index, frame_index)
                dest_image = output / "images" / split / (stem + image.suffix.lower())
                dest_label = output / "labels" / split / (stem + ".txt")
                dest_image.parent.mkdir(parents=True, exist_ok=True)
                dest_label.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(image, dest_image)
                shutil.copy2(label, dest_label)
                paths.append(str(dest_image))
        (output / (split + ".txt")).write_text("\n".join(paths) + "\n", encoding="utf-8")
    (output / "split.json").write_text(json.dumps({"seed": seed, "source_videos": assignments}, indent=2), encoding="utf-8")
    return assignments


def extract_frames(video, output, every_n=10, limit=None):
    if every_n < 1 or (limit is not None and limit < 1):
        raise ValueError("every_n and limit must be positive")
    try:
        import cv2
    except ImportError as exc:
        raise ValueError("frame extraction requires pip install -r requirements-data.txt") from exc
    video = Path(video).resolve()
    if not video.is_file():
        raise ValueError("source video does not exist")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        capture.release()
        raise ValueError("cannot open source video")
    index, written = 0, 0
    fps = capture.get(cv2.CAP_PROP_FPS)
    try:
        with (output / "frames.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=["image", "source_video", "frame_index", "timestamp_seconds"])
            writer.writeheader()
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                if index % every_n == 0:
                    image = output / ("frame_%08d.jpg" % index)
                    if not cv2.imwrite(str(image), frame):
                        raise ValueError("failed to write extracted frame")
                    writer.writerow({"image": str(image), "source_video": str(video),
                                     "frame_index": index, "timestamp_seconds": index / fps if fps > 0 else ""})
                    written += 1
                    if limit is not None and written >= limit:
                        break
                index += 1
    finally:
        capture.release()
    return {"frames_written": written, "every_n": every_n,
            "note": "No labels invented; use frame_index to join real annotations."}


class AntiUAVAdapter(Protocol):
    def annotated_frames(self, sample_label_file: Path) -> Iterable[dict]:
        """Return frame_index, image, class_name and explicitly specified boxes."""
        ...


def require_anti_uav_sample(sample_label_file=None):
    if sample_label_file is None or not Path(sample_label_file).is_file():
        raise ValueError("Anti-UAV: a sample label file is required before implementing the adapter; no schema is assumed.")
    raise ValueError("Anti-UAV sample supplied, but its schema must be reviewed and a dataset-specific adapter implemented first.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate-voc", "voc-to-yolo"):
        command = commands.add_parser(name)
        command.add_argument("--annotations", type=Path, required=True)
        command.add_argument("--images", type=Path, required=True)
        command.add_argument("--class", dest="classes", action="append")
        command.add_argument("--coordinate-origin", type=int, choices=[0, 1], default=1)
        if name == "voc-to-yolo":
            command.add_argument("--output", type=Path, required=True)
            command.add_argument("--every-n", type=int, default=1)
    command = commands.add_parser("split")
    command.add_argument("--manifest", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--train-fraction", type=float, default=0.8)
    command.add_argument("--seed", type=int, default=42)
    command = commands.add_parser("extract-frames")
    command.add_argument("--video", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--every-n", type=int, default=10)
    command.add_argument("--limit", type=int)
    command = commands.add_parser("anti-uav")
    command.add_argument("--sample-label-file", type=Path)
    args = vars(parser.parse_args(argv))
    command = args.pop("command")
    try:
        if command == "validate-voc":
            report, _ = inspect_voc(**args)
            print(json.dumps(report, indent=2))
            return 1 if report["errors"] else 0
        if command == "voc-to-yolo":
            if not args["classes"]:
                raise ValueError("supply --class for each actual class, in YOLO class-id order")
            result = convert_voc(**args)
        elif command == "split":
            result = split_by_video(**args)
        elif command == "extract-frames":
            result = extract_frames(**args)
        else:
            result = require_anti_uav_sample(**args)
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
