# Fixed cameras before the radar: the camera-network mode

This document explains the camera-network mode of the operator preview
(`/preview?demo=cameras`, mode `camera_network`): what is simulated, the
arithmetic behind each number, the code that implements it, the tests that pin
it and the measured results. Everything in the mode is synthetic.

The claim the mode demonstrates is narrow, and it is this:

> A set of fixed cameras, each reporting only the direction of what it sees,
> can place an incoming drone by crossing two directions, and can do so
> further out than a short-range radar sees the same drone.

Three things decide whether that is true in a given case, and all three are
stated with their numbers below: how big the drone is, what lenses the cameras
have and where they stand, and how far the radar reaches.

## 1. What is real here and what is not

- **Simulated:** the site, the cameras, their detections, the radar and the
  drones. No camera footage is analysed in this mode. A camera "detects" a
  drone when the drone is inside its view and large enough in the picture; the
  detector itself is not modelled beyond a detection probability.
- **Arithmetic, not simulation:** how far a camera with a given lens can see a
  drone of a given size (section 2). That follows from pixel counts.
- **Published figure:** the radar's reach, 1.4 km, is the tracking range a
  manufacturer publishes for a short-range counter-drone radar against a
  heavy-lift multirotor (section 9).
- **Not claimed:** that ordinary security cameras see drones miles away (they
  do not: section 2), that any vision product produced these detections, or
  that the result carries over to weather, night or a cluttered skyline.

## 2. How far a camera can see

A drone of width $s$ at range $R$, seen through a lens with horizontal field
of view $\mathrm{HFOV}$ on a sensor $N_x$ pixels wide, covers

$$n = \frac{s}{R\,\theta_{px}}, \qquad \theta_{px} = \frac{\mathrm{HFOV}}{N_x}$$

pixels, with $\theta_{px}$ the angle one pixel covers. Below a handful of
pixels a detector has nothing to work with. Taking $n_{min} = 8$ pixels as that
limit, a camera's reach is

$$R_{max} = \frac{s}{n_{min}\,\theta_{px}} .$$

For a 4K camera ($N_x = 3840$) and a heavy-lift multirotor about 1.2 m across
(the class of the DJI Matrice 600):

| lens (HFOV) | $\theta_{px}$ | reach, 1.2 m drone | reach, 0.35 m drone | picture height | nearest, drone 95 m up, mount 6 m |
|---|---|---|---|---|---|
| 40° | 182 µrad | 0.83 km | 0.24 km | 22.5° | 0.21 km |
| 20° | 91 µrad | 1.65 km | 0.48 km | 11.25° | 0.45 km |
| 16° | 73 µrad | 2.06 km | 0.60 km | 9° | 0.56 km |
| 12° | 55 µrad | 2.75 km | 0.80 km | 6.75° | 0.75 km |

Three consequences, each of which limits what the mode can honestly show:

1. **An ordinary lens gives no early warning.** A 40° lens, common on fixed
   security cameras, reaches 0.83 km. On the site's fence, 0.6 km from the
   centre, that is 1.43 km from the centre: no further than the radar. The four
   wide fence cameras are in the layout to show exactly this.
2. **A longer lens does not widen the view, it moves it.** At its reach every
   lens covers the same strip, $R_{max}\,\mathrm{HFOV} = N_x\,s / n_{min} = 576$ m.
   Distance is bought with angle, so covering an approach needs many long-lens
   cameras or cameras that stand further out.
3. **Reach scales with the size of the drone.** For a 0.35 m camera drone
   every figure is 0.29 of the above: 0.8 km at best. The radar's reach falls
   too, but more slowly (section 9), so for small drones the comparison turns
   round.

The last column is the vertical limit. A 16:9 picture is $9/16$ as tall as it
is wide, and its lower edge is taken to sit on the horizon, so a drone at
height $h$ above a camera mounted at $h_c$ is above the top of the picture
when it is closer than

$$R_{near} = \frac{h - h_c}{\tan(\tfrac{9}{16}\mathrm{HFOV})} .$$

A long lens therefore loses a drone that passes close overhead; the wide ones
keep it. Code: `dronewatch/synthetic/cameras.py`
(`reach_m`, `pixels_on_target`, `FixedCamera.near_m`).

