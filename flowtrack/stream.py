"""Local image stream for other programs (e.g. an AI visualisation that dreams on top of the trails).

With `stream: {enabled: true}` in config.yaml, flowtrack serves on http://127.0.0.1:8090 (by default):
  /frame.jpg     the latest image as JPEG
  /stream.mjpg   a continuous MJPEG stream
Source: "render" (the built-in effect, e.g. trails; falls back to the camera without --render),
"camera" (the camera image) or "mask" (only the detected bright/coloured parts of the camera image).
"""
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2


class FrameStream:
    def __init__(self, cfg):
        self.source = cfg.get("source", "render")
        self.size = int(cfg.get("size", 512))
        self.fps = float(cfg.get("fps", 15))
        self.quality = int(cfg.get("quality", 80))
        self.jpeg = None
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
        if ok:
            with self.cond:
                self.jpeg = buf.tobytes()
                self.cond.notify_all()

    def _handler(self):
        stream = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # keep the console quiet
                pass

            def do_GET(self):
                if self.path.startswith("/frame.jpg"):
                    data = stream.jpeg
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
