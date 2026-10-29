"""Image sources: camera, video file or a synthetic demo (testable without a camera)."""
import math
import time

import cv2
import numpy as np


class CameraSource:
    def __init__(self, spec, width=1280, height=720, fps=60, exposure=None):
        index = int(spec) if str(spec).isdigit() else spec
        # On the Mac, AVFoundation is the right backend for USB cameras.
        backend = cv2.CAP_AVFOUNDATION if isinstance(index, int) and hasattr(cv2, "CAP_AVFOUNDATION") else cv2.CAP_ANY
        self.cap = cv2.VideoCapture(index, backend)
        if not self.cap.isOpened():
            raise RuntimeError(f"Cannot open image source '{spec}'")
        if isinstance(index, int):
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            self.cap.set(cv2.CAP_PROP_FPS, fps)
            if exposure is not None:  # not supported by every camera/backend
                self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
                self.cap.set(cv2.CAP_PROP_EXPOSURE, exposure)
        self.loop = not isinstance(index, int)

    def read(self):
        ok, frame = self.cap.read()
        if not ok and self.loop:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self.cap.read()
        return frame if ok else None

    def release(self):
        self.cap.release()


class DemoSource:
    """Simulates an IR camera image: dark background, noise and one or two
    bright points (poi/torches) moving in figure eights and circles."""

    def __init__(self, width=1280, height=720, fps=60, color=False):
        self.w, self.h, self.fps, self.color = width, height, fps, color
        self.t0 = time.time()
        self.n = 0

    def read(self):
        t = self.n / self.fps
        self.n += 1
        frame = np.random.randint(0, 25, (self.h, self.w), np.uint8)
        cx, cy = self.w / 2, self.h / 2
        # performer's body, dimly lit by the IR illuminator
        cv2.ellipse(frame, (int(cx), int(cy + 80)), (60, 200), 0, 0, 360, 70, -1)
        phase = (t % 12) / 12
        points = [(cx + 280 * math.sin(t * 1.3), cy + 160 * math.sin(t * 2.6))]
        if phase > 0.5:  # second half: two poi in a circle
            points = [(cx + 220 * math.cos(t * 4 + k * math.pi), cy - 40 + 220 * math.sin(t * 4 + k * math.pi)) for k in (0, 1)]
        if 0.40 < phase < 0.5:  # short pause without fire
            points = []
        for x, y in points:
            cv2.circle(frame, (int(x), int(y)), 18, 255, -1)
        frame = cv2.GaussianBlur(frame, (0, 0), 3)
        bgr = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        if self.color:  # green LED poi instead of fire
            hot = frame > 120
            bgr[hot] = (40, 230, 60)
        return bgr

    def release(self):
        pass


def open_source(spec, width, height, fps, exposure=None):
    if str(spec) in ("demo", "demo-color"):
        return DemoSource(width, height, fps, color=str(spec) == "demo-color")
    return CameraSource(spec, width, height, fps, exposure)