Field results are worse than this optical limit in haze, against a dark
background, at night, or with heavy video compression. None of that is
modelled: inside its reach a camera detects with probability 0.9 per look,
outside it never does.

## 3. Where the cameras stand

Thirty-two 4K cameras at fourteen places round the fictional site. Positions
are metres east and north of the site centre; directions are the centre of
each view with 0° east and 90° north.

| place | position (m) | from centre (km) | cameras | lens at direction | reach (km) |
|---|---|---|---|---|---|
| N FENCE | (0, 600) | 0.6 | 1 | 40° at 90° | 0.83 |
| E FENCE | (600, 0) | 0.6 | 2 | 40° at 0°; 12° at 132° | 0.83, 2.75 |
| S FENCE | (0, -600) | 0.6 | 1 | 40° at 270° | 0.83 |
| W FENCE | (-600, 0) | 0.6 | 2 | 40° at 180°; 12° at 48° | 0.83, 2.75 |
| NW CORNER | (-425, 425) | 0.6 | 6 | 12° at 56°, 68°, 80°, 92°, 104°, 116° | 2.75 |
| NE CORNER | (425, 425) | 0.6 | 6 | 12° at 124°, 112°, 100°, 88°, 76°, 64° | 2.75 |
| N GATE | (0, 1500) | 1.5 | 3 | 12° at 90°; 16° at 125° and 55° | 2.75, 2.06 |
| W MAST | (-1900, 1500) | 2.4 | 3 | 16° at 40° and 65°; 20° at 350° | 2.06, 1.65 |
| E MAST | (1900, 1500) | 2.4 | 3 | 16° at 140° and 115°; 20° at 190° | 2.06, 1.65 |
| PUMP HOUSE | (-600, 1700) | 1.8 | 1 | 20° at 75° | 1.65 |
| DEPOT | (600, 1700) | 1.8 | 1 | 20° at 105° | 1.65 |
| E ROAD | (2000, -200) | 2.0 | 1 | 20° at 0° | 1.65 |
| S LANE | (0, -1500) | 1.5 | 1 | 20° at 270° | 1.65 |
| W ROAD | (-2000, -200) | 2.0 | 1 | 20° at 180° | 1.65 |

The layout has two jobs. The cameras that stand 1.5 to 2.4 km out to the
north see a drone first, 3.1 to 3.3 km from the centre, because they are
already most of the way there. The two fans on the northern corners of the
fence then hold it: they stand 850 m apart and both look up the approach, so a
drone flying in stays inside the same two views for a long time and the pair
works as a rangefinder with an 850 m base.

This is a layout made for the demonstration, not a survey of what a real site
has. Twenty-one of the thirty-two cameras have a 12° or 16° lens, which is a
long lens for a security camera. It was arranged on the demonstration's seed
(42) and the approach from the north; section 10 measures it on seeds it was
not arranged on. The cameras on the roads and the lane watch other approaches
and see nothing in this scenario.

## 4. What a camera reports

Twice a second, for each drone inside its view, reach and picture
(`dronewatch/synthetic/sensors.py`, `observe_entity`):

| quantity | error (one sigma) | where it comes from |
|---|---|---|
| bearing | 0.1° | how well a fixed camera's pointing is known; a pixel is far smaller |
| elevation above the horizon | 0.1° | the same |
| rough range | a factor of about 1.4 either way (0.35 in log terms) | apparent size against an assumed size |

A camera reports no position. Its range is poor and its error does not average
away, because it comes from one unknown, the true size of the drone. The
tracker therefore never estimates with it; it is used only to rule out
pairings that are grossly wrong (section 6). Detection probability is 0.9 per
look and reports arrive 0.3 s late on average.

## 5. Two bearings make a position

Camera $i$ at $c_i$ reports bearing $\beta_i$. Let
$n_i = (-\sin\beta_i, \cos\beta_i)$ be the unit vector across its line of
sight. A point $p$ on that line satisfies $(p - c_i)\cdot n_i = 0$, and a
bearing error $\sigma_i$ moves the line sideways by $d_i\sigma_i$ at distance
$d_i$. The position that best agrees with $N$ bearings minimises

