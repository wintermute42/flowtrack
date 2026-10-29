"""Detection of bright points (fire, IR reflective tape, LEDs), smoothing and mapping to projector coordinates."""
import json
import math
import time
from pathlib import Path

import cv2
import numpy as np


class OneEuro:
    """One Euro filter: smooths strongly on slow movement, reacts quickly on fast movement."""

    def __init__(self, min_cutoff=1.0, beta=0.02, d_cutoff=1.0):
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.x = self.dx = self.t = None

    @staticmethod
    def _alpha(cutoff, dt):
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, x, t):
        if self.t is None:
            self.x, self.dx, self.t = x, 0.0, t
            return x
        dt = max(t - self.t, 1e-4)
        self.t = t
        dx = (x - self.x) / dt
        a_d = self._alpha(self.d_cutoff, dt)
        self.dx = a_d * dx + (1 - a_d) * self.dx
        cutoff = self.min_cutoff + self.beta * abs(self.dx)
        a = self._alpha(cutoff, dt)
        self.x = a * x + (1 - a) * self.x
        return self.x

    def reset(self):
        self.t = None


class Calibration:
    """Homography from the camera image to normalized projector coordinates (0..1)."""

    def __init__(self, path=None):
        self.H = None
        if path and Path(path).exists():
            data = json.loads(Path(path).read_text())
            self.H = np.array(data["homography"], dtype=np.float64)

    def to_projector(self, x, y, frame_w, frame_h):
        if self.H is None:
            return x / frame_w, y / frame_h
        p = self.H @ np.array([x, y, 1.0])
        return p[0] / p[2], p[1] / p[2]


class Tracker:
    def __init__(self, cfg, calibration):
        self.cfg = cfg
        self.cal = calibration
        fc = cfg.get("filter", {})
        self.fx = OneEuro(fc.get("min_cutoff", 1.0), fc.get("beta", 0.02))
        self.fy = OneEuro(fc.get("min_cutoff", 1.0), fc.get("beta", 0.02))
        self.prev = None
        self.speed = 0.0
        self.vel = (0.0, 0.0)
        self.last_seen = 0.0
        self.mask = None
        self.pose = None
        if cfg.get("detect") == "pose":
            from .pose import PoseDetector
            self.pose = PoseDetector(cfg)
        if cfg.get("mask"):
            self.mask = cv2.imread(cfg["mask"], cv2.IMREAD_GRAYSCALE)

    def detect(self, frame):
        if self.cfg.get("detect", "brightness") == "color":
            # colour range in HSV (OpenCV: H 0..179, S/V 0..255), e.g. for LED poi or coloured balls
            hsv = cv2.cvtColor(cv2.GaussianBlur(frame, (5, 5), 0), cv2.COLOR_BGR2HSV)
            bw = cv2.inRange(hsv, np.array(self.cfg.get("hsv_low", [40, 120, 120])),
                             np.array(self.cfg.get("hsv_high", [85, 255, 255])))
        else:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
            gray = cv2.GaussianBlur(gray, (5, 5), 0)
            _, bw = cv2.threshold(gray, self.cfg.get("threshold", 200), 255, cv2.THRESH_BINARY)
        if self.mask is not None and self.mask.shape == bw.shape:
            bw = cv2.bitwise_and(bw, self.mask)
        bw = cv2.morphologyEx(bw, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        contours, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        blobs = []
        for c in contours:
            area = cv2.contourArea(c)
            if not self.cfg.get("min_area", 20) <= area <= self.cfg.get("max_area", 20000):
                continue
            m = cv2.moments(c)
            if m["m00"] == 0:
                continue
            blobs.append((m["m10"] / m["m00"], m["m01"] / m["m00"], area))
        blobs.sort(key=lambda b: -b[2])
        return blobs[: self.cfg.get("max_blobs", 4)], bw

    def close(self):
        if self.pose:
            self.pose.landmarker.close()

    def update(self, frame, now=None):
        """Returns a dict of features for mappings and rules."""
        now = time.time() if now is None else now
        h, w = frame.shape[:2]
        if self.pose:
            blobs, bw = self.pose.detect(frame, now), np.zeros(frame.shape[:2], np.uint8)
        else:
            blobs, bw = self.detect(frame)
        pts = [self.cal.to_projector(x, y, w, h) + (a,) for x, y, a in blobs]
        f = {"present": bool(pts), "count": len(pts), "blobs": pts, "blobs_cam": blobs, "mask": bw,
             "landmarks": self.pose.landmarks if self.pose else []}
        if pts:
            if self.cfg.get("mode", "largest") == "centroid":
                wts = [1.0 if self.pose else p[2] for p in pts]  # pose: weight all points equally
                x = sum(p[0] * wt for p, wt in zip(pts, wts)) / sum(wts)
                y = sum(p[1] * wt for p, wt in zip(pts, wts)) / sum(wts)
            else:
                x, y = pts[0][0], pts[0][1]
            if now - self.last_seen > 0.5:  # after a longer pause, do not glide from the old point
                self.fx.reset(); self.fy.reset(); self.prev = None
            sx, sy = self.fx(x, now), self.fy(y, now)
            if self.prev is not None:
                dt = max(now - self.prev[2], 1e-3)
                vx, vy = (sx - self.prev[0]) / dt, (sy - self.prev[1]) / dt
                k = self.cfg.get("lead_smoothing", 0.5)
                self.vel = (k * self.vel[0] + (1 - k) * vx, k * self.vel[1] + (1 - k) * vy)
                self.speed = 0.8 * self.speed + 0.2 * math.hypot(vx, vy)
            else:
                self.vel = (0.0, 0.0)
            self.prev = (sx, sy, now)
            self.last_seen = now
            # prediction: shift lead_ms into the future to make up for part of the latency
            lead = self.cfg.get("lead_ms", 0) / 1000.0
            px = min(max(sx + self.vel[0] * lead, -0.2), 1.2)
            py = min(max(sy + self.vel[1] * lead, -0.2), 1.2)
            xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
            f.update(x=px, y=py, spread=math.hypot(max(xs) - min(xs), max(ys) - min(ys)))
        else:
            self.speed *= 0.9
            if self.prev:  # hold last position
                f.update(x=self.prev[0], y=self.prev[1])
            else:
                f.update(x=0.5, y=0.5)
            f["spread"] = 0.0
        f["speed"] = self.speed
        f["absent_for"] = now - self.last_seen if self.last_seen else 1e9
        return f
