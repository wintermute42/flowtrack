"""Körper-Erkennung mit MediaPipe (KI): liefert Handgelenke, Hände, Kopf oder Körpermitte als Punkte.
Funktioniert mit jeder normalen Kamera und lässt sich von Projektion weniger stören als die Helligkeitserkennung."""
import urllib.request
from pathlib import Path

import cv2

MODELS = {
    "lite": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task",
    "full": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task",
}

# Namen -> MediaPipe-Landmarken. Mehrere Indizes werden gemittelt.
POINTS = {
    "nose": [0],
    "left_wrist": [15], "right_wrist": [16],
    "left_hand": [15, 17, 19, 21], "right_hand": [16, 18, 20, 22],
    "left_elbow": [13], "right_elbow": [14],
    "left_foot": [27, 29, 31], "right_foot": [28, 30, 32],
    "center": [11, 12, 23, 24],  # Mitte aus Schultern und Hüften
}


def model_path(variant):
    path = Path(__file__).resolve().parent.parent / "models" / f"pose_landmarker_{variant}.task"
    if not path.exists():
        path.parent.mkdir(exist_ok=True)
        print(f"[pose] lade KI-Modell '{variant}' herunter (einmalig) …")
        urllib.request.urlretrieve(MODELS[variant], path)
    return path


class PoseDetector:
    def __init__(self, cfg):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision
        self.mp = mp
        self.points = cfg.get("pose_points", ["right_hand", "left_hand"])
        unknown = [p for p in self.points if p not in POINTS]
        if unknown:
            raise ValueError(f"Unbekannte pose_points {unknown}; möglich: {sorted(POINTS)}")
        self.min_vis = cfg.get("pose_min_visibility", 0.5)
        opts = vision.PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path(cfg.get("pose_model", "lite")))),
            running_mode=vision.RunningMode.VIDEO,
            num_poses=cfg.get("pose_people", 1),
        )
        self.landmarker = vision.PoseLandmarker.create_from_options(opts)
        self.last_ts = -1
        self.landmarks = []  # für die Vorschau

    def detect(self, frame, now):
        h, w = frame.shape[:2]
        ts = max(int(now * 1000), self.last_ts + 1)  # MediaPipe verlangt steigende Zeitstempel
        self.last_ts = ts
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = self.landmarker.detect_for_video(self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb), ts)
        blobs = []
        self.landmarks = []
        for person in result.pose_landmarks:
            self.landmarks.append([(lm.x * w, lm.y * h) for lm in person])
            for rank, name in enumerate(self.points):
                lms = [person[i] for i in POINTS[name]]
                vis = min(getattr(lm, "visibility", 1.0) or 0.0 for lm in lms)
                if vis < self.min_vis:
                    continue
                x = sum(lm.x for lm in lms) / len(lms) * w
                y = sum(lm.y for lm in lms) / len(lms) * h
                # "Fläche" = Rang, damit der zuerst genannte Punkt der Hauptpunkt bleibt
                blobs.append((x, y, float(len(self.points) - rank)))
        blobs.sort(key=lambda b: -b[2])
        return blobs
