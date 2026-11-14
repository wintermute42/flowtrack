"""Local image stream for other programs (e.g. an AI visualisation that dreams on top of the trails).

With `stream: {enabled: true}` in config.yaml, flowtrack serves on http://127.0.0.1:8090 (by default):
  /frame.jpg     the latest image as JPEG
  /stream.mjpg   a continuous MJPEG stream
  /pose.jpg      with `detect: pose`: the body skeleton in OpenPose style (for ControlNet), else 503
Source: "render" (the built-in effect, e.g. trails; falls back to the camera without --render),
"camera" (the camera image) or "mask" (only the detected bright/coloured parts of the camera image).
"""
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np

# OpenPose's 18 body points taken from MediaPipe's 33 ("neck" = middle of the shoulders)
OP_FROM_MP = [0, "neck", 12, 14, 16, 11, 13, 15, 24, 26, 28, 23, 25, 27, 5, 2, 8, 7]
OP_LIMBS = [(1, 2), (1, 5), (2, 3), (3, 4), (5, 6), (6, 7), (1, 8), (8, 9), (9, 10), (1, 11), (11, 12), (12, 13),
            (1, 0), (0, 14), (14, 16), (0, 15), (15, 17)]
OP_COLORS = [(255, 0, 0), (255, 85, 0), (255, 170, 0), (255, 255, 0), (170, 255, 0), (85, 255, 0), (0, 255, 0),
             (0, 255, 85), (0, 255, 170), (0, 255, 255), (0, 170, 255), (0, 85, 255), (0, 0, 255), (85, 0, 255),
             (170, 0, 255), (255, 0, 255), (255, 0, 170), (255, 0, 85)]  # RGB, as in OpenPose


def draw_openpose(landmarks, w, h):
    """Draws MediaPipe landmarks (per person: 33 (x, y) in pixels) as an OpenPose skeleton on black (BGR)."""
    img = np.zeros((h, w, 3), np.uint8)
    thick = max(2, int(round(min(w, h) / 120)))
    for person in landmarks:
        if len(person) < 29:
            continue
        pts = []
        for src in OP_FROM_MP:
            if src == "neck":
                pts.append(((person[11][0] + person[12][0]) / 2, (person[11][1] + person[12][1]) / 2))
            else:
                pts.append(person[src])
        for i, (a, b) in enumerate(OP_LIMBS):
            r, g, bl = OP_COLORS[i]
            cv2.line(img, (int(pts[a][0]), int(pts[a][1])), (int(pts[b][0]), int(pts[b][1])), (bl, g, r), thick * 2,
                     cv2.LINE_AA)
        for i, (x, y) in enumerate(pts):
            r, g, bl = OP_COLORS[i]
            cv2.circle(img, (int(x), int(y)), thick * 2, (bl, g, r), -1, cv2.LINE_AA)
    return img


class FrameStream:
    def __init__(self, cfg):
        self.source = cfg.get("source", "render")
        self.size = int(cfg.get("size", 512))
        self.fps = float(cfg.get("fps", 15))
        self.quality = int(cfg.get("quality", 80))
        self.jpeg = None
        self.pose_jpeg = None
        self.last = 0.0
        self.cond = threading.Condition()
        self.httpd = ThreadingHTTPServer((cfg.get("host", "127.0.0.1"), int(cfg.get("port", 8090))), self._handler())
        self.httpd.daemon_threads = True
        self.host, self.port = self.httpd.server_address[:2]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        print(f"[stream] http://{self.host}:{self.port}/stream.mjpg ({self.source})")

    def pick(self, frame, out, f):
        if self.source == "render" and out is not None:
            return out
        if self.source == "mask" and f.get("mask") is not None and f["mask"].shape[:2] == frame.shape[:2]:
            return cv2.bitwise_and(frame, frame, mask=f["mask"])
        return frame

    def update(self, frame, out, f):
        """Takes the current images; encodes at most `fps` times per second."""
        now = time.time()
        if now - self.last < 1.0 / self.fps:
            return
        self.last = now
        img = self.pick(frame, out, f)
        h, w = img.shape[:2]
        s = self.size / max(h, w)
        small = cv2.resize(img, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, self.quality])
        pose = None
        if f.get("landmarks"):                      # landmarks are in camera pixels
            fh, fw = frame.shape[:2]
            ps = self.size / max(fh, fw)
            skel = cv2.resize(draw_openpose(f["landmarks"], fw, fh), (max(1, int(fw * ps)), max(1, int(fh * ps))),
                              interpolation=cv2.INTER_AREA)
            ok_p, pbuf = cv2.imencode(".jpg", skel, [cv2.IMWRITE_JPEG_QUALITY, 90])
            pose = pbuf.tobytes() if ok_p else None
        if ok:
            with self.cond:
                self.jpeg = buf.tobytes()
                self.pose_jpeg = pose
                self.cond.notify_all()

    def _handler(self):
        stream = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # keep the console quiet
                pass

            def do_GET(self):
                if self.path.startswith("/frame.jpg") or self.path.startswith("/pose.jpg"):
                    data = stream.pose_jpeg if self.path.startswith("/pose.jpg") else stream.jpeg
                    if data is None:
                        self.send_error(503, "no frame yet")
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(data)
                elif self.path.startswith("/stream.mjpg"):
                    self.send_response(200)
                    self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    last = None
                    try:
                        while True:
                            with stream.cond:
                                stream.cond.wait_for(lambda: stream.jpeg is not last, timeout=2.0)
                                data = stream.jpeg
                            if data is None or data is last:
                                continue
                            last = data
                            self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                             + str(len(data)).encode() + b"\r\n\r\n" + data + b"\r\n")
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                else:
                    self.send_error(404)

        return Handler

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