$$\sum_i \frac{\big((p - c_i)\cdot n_i\big)^2}{(d_i\sigma_i)^2} ,$$

which is linear in $p$ once the $d_i$ are fixed:

$$J = \sum_i \frac{n_i n_i^{\mathsf T}}{(d_i\sigma_i)^2}, \qquad
p = J^{-1}\sum_i \frac{n_i n_i^{\mathsf T} c_i}{(d_i\sigma_i)^2}, \qquad
\mathrm{cov}(p) = J^{-1} .$$

Three passes from the crossing of the first two bearings settle the $d_i$
(`crossfix.fit`). A floor of 1.5 m is added to $d_i\sigma_i$ to stand for
what the model leaves out (camera survey error, timing).

The covariance is the geometry. For two cameras at the same distance $d$ whose
lines cross at angle $\gamma$, the position is known to
$d\sigma/(\sqrt2\cos\tfrac{\gamma}{2})$ across the view and
$d\sigma/(\sqrt2\sin\tfrac{\gamma}{2})$ along it: a narrow crossing gives a long
thin region. For the two corner fans, 850 m apart:

| drone at (m) | crossing angle | sigma across the view | sigma along the view |
|---|---|---|---|
| (0, 1400) | 47° | 1.8 m | 4.2 m |
| (0, 2400) | 24° | 2.8 m | 12.9 m |
| (0, 3100) | 18° | 3.6 m | 22.4 m |

The fix goes to the tracker as a position measurement carrying this
covariance, so the Kalman filter weights it correctly in each direction.
Bearings closer to parallel than 12° make no fix. Two lenses on one pole share
a viewpoint and never make one, however many of them see the drone.

Cameras are assumed to report at the same instants. Real cameras do not; a
deployment would have to bring sightings to a common time first.

## 6. Telling true crossings from ghosts

With two drones in view of two cameras there are four crossings, and two of
them are of nothing: one camera's line to the first drone meets the other
camera's line to the second. Four checks keep those out
(`crossfix.pair_cost`, `CrossFixer._resolve`):

1. **Height.** Each camera also measures elevation $\epsilon_i$, so at a
   crossing at distances $d_a$ and $d_b$ the two cameras each imply a height,
   $z_i = h_i + d_i\tan\epsilon_i$. At a true crossing they agree. At a ghost
   the distances are wrong by tens of percent and the heights disagree by
   tens of metres. A pair is accepted only when the heights agree within three
   standard deviations, the variance being

$$\sigma_z^2 = \sigma_0^2 + \sum_{i}\Big[\Big(\frac{d_i\,\sigma_{\epsilon}}{\cos^2\epsilon_i}\Big)^2
  + \Big(\tan\epsilon_i\,\frac{d_j\,\sigma_\beta}{\sin\gamma}\Big)^2\Big], \qquad \sigma_0 = 2\ \mathrm{m},$$

   the second term being the error in each distance that the other camera's
   bearing error causes through the crossing angle.
2. **Reach and rough range.** A crossing further than either camera can see is
   not a pair, and neither is one more than three standard deviations from a
   camera's rough range.
3. **Known objects first.** A sighting that agrees with a track already held
   is given to that track. A new object is made only from sightings that no
   held track is anywhere near. Two sightings that each lie close to some held
   track, but to different tracks, are two known objects seen from two places;
   their crossing is not believed. This is the rule that removed ghost tracks
   in dense groups.
4. **Who else should see it.** A new crossing is checked against every other
   camera that has that spot well inside its view. If one of them reports
   nothing in that direction, the crossing is not believed.

Among the pairings that pass, the one with the least total disagreement is
chosen, each sighting left unpaired costing a fixed amount so that a doubtful
pair is not made merely to use sightings up.

## 7. One camera alone

A sighting that cannot be paired stays a bearing. It can never start a track.
It may refine a track that already exists, but only across the line of sight.

