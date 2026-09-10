/* Deterministic fixture producer. Positions use a schematic unit square, never geography. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.DroneWatchScenario = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const DURATION = 90;
  const fixtures = [
    { id: 'DW-01', start: [.75, .19], end: [.59, .32], status: 'THREAT', confidence: .87, priority: 1, direction: 'South-west', reason: 'Inbound path approaches the protected area.', alternative: 'The same path could represent an authorised aircraft. Intent is not established.' },
    { id: 'DW-02', start: [.23, .28], end: [.36, .36], status: 'POSSIBLE THREAT', confidence: .71, priority: 2, direction: 'South-east', reason: 'A second inbound track requires review.', alternative: 'An approaching course alone does not establish hostile intent.' },
    { id: 'DW-03', start: [.82, .65], end: [.73, .58], status: 'TRACKED', confidence: .92, priority: 4, direction: 'North-west', reason: 'Track remains outside the protected area.', alternative: 'No identity or intent can be verified from this demonstration.' },
    { id: 'DW-04', start: [.39, .83], end: [.41, .74], status: 'UNKNOWN', confidence: .42, priority: 3, direction: 'North', reason: 'Limited identification evidence. Keep under observation.', alternative: 'Unknown means insufficient evidence, not a threat classification.' },
    { id: 'DW-05', start: [.15, .58], end: [.21, .66], status: 'TRACKED', confidence: .89, priority: 5, direction: 'South-east', reason: 'Track is passing outside the protected area.', alternative: 'Its scripted steady course does not imply a decoy or benign intent.' },
    { id: 'DW-06', start: [.47, .13], end: [.48, .20], status: 'UNKNOWN', confidence: .46, priority: 6, direction: 'South', reason: 'Additional demonstration track awaiting review.', alternative: 'No verified identity is available.' },
    { id: 'DW-07', start: [.87, .39], end: [.81, .39], status: 'TRACKED', confidence: .82, priority: 7, direction: 'West', reason: 'Track remains outside the protected area.', alternative: 'An observed course does not establish intent.' },
    { id: 'DW-08', start: [.71, .85], end: [.66, .81], status: 'TRACKED', confidence: .78, priority: 8, direction: 'North-west', reason: 'Additional perimeter observation.', alternative: 'No real sensor evidence supports this fixture.' },
    { id: 'DW-09', start: [.14, .81], end: [.18, .85], status: 'TRACKED', confidence: .85, priority: 9, direction: 'South-east', reason: 'Track is moving away from the protected area.', alternative: 'A departing course is not proof of identity.' },
    { id: 'DW-10', start: [.11, .12], end: [.15, .16], status: 'UNKNOWN', confidence: .39, priority: 10, direction: 'South-east', reason: 'Low-confidence demonstration observation.', alternative: 'Limited evidence leaves several interpretations open.' }
  ];
  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const pointAt = (fixture, seconds) => {
    const t = clamp(seconds, 0, DURATION) / DURATION;
    return { x: fixture.start[0] + (fixture.end[0] - fixture.start[0]) * t, y: fixture.start[1] + (fixture.end[1] - fixture.start[1]) * t, coordinate_system: 'synthetic_schematic' };
  };
  function snapshot(seconds = 0, count = 5) {
    const time = finite(seconds) ? clamp(seconds, 0, DURATION) : 0;
    const size = finite(count) ? clamp(Math.floor(count), 0, 10) : 5;
    return fixtures.slice(0, size).map(fixture => ({
      target_id: fixture.id, event_id: `scenario-01:${fixture.id}:${Math.floor(time)}`,
      source_kind: 'SYNTHETIC_EVENT', source: 'Local deterministic scenario 01',
      synthetic: true, status_basis: 'scenario_authored', status: fixture.status,
      confidence: fixture.confidence, confidence_basis: 'illustrative',
      position: pointAt(fixture, time), velocity: null, heading: null,
      updated_at: new Date(Date.UTC(2026, 0, 1) + time * 1000).toISOString(),
      scenario_seconds: time, priority: fixture.priority, direction: fixture.direction,
      reason: fixture.reason, alternative_interpretation: fixture.alternative,
      uncertainty: 'All positions, priorities and confidence values are authored demonstration fixtures. No real detection, intent inference or classifier is running.',
      evidence: ['Scripted inbound/perimeter course', 'Illustrative confidence only; no classifier'],
      history: [30, 20, 10, 0].filter(age => time >= age).map(age => pointAt(fixture, time - age)),
      predicted_path: [pointAt(fixture, time), pointAt(fixture, DURATION)],
      course_degrees: Math.atan2(fixture.end[0] - fixture.start[0], -(fixture.end[1] - fixture.start[1])) * 180 / Math.PI
    })).sort((a, b) => a.priority - b.priority);
  }
  function isSensorRecord(record) {
    return record && typeof record === 'object' && !Array.isArray(record) &&
      typeof record.target_id === 'string' && record.target_id.length > 0 && record.target_id.length <= 256 &&
      ['SENSOR_EVENT', 'SYNTHETIC_EVENT', 'WEBHOOK_EVENT', 'TEST_EVENT'].includes(record.source_kind) &&
      ['THREAT', 'POSSIBLE THREAT', 'TRACKED', 'UNKNOWN'].includes(record.status) &&
      (record.confidence === null || (finite(record.confidence) && record.confidence >= 0 && record.confidence <= 1)) &&
      typeof record.updated_at === 'string';
  }
  function normalizeSensorPayload(payload) {
    if (!payload || payload.schema_version !== 1 || !Array.isArray(payload.targets)) throw new Error('Unsupported sensor response');
    if (payload.targets.length > 1000) throw new Error('Sensor response exceeds display limit');
    if (payload.targets.some(record => !isSensorRecord(record))) throw new Error('Malformed sensor record');
    const seen = new Set();
    return payload.targets.filter(record => {
      const key = `${record.source_kind}:${typeof record.source === 'string' ? record.source : 'Unspecified source'}:${record.target_id}`;
      if (seen.has(key)) return false;
      seen.add(key); return true;
    }).map(record => ({ ...record, source: typeof record.source === 'string' ? record.source : 'Unspecified source', evidence: Array.isArray(record.evidence) ? record.evidence.filter(item => typeof item === 'string').slice(0, 20) : [], position: record.position && finite(record.position.x) && finite(record.position.y) && record.position.x >= 0 && record.position.x <= 1 && record.position.y >= 0 && record.position.y <= 1 && record.position.coordinate_system === 'normalized_frame' ? record.position : null }));
  }
  function freshness(timestamp, now = Date.now()) {
    const age = now - Date.parse(timestamp);
    if (!Number.isFinite(age) || age < -5000) return { fresh: false, label: 'Timestamp unverified' };
    if (age > 120000) return { fresh: false, label: 'Stale observation' };
    return { fresh: true, label: 'Recent observation' };
  }
  return { DURATION, snapshot, normalizeSensorPayload, freshness };
});
