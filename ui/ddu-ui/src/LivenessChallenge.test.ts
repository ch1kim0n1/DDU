/**
 * Regression tests for the head-turn geometry.
 *
 * These exist because of a specific failure: the turn comparison was inverted,
 * so "slowly turn your head left" never registered. People turned further and
 * further, their face left the frame, MediaPipe threw, and the render loop —
 * which scheduled its next frame *after* the detect call — died. The visible
 * symptom was "the camera breaks when I turn left".
 *
 * A fake camera device cannot catch this, since a synthetic feed has no face.
 * So the direction is pinned here instead.
 */

import {describe, expect, it} from "vitest";

import {isTurned, yawRatio} from "./LivenessChallenge";

/**
 * Landmarks in the RAW feed, not the mirrored preview. Only the three indices
 * the yaw uses need to be real: 33 right eye corner, 263 left eye corner, 1 nose.
 */
function face(noseX: number, {eyeR = 0.4, eyeL = 0.6} = {}) {
  const points = Array.from({length: 468}, () => ({x: 0, y: 0.5, z: 0}));
  points[33] = {x: eyeR, y: 0.45, z: 0};
  points[263] = {x: eyeL, y: 0.45, z: 0};
  points[1] = {x: noseX, y: 0.5, z: 0};
  return points;
}

describe("yawRatio", () => {
  it("reads ~0.5 looking straight ahead", () => {
    expect(yawRatio(face(0.5))).toBeCloseTo(0.5, 5);
  });

  it("is invariant to where the head sits in frame", () => {
    // Same pose, shifted right across the frame: the ratio must not move, or a
    // user standing off-centre would trip the threshold without turning at all.
    const centred = yawRatio(face(0.5, {eyeR: 0.4, eyeL: 0.6}));
    const offset = yawRatio(face(0.75, {eyeR: 0.65, eyeL: 0.85}));
    expect(offset).toBeCloseTo(centred!, 5);
  });

  it("is invariant to distance from the camera", () => {
    const near = yawRatio(face(0.5, {eyeR: 0.25, eyeL: 0.75}));
    const far = yawRatio(face(0.5, {eyeR: 0.45, eyeL: 0.55}));
    expect(far).toBeCloseTo(near!, 5);
  });

  it("returns null when a required landmark is missing", () => {
    expect(yawRatio([])).toBeNull();
  });

  it("returns null when the eyes coincide, rather than dividing by ~zero", () => {
    expect(yawRatio(face(0.5, {eyeR: 0.5, eyeL: 0.5}))).toBeNull();
  });
});

describe("isTurned", () => {
  it("accepts a left turn — nose toward +x in the raw feed", () => {
    // This is the assertion the old code got backwards.
    const ratio = yawRatio(face(0.58))!;
    expect(ratio).toBeGreaterThan(0.62);
    expect(isTurned("turn_left", ratio)).toBe(true);
  });

  it("accepts a right turn — nose toward -x", () => {
    const ratio = yawRatio(face(0.42))!;
    expect(ratio).toBeLessThan(0.38);
    expect(isTurned("turn_right", ratio)).toBe(true);
  });

  it("does not accept a left turn as a right turn, or the reverse", () => {
    const left = yawRatio(face(0.58))!;
    const right = yawRatio(face(0.42))!;
    expect(isTurned("turn_right", left)).toBe(false);
    expect(isTurned("turn_left", right)).toBe(false);
  });

  it("stays neutral looking straight ahead", () => {
    const ratio = yawRatio(face(0.5))!;
    expect(isTurned("turn_left", ratio)).toBe(false);
    expect(isTurned("turn_right", ratio)).toBe(false);
  });

  it("ignores a small head tilt so the hold does not trigger accidentally", () => {
    const slight = yawRatio(face(0.52))!;
    expect(isTurned("turn_left", slight)).toBe(false);
  });
});
