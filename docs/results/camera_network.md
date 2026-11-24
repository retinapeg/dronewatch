# Camera-network experiments

Mode `camera_network`: faults `cameras:on;reach:1400;runin:72;hold:15`, 32 cameras, run length 162 s, scenario `operator_demo`.
Held-out seeds: [10000, 10001, 10002, 10003, 10004, 10005, 10006, 10007], not run until the layout and the code were finished. Development seeds [42, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 2024, 31337, 99, 555] are excluded from the first table.

## Held-out seeds

| contacts | seed | tracks | untracked | extra | far / fresh frames | RMSE m | first fix km | radar km | lead s | gain s min / median (tracks) | custody min | merged | ghosts refused + vetoed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 3 | 10000 | 3 | 0 | 0 | 0 / 1690 | 6.4 | 3.25 at T+23.2 | 1.39 at T+99.8 | 76.6 | 76.6 / 83.1 (2) | 0.99 | 0 | 0 + 0 |
| 3 | 10001 | 3 | 0 | 0 | 0 / 1501 | 7.5 | 3.33 at T+23.6 | 1.39 at T+107.2 | 83.6 | 62.0 / 72.8 (2) | 1.0 | 0 | 0 + 0 |
| 3 | 10002 | 3 | 0 | 0 | 0 / 1751 | 5.7 | 3.27 at T+20.6 | 1.39 at T+88.2 | 67.6 | 67.6 / 74.9 (2) | 1.0 | 0 | 0 + 0 |
| 3 | 10003 | 3 | 0 | 0 | 0 / 1736 | 6.3 | 3.27 at T+22.6 | 1.39 at T+93.8 | 71.2 | 66.6 / 71.2 (3) | 1.0 | 0 | 0 + 0 |
| 3 | 10004 | 3 | 0 | 0 | 0 / 1680 | 7.0 | 3.23 at T+23.2 | 1.38 at T+94.2 | 71.0 | 71.0 / 78.5 (2) | 1.0 | 0 | 0 + 0 |
| 3 | 10005 | 3 | 0 | 0 | 0 / 1653 | 6.3 | 3.23 at T+22.6 | 1.39 at T+102.2 | 79.6 | 71.6 / 75.6 (2) | 1.0 | 0 | 0 + 0 |
| 3 | 10006 | 3 | 0 | 0 | 0 / 1720 | 5.8 | 3.22 at T+23.2 | 1.39 at T+87.8 | 64.6 | 64.0 / 64.3 (2) | 1.0 | 0 | 0 + 0 |
| 3 | 10007 | 3 | 0 | 0 | 0 / 1691 | 5.7 | 3.08 at T+29.6 | 1.38 at T+98.8 | 69.2 | 69.2 / 80.9 (2) | 1.0 | 0 | 0 + 0 |
| 6 | 10000 | 6 | 0 | 0 | 0 / 3135 | 7.1 | 3.24 at T+27.2 | 1.39 at T+105.8 | 78.6 | 61.8 / 76.3 (4) | 1.0 | 0 | 0 + 0 |
| 6 | 10001 | 6 | 0 | 0 | 0 / 2984 | 6.6 | 3.26 at T+25.6 | 1.39 at T+103.8 | 78.2 | 67.6 / 75.9 (4) | 0.99 | 0 | 0 + 0 |
| 6 | 10002 | 6 | 0 | 0 | 0 / 3121 | 6.2 | 3.22 at T+25.6 | 1.39 at T+101.2 | 75.6 | 67.0 / 72.4 (4) | 0.94 | 0 | 0 + 0 |
| 6 | 10003 | 6 | 0 | 0 | 0 / 3119 | 6.3 | 3.07 at T+31.6 | 1.39 at T+99.2 | 67.6 | 56.2 / 66.6 (4) | 1.0 | 0 | 0 + 0 |
| 6 | 10004 | 6 | 0 | 0 | 0 / 3050 | 6.3 | 3.23 at T+25.2 | 1.39 at T+101.2 | 76.0 | 59.6 / 70.8 (4) | 0.91 | 0 | 0 + 0 |
| 6 | 10005 | 6 | 0 | 0 | 0 / 3143 | 6.0 | 3.25 at T+23.2 | 1.38 at T+95.8 | 72.6 | 60.8 / 67.9 (4) | 0.99 | 0 | 1 + 0 |
| 6 | 10006 | 6 | 0 | 0 | 0 / 3268 | 6.3 | 3.24 at T+27.2 | 1.4 at T+98.2 | 71.0 | 63.0 / 64.6 (5) | 0.97 | 0 | 0 + 0 |
| 6 | 10007 | 6 | 0 | 0 | 0 / 3197 | 6.7 | 3.24 at T+25.6 | 1.37 at T+107.2 | 81.6 | 59.8 / 75.9 (4) | 0.95 | 0 | 0 + 0 |
| 10 | 10000 | 10 | 0 | 0 | 0 / 4960 | 6.1 | 3.2 at T+23.2 | 1.38 at T+94.8 | 71.6 | 69.8 / 74.2 (7) | 0.89 | 0 | 0 + 0 |
| 10 | 10001 | 10 | 0 | 0 | 0 / 4900 | 6.2 | 3.24 at T+21.6 | 1.39 at T+98.2 | 76.6 | 64.2 / 75.8 (6) | 0.82 | 0 | 0 + 0 |
| 10 | 10002 | 10 | 0 | 0 | 0 / 4606 | 6.3 | 3.25 at T+22.2 | 1.38 at T+98.2 | 76.0 | 64.6 / 75.9 (6) | 0.99 | 0 | 0 + 0 |
| 10 | 10003 | 10 | 0 | 0 | 0 / 4773 | 6.8 | 3.28 at T+20.6 | 1.4 at T+99.2 | 78.6 | 59.6 / 70.8 (7) | 0.79 | 0 | 0 + 0 |
| 10 | 10004 | 10 | 0 | 0 | 32 / 4792 | 29.6 | 3.28 at T+22.2 | 1.39 at T+96.2 | 74.0 | 59.6 / 73.6 (7) | 0.98 | 0 | 2 + 2 |
| 10 | 10005 | 10 | 0 | 0 | 0 / 5017 | 6.6 | 3.25 at T+24.2 | 1.38 at T+94.8 | 70.6 | 58.6 / 75.9 (6) | 0.96 | 0 | 0 + 0 |
| 10 | 10006 | 10 | 0 | 0 | 0 / 4749 | 7.4 | 3.25 at T+22.2 | 1.39 at T+93.2 | 71.0 | 60.2 / 68.6 (6) | 0.87 | 0 | 0 + 0 |
| 10 | 10007 | 10 | 0 | 0 | 0 / 4854 | 7.3 | 3.25 at T+21.6 | 1.38 at T+95.2 | 73.6 | 70.2 / 73.6 (6) | 0.98 | 0 | 0 + 0 |

