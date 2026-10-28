"""Eigene Effekte ohne Resolume. Ausgabe als Vollbild auf dem Beamer und/oder per Syphon an Resolume."""

import cv2
import numpy as np

EFFECTS = ["trails", "ripples", "particles", "kaleido"]


class Renderer:
    def __init__(self, cfg):
        self.W, self.H = cfg.get("size", [1280, 720])
        self.s = cfg.get("internal_scale", 0.5)  # intern in halber Auflösung rechnen, spart CPU
        self.w, self.h = int(self.W * self.s), int(self.H * self.s)
        self.color = np.array(cfg.get("color", [40, 140, 255]), np.float32) / 255.0  # BGR, Feuer-Orange
        self.color2 = np.array(cfg.get("color2", [255, 120, 30]), np.float32) / 255.0  # BGR, Blau
        self.decay = cfg.get("decay", 0.90)
        self.effect = cfg.get("effect", "trails")
        self.buf = np.zeros((self.h, self.w, 3), np.float32)
        self.ripples = []
        self.parts = np.zeros((0, 5), np.float32)  # x, y, vx, vy, leben
        self.t = 0.0

    def set_effect(self, name):
        if name == "next":
            name = EFFECTS[(EFFECTS.index(self.effect) + 1) % len(EFFECTS)]
        if name in EFFECTS:
            self.effect = name
            print(f"[effekt] {name}")

    def _px(self, x, y):
        return int(x * self.w), int(y * self.h)

    def frame(self, f, dt=1 / 60):
        self.t += dt
        self.buf *= self.decay
        energy = min(f["speed"] / 1.5, 1.0)
        blobs = f["blobs"] if f["present"] else []

        if self.effect in ("trails", "kaleido"):
            for x, y, _ in blobs:
                r = int(6 + 18 * energy)
                cv2.circle(self.buf, self._px(x, y), r, (self.color * (0.6 + 0.6 * energy)).tolist(), -1, cv2.LINE_AA)
        elif self.effect == "ripples":
            gap = 0.6 - 0.45 * energy  # schneller = dichtere Wellen
            if f["present"] and (not self.ripples or self.ripples[-1][2] > gap):
                self.ripples.append([f["x"], f["y"], 0.0])
            keep = []
            rings = np.zeros_like(self.buf)  # Ringe jedes Bild neu zeichnen, sonst verschmieren sie
            for rp in self.ripples:
                rp[2] += dt
                rad = int(rp[2] * self.w * 0.35)
                a = max(0.0, 1.0 - rp[2] / 1.6)
                if a > 0:
                    cv2.circle(rings, self._px(rp[0], rp[1]), rad, (self.color2 * a).tolist(), 3, cv2.LINE_AA)
                    keep.append(rp)
            self.ripples = keep[-40:]
            overlay = rings
            for x, y, _ in blobs:
                cv2.circle(self.buf, self._px(x, y), 5, self.color2.tolist(), -1, cv2.LINE_AA)
        elif self.effect == "particles":
            n = int(4 + 40 * energy) if blobs else 0
            if n:
                bx = np.array([b[0] for b in blobs]); by = np.array([b[1] for b in blobs])
                k = np.random.randint(0, len(blobs), n)
                ang = np.random.uniform(0, 2 * np.pi, n); sp = np.random.uniform(0.05, 0.3, n) * (0.5 + energy)
                new = np.stack([bx[k], by[k], np.cos(ang) * sp, np.sin(ang) * sp - 0.15, np.random.uniform(0.6, 1.4, n)], 1)
                self.parts = np.concatenate([self.parts, new.astype(np.float32)])[-3000:]
            if len(self.parts):
                p = self.parts
                p[:, 3] -= 0.25 * dt  # Funken steigen auf wie Feuer
                p[:, 0] += p[:, 2] * dt; p[:, 1] += p[:, 3] * dt; p[:, 4] -= dt
                inside = (p[:, 4] > 0) & (p[:, 0] >= 0) & (p[:, 0] < 1) & (p[:, 1] >= 0) & (p[:, 1] < 1)
                self.parts = p = p[inside]
                xs = (p[:, 0] * self.w).astype(int)
                ys = (p[:, 1] * self.h).astype(int)
                np.add.at(self.buf, (ys, xs), self.color * np.minimum(p[:, 4:5], 1.0) * 1.5)

        img = self.buf if self.effect != "ripples" else np.maximum(self.buf, overlay)
        glow = cv2.GaussianBlur(img, (0, 0), 6)
        img = np.clip(img + glow * 1.5, 0, 1)
        if self.effect == "kaleido":
            img = np.maximum.reduce([img, img[:, ::-1], img[::-1, :], img[::-1, ::-1]])
        out = (img * 255).astype(np.uint8)
        return cv2.resize(out, (self.W, self.H), interpolation=cv2.INTER_LINEAR)


class SyphonOut:
    """Schickt das Bild per Syphon an Resolume (nur macOS, braucht 'syphon-python')."""

    def __init__(self, name="flowtrack"):
        import syphon
        from syphon.utils.raw import create_mtl_texture
        from syphon.utils.numpy import copy_image_to_mtl_texture
        self._copy = copy_image_to_mtl_texture
        self._create = create_mtl_texture
        self.server = syphon.SyphonMetalServer(name)
        self.tex = None

    def send(self, bgr):
        h, w = bgr.shape[:2]
        if self.tex is None:
            self.tex = self._create(self.server.device, w, h)
        rgba = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGBA)
        self._copy(rgba, self.tex)
        self.server.publish_frame_texture(self.tex)

    def close(self):
        self.server.stop()
