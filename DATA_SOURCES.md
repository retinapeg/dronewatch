# DroneWatch data and feed decision

Research status: verified from primary sources on 7 September 2026.

V0.2 fixture status: a six-clip Halmstad selection is pinned and manifest
controlled. The media itself is external to Git. The selection was made before
any Viso result was available; no result-based cherry-picking occurred.

## Decision

Use **Viso Now for discrete visual files**, a small licence-clean evaluation
pack, **replayed real radar**, and clearly labelled deterministic synthetic
tracks. Do not build the first demo around a supposed open live radar feed: no
defensible public live counter-UAS/air-defence radar API was found.

If a live layer is useful, add cooperative ADS-B or Direct Remote ID telemetry
and name it accurately. A live counter-UAS radar claim requires owned hardware
or a provider/defence partner feed.

Viso Now is a managed visual-analysis service that advertises no-training setup.
The first data need is therefore an **evaluation fixture set**, not a large
training download. Training a separate custom model is a later decision.

## Viso product boundary

The intended self-service product is **Viso Now**, distinct from enterprise
**Viso Suite**.

- [Viso Now processing model](https://docs.now.viso.ai/media-processing-model):
  discrete media files, not continuous live video streams.
- [Input connectors](https://docs.now.viso.ai/input-connectors): manual upload or
  SharePoint, OneDrive, S3, Azure Blob, Google Cloud Storage, and Google Drive;
  image and video files are supported.
- [Google Drive connector](https://docs.now.viso.ai/google-drive): polling at 15
  seconds, 30 seconds, 1 minute, or 5 minutes.
- [Output connectors](https://docs.now.viso.ai/output-connectors) and
  [Webhook/API output](https://docs.now.viso.ai/webhook-api): outbound structured
  results to a customer endpoint, with 2xx acknowledgement expected.
- [Custom output messages](https://docs.now.viso.ai/custom-output-messages):
  webhook JSON can be configured, so DroneWatch must own and version its
  contract rather than guess a universal Viso payload.
- [Changelog](https://docs.now.viso.ai/changelog): the 2 July 2026 entry still
  described IP Camera Gateway as coming soon outside development; no later
  general-availability entry was visible by the research date.

The public documentation does not define webhook signatures, retries, ordering,
timeouts, delivery guarantees, a canonical schema, or a Viso idempotency key.
Those details must be captured from the actual account and a redacted test
delivery.

Viso Suite separately documents RTSP/IP cameras, edge/on-prem processing,
custom models, and fleet deployment. Those enterprise capabilities are a future
path and must not be attributed to the current Viso Now file demo.

## Recommended immediate datasets

| Priority | Source | Modality and verified scope | Rights and decision |
| --- | --- | --- | --- |
| 1 | [Halmstad Drone Detection Dataset](https://github.com/DroneDetectionThesis/Drone-detection-dataset) | Ground-surveillance visible/thermal video and audio; 650 videos, 90 audio clips, 203,328 annotated frames; visual drone, bird, aircraft, and helicopter classes | Dataset is contained in a repository carrying [CC0 1.0](https://github.com/DroneDetectionThesis/Drone-detection-dataset/blob/master/LICENSE). Use a small curated visual fixture pack first. |
| 2 | [Real Doppler RAD-DAR](https://www.kaggle.com/datasets/iroldan/real-doppler-raddar-database) | Real 8.75 GHz FMCW range-Doppler crops; 17,485 samples: 5,065 drone, 6,700 person, 5,720 car; about 92.5 MB | Dataset and [source paper](https://ietresearch.onlinelibrary.wiley.com/doi/10.1049/iet-rsn.2019.0307) identify CC BY 4.0. Best first real-radar replay; not a live track feed. |
| 3 | [KTH 77 GHz FMCW](https://zenodo.org/records/5896641) | 75,868 samples across six drones, birds, and humans; mechanically scanned 77 GHz FMCW; 1.6 GB NumPy file | Dataset metadata is CC BY 4.0. Strong drone-versus-bird/human radar evaluation; not a full continuous geographic track. |
| 4 | [Tampere RF recordings](https://zenodo.org/records/4264467) | 8.6 GB of 2.44/5.8 GHz raw I/Q from ten consumer/prosumer drones, recorded in an anechoic chamber | Dataset metadata is CC BY 4.0. Good first RF spectrogram replay; do not generalize it to outdoor range/performance. |
| 5 | [SynDrone-Swarm](https://github.com/MehmetUnall/SynDrone-Swarm) | 79,200 synthetic RGB frames, YOLO boxes, multiple cameras/drones, and scenario telemetry | Data-only repository states CC BY 4.0. Good deterministic swarm and intent-story fixture; always label synthetic. |
| 6 | [Amazon Airborne Object Tracking](https://registry.opendata.aws/airborne-object-tracking/) | 4,943 roughly 120-second airborne-camera sequences, 5.9M+ grayscale images, 3.3M+ annotations and extensive no-object frames | CDLA-Permissive-1.0. Useful supplementary tiny-object and negative evaluation, but its airborne-camera viewpoint differs from a fixed perimeter camera. |

Do not download the full corpora for V0. Start with a small manifest-selected set
whose hashes, source sequences, annotations, and expected outcomes are reviewable.

## V0.2 Halmstad selection

The checked-in `fixtures/halmstad-selection.v1.json` is the authoritative
selection manifest. It pins the upstream repository to commit
`442d0c6750708cc221636f7a1fd31cbd8cb0aeb8`, records access on 7 September
2026, and identifies the dataset licence as CC0 1.0. Code, paper, and model
licences are recorded separately as `NOT_USED`; the data licence must not be
inferred from those artifacts.

Only the pinned licence plus the six selected clips and their matching label
files were fetched for hash verification. The corpus was not bulk-downloaded.
No media or label file is committed to DroneWatch, and `/fixture-media/` is
ignored. Each selected source file is used byte-for-byte
(`NONE_SOURCE_BYTES`), so its derived byte count and SHA-256 equal its upstream
values.

| Manifest fixture | Exact upstream file | Class/control | Bytes | SHA-256 |
| --- | --- | --- | ---: | --- |
| `halmstad-v-drone-001` | `Data/Video_V/V_DRONE_001.mp4` | Visible drone positive; relatively clear, larger target | 144,518 | `9db5a800377c01db8369dfba808d400ca52cd393e0a32850e1d20a4861eaecbe` |
| `halmstad-ir-drone-001` | `Data/Video_IR/IR_DRONE_001.mp4` | Thermal drone positive; smaller target near tree line | 25,853 | `19ec2ccbcccfdaf3566fff5122c30f8b82172b9e610c975d37558214dcd349d6` |
| `halmstad-v-bird-003` | `Data/Video_V/V_BIRD_003.mp4` | Visible bird hard negative; small aerial target | 87,927 | `502229dcf0c3633148e97635fcbc8a2bec520b091da3735a51ee6c7b06e074f4` |
| `halmstad-v-airplane-004` | `Data/Video_V/V_AIRPLANE_004.mp4` | Visible aircraft hard negative; distant target and haze | 96,903 | `940f2243e5a22701c28229b077347026f539070552254dc62be275819f47df9f` |
| `halmstad-v-helicopter-004` | `Data/Video_V/V_HELICOPTER_004.mp4` | Visible helicopter hard negative; roof/pole clutter | 93,602 | `7cb2561d567d62086bae684cdd392eeb4c77ee33903a3b068793a6d1a5ef1781` |
| `halmstad-ir-bird-003` | `Data/Video_IR/IR_BIRD_003.mp4` | Thermal bird hard negative; extremely small difficult target | 20,489 | `5017cbe6415994364987ac5db9dce375059c4709e5ea3d0ecd3aed527926bfdf` |

The manifest also records each matching MATLAB label identity, byte count, and
SHA-256, plus the pinned upstream URLs and the upstream licence hash. The labels
are provenance/ground-truth references; the V0.2 replay runner copies only the
selected MP4 source supplied by the operator.

The pack is for transport and later visual-evaluation evidence, not training.
Expected outcomes come from the upstream class labels and must not be rewritten
after processing. A Viso miss, negative, or false positive must be retained in
the supervised evidence record. Six short clips cannot establish accuracy,
reliability, operational suitability, range performance, or generalization.

### External-media preparation and validation

1. Obtain only a manifest-listed MP4 from the pinned upstream revision. Do not
   clone or download the full dataset by default.
2. Place it in a local external directory such as `fixture-media/`; do not add
   it to Git.
3. Run the replay command with the checked-in manifest, exact fixture ID, and
   local source. The runner rejects a basename, byte count, or SHA-256 mismatch
   before creating a watched-folder copy.
4. Keep the source read-only. The runner uses a temporary `.part` file followed
   by an atomic no-clobber publication and never deletes the source or existing
   completed files.
5. Retain the ignored run record as local copy evidence. Do not upgrade that
   evidence into a Drive, Viso, webhook, or detection claim.

To verify a locally prepared pack containing the exact six MP4 files, six label
files, and pinned `LICENSE` bytes:

```sh
.venv/bin/python scripts/verify_replay_artifacts.py \
  --media-dir /path/to/external-halmstad-selection
```

Without `--media-dir`, the same command validates only the checked-in manifest
and blank evidence template and explicitly reports that external bytes were not
checked.

## Later synchronized fusion dataset

[TSMS-Drone](https://doi.org/10.25452/figshare.plus.30027313) is the strongest
licence-clean public multimodal candidate found. It contains synchronized CW
radar, FMCW range-Doppler, and RF measurements for four drone models and a corner
reflector at 2–30 metres in 2-metre steps. The derived total is 37,500 aligned
three-sensor indices. The Figshare API reports about 392.8 GB across 85 files, so
V0 should select only specific target/range archives.

The dataset is CC BY 4.0. The associated article has different, more restrictive
rights; record the data licence and article licence separately. Technical limits
also remain visible: controlled conditions, short range, hovering targets, one
non-drone class, software/index synchronization, and processed main FMCW maps
rather than full raw FMCW ADC for the full corpus.

## Optional live context

- [ADSB.lol API](https://www.adsb.lol/docs/open-data/api/) provides openly
  accessible cooperative aircraft telemetry under the service's
  [ODbL/terms](https://www.adsb.lol/privacy-license/). If used, label it
  `LIVE COOPERATIVE AIRCRAFT TELEMETRY`. It is not radar and usually will not
  show ordinary small drones.
- The UK CAA's [Remote ID programme](https://www.caa.co.uk/drones/drone-regulations/policy-programmes/remote-id-rid/)
  makes a local receiver plus an owned compliant drone the most credible later
  live-drone telemetry demonstration. It is cooperative broadcast telemetry,
  not radar, and will not reveal a silent/non-compliant threat.
- Weather radar such as NEXRAD is genuine live radar but measures weather. It is
  not a drone-track source and is not part of the core plan.

## Permission-gated or rejected for the first defence-company demo

| Source | Reason not to use first |
| --- | --- |
| [OpenSky](https://opensky-network.org/about/terms-of-use) | ADS-B/Mode-S surveillance data, not counter-UAS radar. Current terms require written licensing for commercial entities, government/military contractors, and operational API use. |
| [Drone-vs-Bird Challenge](https://github.com/wosdetc/challenge) | Email request and signed research-purpose data agreement; no broad commercial-use licence. |
| [MMAUD](https://github.com/ntu-aris/MMAUD) | Excellent camera/lidar/radar/audio reference, but dataset terms are CC BY-NC-SA 4.0 and explicitly non-commercial. |
| [Open Radar Initiative](https://github.com/openradarinitiative/open_radar_datasets) | Convenient UAV/person/bicycle/vehicle tracks, but dataset licence is CC BY-NC 4.0. Repository code and dataset rights are separate. |
| [Anti-UAV](https://github.com/ZhaoJ9014/Anti-UAV) | Technically strong RGB/thermal benchmark, but the software-project licence does not clearly establish commercial rights in all externally hosted footage. Obtain written clarification first. |
| [NATO/NCIA ICMCIS challenge data](https://www.kaggle.com/c/icmcis-drone-tracking/data) | Highly relevant multi-radar/RF track reports, but challenge access/rules do not establish broad commercial reuse. Request NCIA permission. |

## Evaluation manifest requirements

Every imported fixture or external corpus must record:

- canonical title, owner/publisher, source URL, DOI where available, and version;
- separate data, code, paper, and model licences rather than assuming one covers
  all artifacts;
- download date, file hashes, bytes, selected source sequences, and portable
  upstream source paths; any machine-local storage path stays outside Git and
  retained evidence;
- modality, sensor/acquisition conditions, target classes, negatives, annotations,
  splits, and known quality issues;
- permitted uses, attribution text, redistribution limits, and permission notes;
- whether the item is training, validation, test, calibration, replay, or display
  material;
- transformations and derived-artifact hashes;
- any known metadata inconsistency, missing sample, timing limitation, or domain
  mismatch.

Split video/radar data by source sequence, flight, or measurement trial. Randomly
splitting neighboring frames or repeated measurements would leak near-duplicates
between train and test and produce misleading scores.

## Viso and defence-data gate

Viso's [Cloud Terms](https://viso.ai/legal/terms-of-service/) require uploaded
data not to be ITAR- or similarly controlled and contain export/end-use limits.
Only public, synthetic, CC0/licence-clean, or specifically authorized material
belongs in the self-service Viso Now path.

Before a defence-company pilot or public performance benchmark, obtain written
confirmation of the applicable Viso plan/order and permitted demonstration use.
Also verify the actual account's webhook authentication, connector entitlement,
credits, media retention, processing region, subprocessors, and any IP Camera
Gateway availability. None should be inferred from marketing copy.