Per contact count, over the held-out seeds:

| contacts | runs with one track per contact and no far frame | untracked contacts | extra tracks | far fresh frames | lead s, min to max | custody, min |
|---|---|---|---|---|---|---|
| 3 | 8 of 8 | 0 | 0 | 0 of 13422 | 64.6 to 83.6 | 0.99 |
| 6 | 8 of 8 | 0 | 0 | 0 of 25017 | 67.6 to 81.6 | 0.91 |
| 10 | 7 of 8 | 0 | 0 | 32 of 38651 | 70.6 to 78.6 | 0.79 |

## Seed 42, the one the demo replays (a development seed)

| contacts | seed | tracks | untracked | extra | far / fresh frames | RMSE m | first fix km | radar km | lead s | gain s min / median (tracks) | custody min | merged | ghosts refused + vetoed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 3 | 42 | 3 | 0 | 0 | 0 / 1671 | 6.0 | 3.25 at T+22.6 | 1.38 at T+95.2 | 72.6 | 72.6 / 76.4 (2) | 1.0 | 0 | 0 + 0 |
| 6 | 42 | 6 | 0 | 0 | 0 / 3096 | 7.6 | 3.26 at T+26.2 | 1.39 at T+99.2 | 73.0 | 58.6 / 69.0 (4) | 0.98 | 0 | 0 + 0 |
| 10 | 42 | 11 | 0 | 1 | 0 / 4749 | 7.0 | 3.28 at T+23.2 | 1.4 at T+99.2 | 76.0 | 0.0 / 71.0 (7) | 0.98 | 1 | 1 + 0 |

## Metric definitions

```
contacts          true contacts in the run.
tracks            distinct track identities ever shown (confirmed), whole run.
untracked         true contacts that are never the nearest contact, within 150 m, of any
                  freshly positioned track. A contact no two cameras ever saw together.
extra             tracks - (contacts - untracked): identities beyond one per tracked contact
                  (a duplicate on a real contact, or a track restarted after a loss).
far_fresh_frames  (frame, track) pairs where a freshly positioned track (fresh == U) is more
                  than 150 m from every true contact: a track that is not on anything.
                  Denominator fresh_frames.
rmse_m            sqrt(mean |p_est - p_true|^2) over fresh (frame, track) pairs before the
                  radar has contributed to the track, p_true being the nearest true contact.
first_fix_km      range from the site centre at which the first track of the run is first
                  shown, and first_fix_s when.
radar_km          range at which the radar first contributes to any track, and radar_s when.
lead_s            radar_s - first_fix_s: how long the cameras had a position on something
                  before the radar had seen anything.
gain_s            per track the radar ever saw: seconds between the track first being shown
                  and the radar first contributing to it. Minimum and median over those tracks.
custody           per track the radar ever saw: share of frames, from first shown until the
                  radar contributes, in which the track is freshly positioned. Minimum over
                  those tracks.
merged            duplicate tracks retired by the tracker.
ghosts_refused    crossings of two known objects' directions that were not believed, and
                  vetoed: new crossings a third camera should have seen and did not.
```
