# DroneWatch: one-minute stage demo

Start with `./start-demo.sh`, open http://127.0.0.1:8000, select FULLSCREEN, then RUN DEMO.

- 0-3 seconds: "DroneWatch is a common airspace-awareness layer for protecting critical infrastructure. Today's aircraft and sensor observations are simulated."
- 3-20 seconds: "The EO sensor detects a UAS approaching from the north-east. DroneWatch establishes DW-001 and derives range, bearing, altitude and speed from its position and velocity."
- 20-29 seconds: "The aircraft has entered the warning zone."
- 29-37 seconds: "The sensor feed is lost. We do not invent measurements. The track coasts from its last measured state, with increasing uncertainty."
- 37-42 seconds: "The returning observation passes a position-consistency gate, so DW-001 retains its identity."
- 42-52 seconds: "The drone breaches the protected boundary, raising a high-priority alert."
- 52 seconds onward: Final state holds. "Real EO/IR, radar, RF, acoustic or Remote ID observations can later enter through this same observation interface."

Ten seconds: "DroneWatch turns drone detections into a resilient operational track. It keeps estimating through sensor loss, exposes uncertainty, reacquires the contact and alerts when protected airspace is breached."

Recovery: RESET clears everything; RUN DEMO starts a fresh deterministic run. PAUSE toggles pause/resume. OPERATOR CONTROLS exposes DETECT, DROP SENSOR, REACQUIRE and TRIGGER HIGH. These explicitly seek the scenario timeline, not real-world events. Space runs/pauses; R resets when a button is not focused.

Technical honesty: all scene content is synthetic. During the 29-37 second dropout the API returns no current observation. Prediction uses the two last pre-dropout observations to estimate constant velocity; association checks Euclidean residual against a 150 m gate without using a hidden object ID. The uncertainty radius is an illustrative 20 m + 22 m/s of loss, not a calibrated confidence interval. Stage events stay in memory and never modify the permanent Viso history.