The ordinary Kalman gain for a bearing also moves range and range rate,
through correlations that the linearisation builds up, and over a long spell
with one sensor that makes the range drift: the known weakness of a Cartesian
filter fed bearings alone. In a first version a contact flying along a
camera's view lost two thirds of its estimated closing speed this way. So the
gain is projected onto the direction across the line of sight, for position
and for velocity, before it is applied:

$$n = \frac{(-d_y,\ d_x)}{\lVert d\rVert},\quad d = \hat p^- - c,
\qquad K' = \begin{bmatrix} n n^{\mathsf T} & 0\\ 0 & n n^{\mathsf T}\end{bmatrix} K .$$

The covariance is then updated in Joseph form,
$P^+ = (I - K'H)P^-(I - K'H)^{\mathsf T} + K'RK'^{\mathsf T}$, which is correct
for any gain, so the uncertainty along the line of sight is left exactly as
the prediction made it (`kalman.update_across_sight_line`).

A lone bearing is given to a track only while the track is already placed to
within 80 m across the line of sight. A track that has drifted further than
that is lost, and a bearing must not be allowed to steer it.

## 8. Tracks

- **Custody.** A camera that still has the object keeps its track from going
  stale: the direction is known now even though the range is not. The track is
  shown as predicted, not as freshly positioned, and is not dropped.
- **Duplicates.** With one sensor each object gives one report per scan and
  two tracks cannot both live on it. With cameras and a radar they can, each
  fed by a different one. Two confirmed tracks that stay within 40 m and
  5 m/s of each other for 3 s are taken to be one object and the newer is
  retired (`Tracker._merge_duplicates`; off in every other mode).
- **Height.** The contacts hold their height within 15 m in this mode. The
  vertical wander of the motion model has no limit, and over a run this long
  it would put contacts below the ground (`scenarios.hold_altitude`).

## 9. The radar it is compared with

