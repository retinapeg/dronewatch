(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.StageCore = factory();
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  function project(x, y, maximum = 2500) { return {x: 500 + x / maximum * 415, y: 500 - y / maximum * 415}; }
  function geometry(x, y, z) { return {range_m: Math.hypot(x, y), bearing_deg: x || y ? (Math.atan2(x, y) * 180 / Math.PI + 360) % 360 : null, altitude_m: z}; }
  function interpolate(from, to, progress) {
    if (!from || !to || from.track_id !== to.track_id) return to;
    const p = Math.max(0, Math.min(1, progress));
    const x = from.x + (to.x - from.x) * p, y = from.y + (to.y - from.y) * p, z = from.z + (to.z - from.z) * p;
    return {...to, x, y, z, ...geometry(x, y, z)};
  }
  return {project, geometry, interpolate};
});
