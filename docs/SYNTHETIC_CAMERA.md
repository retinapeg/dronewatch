# Synthetic camera inputs for Viso

## Simple 2D input used by the event demo

The requested schematic is generated with:

```sh
python scripts/render_viso_schematic.py --output /path/to/viso-feed --clip-id schematic-02
```

`schematic-02.png` is the camera observation at simulation time 58 seconds.
`schematic-02.mp4` shows simulation seconds 40–70 in eight playback seconds.
The video uses the existing `operator_demo`, seed 42, count 6, and
`radar_off_30s_viso` mode. It reproduces the preview's radar-only first pass,
camera cue planner, and second `pipeline_input` pass with that cue schedule.
Positions come only from `viso-eo` measurements at their acquisition time;
there is no ground-truth access, interpolation from future measurements, or
position invented when the camera sees nothing. Only observations visible in
the current cued camera sector are drawn.

The camera cue schedule is also saved as `schematic-cues.json`, containing only
simulation times and bearings. Pass it using `--cues-json` for an exact offline
replay of that schedule, or pass a saved `/api/preview/tracks` response. Loss
ensembles now seed from a stable CRC32 of the track identifier, so independent
renderer and server processes agree regardless of Python's hash seed. Previously
the built-in process-randomised hash changed the containment shape and therefore
the camera pointing between restarts. The earlier `schematic-01` files remain
the immutable source of their already-received Viso response.

The user requested **DRONE** and **MISSILE** labels. These are explicit synthetic
test artwork, assigned consistently between nearby observations, and are not
the existing domain's classification values. The tracker receives no renderer
labels or identities. Viso may read these labels as well as the glyph shapes;
success is a labelled schematic integration test, not evidence of recognition
performance on camera footage. The media annotation states **LABELLED TEST
SYMBOLS**.

The manifest provides scenario, seed, count, mode, simulation window, still time,
fixed epoch and coordinate calibration for linking a real returned Viso result
to its input. It does not expose individual objects, labels or expected answers.
The existing tracker retains responsibility for lost-contact propagation,
uncertainty, camera cueing and reacquisition. A textual Viso result without
numeric image coordinates cannot establish a new tracker position.

## Earlier camera-style samples

`scripts/render_viso_media.py` generates real camera-view PNG and MP4 files for
uploading to a visual-inference service. It does not generate webhook payloads
or model answers. All imagery is a procedural 3D projection rendered locally;
there are no downloaded assets or external rendering services.

Run with Python 3, Pillow, NumPy and ffmpeg installed:

```sh
python scripts/render_viso_media.py --output /path/to/viso-feed
```

Use `--ffmpeg /absolute/path/to/ffmpeg` if ffmpeg is not on PATH. The
`--stills-only` option is a quick visual check that does not replace the video
manifest. Rendering is deterministic for a fixed Python/library/ffmpeg runtime.

The generated files are `clip-01.mp4` through `clip-03.mp4`, corresponding PNG
preview stills, and `manifest.json`. Videos are eight seconds long, 960×540,
15 fps, H.264 with yuv420p pixels and faststart enabled. They are silent and
small enough to upload during a live demonstration. The first useful clip is
rendered before the controls so it can be uploaded immediately.

Each input has a modest **SYNTHETIC CAMERA** label and camera timer. No detector
labels, bounding boxes, object identifiers, future positions or expected answers
are drawn into the pixels or exported in the manifest. The scene includes a
chain-link fence, hangars, runway and detailed quadcopter geometry with four
motors, blurred propellers, a camera gimbal and landing gear.

For development evaluation only, clip 01 is the empty-camera control, clip 02
contains a crossing quadcopter and clip 03 contains two crossing quadcopters.
Do not pass these expected outcomes into Viso, the operator tracking pipeline,
or the camera-result display. Viso must infer its own results from the media.

The manifest contains only media metadata: clip ID, filenames, dimensions,
duration, frame rate and synthetic provenance. Displayed detections must come
from actual received Viso responses. Until a result arrives, the frontend should
show that processing is pending. Rendered camera playback alone does not prove
that Viso has processed the clip or that a webhook is connected to that input.

Viso's Google Drive input can consume these files when they are uploaded into
the folder monitored by the configured application. This renderer does not
upload files, poll Viso, spend inference credits, or simulate a successful
delivery. The application integration handles those steps separately.