The radar is at the site centre and sees nothing beyond 1.4 km. That is the
tracking range Echodyne publishes for its short-range EchoGuard radar against
a DJI Matrice 600 (more than 1.4 km; more than 1 km for a Phantom 4)
[[data sheet]](https://www.echodyne.com/media/owckkjvt/echodyne-ts-echoguardsecurity.pdf).
The same company's medium-range EchoShield is listed at more than 6 km against
the Matrice 600 and more than 3 km against the Phantom 4
[[data sheet]](https://www.echodyne.com/media/nvufa2ud/echodyne-ts-echoshield.pdf).

So the comparison only favours the cameras against a short-range radar, or at
a site with none. A medium-range radar sees the same drone further out than
any camera here. It also holds for the large drone only. Radar range falls
with the fourth root of radar cross-section while camera reach falls in
proportion to size, so against a small drone the cameras lose ground faster
than the radar does: the best lens here reaches 0.8 km against a 0.35 m drone,
inside the 1 km the short-range radar is listed at for that class.

What cameras add in every case is what a radar does not give: a picture of
the object. This mode does not use that; the camera-check mode does
([VISO_INTEGRATION.md](VISO_INTEGRATION.md)).

## 10. Results

`python -m experiments.camera_network` runs the mode on eight seeds that were
not run until the layout and the code were finished, and scores it against
ground truth the tracker never sees. Full table and metric definitions:
[results/camera_network.md](results/camera_network.md).

| contacts | runs with one track per contact and no track off its contact | lead of cameras over radar | position RMSE while only cameras hold it | custody, worst track |
|---|---|---|---|---|
| 3 | 8 of 8 | 64.6 to 83.6 s | 5.7 to 7.5 m | 0.99 |
| 6 | 8 of 8 | 67.6 to 81.6 s | 6.0 to 7.1 m | 0.91 |
| 10 | 7 of 8 | 70.6 to 78.6 s | 6.1 to 29.6 m | 0.79 |

- **Lead** is the time between the first position the cameras give and the
  radar's first detection of anything. The first camera fix was 3.07 to
  3.33 km from the centre and the first radar detection 1.37 to 1.40 km.
- **Custody** is, for each track the radar eventually saw, the share of the
  time before that in which the track was freshly positioned by cameras. The
  figure is the worst track of the worst run.
- **The failure:** in one ten-contact run a freshly positioned track sat more
  than 150 m from every true contact for 32 of 4792 track-frames (0.7%).
- On the demonstration's own seed (42), three and six contacts are clean; with
  ten, two contacts pass within about 10 m of each other and a duplicate
  track lives for about 10 s before it is merged.

Seeds 2024, 31337, 99 and 555 were run once on an earlier layout of 28
cameras. With three contacts all four runs had one track per contact, but in
two of them a contact on the flank of the approach was held by one camera only
for a third of its way in. That led to the sixth camera on each corner fan and
the inward-looking camera on each mast, so those seeds are counted as
development seeds and are not in the table.

## 11. Limits

- Synthetic throughout. The detector is a probability, not a model; false
  detections, birds, aircraft and a cluttered skyline are absent.
- A hard reach: 0.9 inside, nothing outside. No haze, contrast, night or
  compression.
- Cameras are assumed surveyed (position and pointing known to 0.1°) and
  synchronised.
- The lower edge of every picture is on the horizon. A real camera sees below
  it too, against ground clutter where detection is harder.
- The layout suits one approach direction and one scenario. Contacts that turn
  away to the sides leave the views and are shown as lost.
- The drone is 1.2 m across. For small drones the cameras see under a third
  as far and the comparison with the radar reverses (section 9).
- Association is still greedy; in dense groups it can swap identities between
  neighbours even when every track is on a real contact.

## 12. Where each piece is tested

All in `tests/test_camera_network.py` unless marked; page functions in
`tests/operator.test.cjs`.

| statement | test |
|---|---|
| reach is the range of 8 pixels on target | `test_reach_is_the_range_at_which_the_drone_still_covers_eight_pixels` |
| the strip at reach is 576 m for every lens | `test_whatever_the_lens_the_strip_a_camera_covers_at_its_reach_is_the_same_width` |
| reach scales with drone size | `test_a_small_camera_drone_is_seen_at_under_a_third_of_the_distance` |
| a wide fence camera sees no further than the radar | `test_an_ordinary_wide_lens_on_the_fence_sees_no_further_than_the_radar` |
| close and high is above the picture | `test_a_drone_that_passes_close_and_high_is_above_the_picture` |
| two views on the approach axis down to the radar | `test_the_northern_approach_is_seen_from_two_places_all_the_way_to_the_radar` |
| a camera reports no position | `test_a_camera_reports_a_direction_an_elevation_and_a_rough_range_and_no_position` |
| the fix and its covariance | `test_a_fix_is_long_along_the_view_and_short_across_it` |
| one pole cannot fix | `test_two_lenses_on_one_pole_cannot_fix_a_position_between_them` |
| height separates true pairs from ghosts | `test_with_two_objects_in_view_height_tells_the_true_pairs_from_the_ghosts` |
| two known objects do not make a third | `test_two_known_objects_seen_from_two_places_do_not_make_a_third` |
| a camera that should see it and does not | `test_a_camera_that_ought_to_see_a_new_object_and_does_not_vetoes_it` |
| one camera never starts a track | `test_one_camera_gives_a_direction_and_two_give_a_position` |
| a bearing moves the estimate across the line only | `test_a_cameras_bearing_moves_the_estimate_across_the_line_of_sight_and_not_along_it` |
| a bearing never steers a lost track | `test_a_lone_bearing_is_matched_to_a_well_placed_track_and_never_to_a_lost_one` |
| in view means coasting, not stale | `test_a_camera_that_still_has_the_object_keeps_its_track_from_going_stale` |
| duplicates merge only when asked | `test_two_tracks_on_one_object_are_merged_only_when_asked_and_the_older_is_kept` |
| every camera-born track is a real contact (seed 42) | `test_every_track_the_cameras_start_is_a_real_contact_and_there_is_one_each` |
| over a minute before the radar (seed 42) | `test_the_cameras_place_the_group_over_a_minute_before_the_radar_sees_it` |
| held all the way in (seed 42) | `test_a_contact_that_reaches_the_radar_was_held_by_cameras_all_the_way_in` |
| other modes untouched | `test_other_modes_are_untouched_by_the_camera_machinery` |
| the counter never shows the future | `the early-warning counter waits, then counts, then holds the lead once the radar has seen something` (node) |
