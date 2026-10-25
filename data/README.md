# Local dataset workspace

These directories are local-only; generated content is ignored by git.

- `raw/`: original licensed datasets, videos and annotations. Never edit originals.
- `interim/`: extracted/subsampled frames, reviewed replay manifests, conversion output.
- `processed/`: validated YOLO labels and leakage-safe train/validation splits.

Create them when needed with `mkdir -p data/raw data/interim data/processed`.
No dataset is downloaded automatically. Do not commit videos, credentials, model
weights or private source payloads. The small, explicitly synthetic test sequence
in `samples/` is intentionally versioned.

The VOC converter accepts standard Pascal VOC XML and checks the declared sizes
against PNG/JPEG image headers. Dataset-specific class names must be supplied
explicitly. See the root README for commands, coordinate conventions and the
Anti-UAV adapter boundary.
