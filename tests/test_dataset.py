import csv
import struct
from pathlib import Path

import pytest

from dronewatch.tools.dataset import (convert_voc, extract_frames, inspect_voc,
                                     require_anti_uav_sample, split_by_video)


def sample(tmp_path, name="frame.png", box=(1, 1, 50, 25), declared=(100, 50), empty=False):
    images, annotations = tmp_path / "images", tmp_path / "annotations"
    images.mkdir(exist_ok=True)
    annotations.mkdir(exist_ok=True)
    # Only the header is required for dimension validation; no decoder dependency.
    (images / name).write_bytes(b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 100, 50))
    obj = "" if empty else "<object><name>drone</name><bndbox>" + "".join(
        "<%s>%s</%s>" % (key, value, key) for key, value in zip(("xmin", "ymin", "xmax", "ymax"), box)
    ) + "</bndbox></object>"
    (annotations / (Path(name).stem + ".xml")).write_text(
        "<annotation><filename>%s</filename><size><width>%s</width><height>%s</height></size>%s</annotation>" %
        (name, declared[0], declared[1], obj))
    return images, annotations


def test_voc_conversion_actual_dimensions_and_one_based_coordinates(tmp_path):
    images, annotations = sample(tmp_path)
    report = convert_voc(annotations, images, tmp_path / "converted", ["drone"])
    assert not report["errors"]
    assert report["class_counts"] == {"drone": 1}
    assert report["image_dimensions"] == {"frame.png": [100, 50]}
    label = (tmp_path / "converted/labels/frame.txt").read_text().split()
    assert label[0] == "0"
    assert list(map(float, label[1:])) == [0.25, 0.25, 0.5, 0.5]


@pytest.mark.parametrize("box", [(-1, 0, 10, 10), (40, 0, 20, 10), (1, 1, 101, 20), (float("nan"), 1, 2, 3)])
def test_invalid_boxes_do_not_produce_labels(tmp_path, box):
    images, annotations = sample(tmp_path, box=box)
    report, _ = inspect_voc(annotations, images)
    assert report["errors"]
    with pytest.raises(ValueError):
        convert_voc(annotations, images, tmp_path / "out", ["drone"])
    assert not (tmp_path / "out").exists()


def test_validator_missing_images_annotations_dimensions_and_empty_labels(tmp_path):
    images, annotations = sample(tmp_path, declared=(200, 50))
    report, _ = inspect_voc(annotations, images)
    assert "dimensions" in report["errors"][0]
    sample(tmp_path, empty=True)
    report, _ = inspect_voc(annotations, images)
    assert not report["errors"] and report["empty_labels"] == 1
    assert report["warnings"]
    (images / "frame.png").rename(images / "orphan.png")
    report, _ = inspect_voc(annotations, images)
    assert any("missing image" in item for item in report["errors"])
    assert any("missing annotation" in item for item in report["errors"])


def test_subsampling_and_zero_based_exporters(tmp_path):
    for n in range(5):
        images, annotations = sample(tmp_path, name="frame%d.png" % n, box=(0, 0, 50, 25))
    report = convert_voc(annotations, images, tmp_path / "out", ["drone"], every_n=2, coordinate_origin=0)
    assert report["converted_images"] == 3


def test_split_assigns_whole_videos_and_requires_real_group_metadata(tmp_path):
    manifest = tmp_path / "manifest.csv"
    with manifest.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["image", "label", "source_video"])
        writer.writeheader()
        for video in ("a", "b", "c"):
            for frame in range(3):
                image = tmp_path / ("%s%d.png" % (video, frame))
                label = image.with_suffix(".txt")
                image.write_bytes(b"image")
                label.write_text("0 .5 .5 .1 .1\n")
                writer.writerow({"image": image, "label": label, "source_video": video})
    assignment = split_by_video(manifest, tmp_path / "split", seed=3)
    assert set(assignment["train"]).isdisjoint(assignment["val"])
    assert set(assignment["train"] + assignment["val"]) == {"a", "b", "c"}
    assert assignment == split_by_video(manifest, tmp_path / "split2", seed=3)
    assert len(list((tmp_path / "split/images").rglob("*.png"))) == 9
    manifest.write_text("image,label,source_video\nimage.png,label.txt,\n")
    with pytest.raises(ValueError, match="explicit source_video"):
        split_by_video(manifest, tmp_path / "bad")


def test_anti_uav_requires_a_sample_and_never_guesses_a_schema():
    with pytest.raises(ValueError, match="sample label file is required"):
        require_anti_uav_sample()


def test_frame_extraction_validates_stride_before_optional_import(tmp_path):
    with pytest.raises(ValueError, match="positive"):
        extract_frames(tmp_path / "missing.mp4", tmp_path / "frames", every_n=0)
