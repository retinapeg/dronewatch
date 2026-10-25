# DroneWatch: 35-second product demo

Run `./start-demo.sh`, open http://127.0.0.1:8000, and select FULLSCREEN.

1. Select RUN DRONE DEMO. The first three seconds are clear.
2. At 3 seconds, the synthetic sensor detects DRONE at 96% demonstration confidence.
3. At 6 seconds, DW-001 appears on the radar. Position, range, bearing, altitude and speed come from the backend's deterministic coordinates.
4. At 25 seconds, the drone enters the warning boundary.
5. At 30 seconds, the drone enters the restricted zone and raises HIGH.
6. At 35 seconds, the final state holds. RESET clears the demo without touching permanent webhook history.
7. Select AIRCRAFT, then BIRD. Their distinct silhouettes, labels and tracks remain informational, not drone threats.

Say: "DroneWatch connects visual detections to a coherent operational airspace picture. Here a drone is identified, tracked and escalated as it approaches a protected site. Aircraft and birds are distinguished rather than treated as the same security threat. Today's imagery and classifications are simulated; this demonstrates the downstream workflow, not a trained detector."

All assets and state are local. There are no external API requests, media downloads or remote fonts. Hidden OPERATOR CONTROLS can pause, acquire, advance to warning or advance to high. These seek the demonstration timeline and do not represent real detections.
