# DroneWatch data and feed decision

Research status: verified from primary sources on 7 September 2026.

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
- download date, file hashes, bytes, selected source sequences, and local path;
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
