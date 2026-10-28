"""Kalibrierung: Der Beamer zeigt vier Markierungen, du ordnest sie im Kamerabild zu.

Pro Markierung entweder ins Kamerabild klicken oder LEERTASTE drücken: Dann wird der hellste
Punkt im Kamerabild genommen. Mit IR-Filter vor der Kamera sieht sie den Beamer nicht. Dann
hältst du eine Taschenlampe oder ein Feuerzeug an die projizierte Markierung und drückst LEERTASTE.
"""
import json

import cv2
import numpy as np

from .source import open_source

TARGETS = [(0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9)]


def projector_window(name, cfg):
    cv2.namedWindow(name, cv2.WINDOW_NORMAL)
    pos = cfg.get("projector_window", {"x": 1920, "y": 0})
    cv2.moveWindow(name, pos["x"], pos["y"])
    cv2.setWindowProperty(name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)


def brightest(frame):
    gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (21, 21), 0)
    _, _, _, loc = cv2.minMaxLoc(gray)
    return loc


def run(cfg, source_spec, out_path):
    W, H = cfg.get("render", {}).get("size", [1280, 720])
    cam = cfg.get("camera", {})
    src = open_source(source_spec, cam.get("width", 1280), cam.get("height", 720), cam.get("fps", 60))
    points = []
    projector_window("projector", cfg)
    cv2.namedWindow("kamera")
    state = {"frame": None}

    def on_click(event, x, y, *_):
        if event == cv2.EVENT_LBUTTONDOWN and len(points) < 4:
            points.append((x, y))

    cv2.setMouseCallback("kamera", on_click)
    while True:
        frame = src.read()
        if frame is None:
            break
        state["frame"] = frame
        i = len(points)
        proj = np.zeros((H, W, 3), np.uint8)
        for k, (tx, ty) in enumerate(TARGETS):
            c = (int(tx * W), int(ty * H))
            active = k == i
            cv2.circle(proj, c, 30 if active else 12, (255, 255, 255) if active else (80, 80, 80), -1)
            cv2.putText(proj, str(k + 1), (c[0] + 40, c[1] + 10), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2)
        cv2.imshow("projector", proj)
        view = frame.copy()
        for k, p in enumerate(points):
            cv2.drawMarker(view, p, (0, 255, 0), cv2.MARKER_CROSS, 30, 2)
            cv2.putText(view, str(k + 1), (p[0] + 10, p[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        msg = f"Markierung {i + 1}: klicken oder LEERTASTE" if i < 4 else "ENTER = speichern, R = neu"
        cv2.putText(view, msg, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2)
        cv2.imshow("kamera", view)
        key = cv2.waitKey(1) & 0xFF
        if key == ord(" ") and i < 4:
            points.append(brightest(frame))
        elif key in (ord("r"), ord("R")):
            points.clear()
        elif key in (13, 10) and len(points) == 4:
            H_ = cv2.getPerspectiveTransform(np.float32(points), np.float32(TARGETS))
            json.dump({"homography": H_.tolist(), "camera_points": points, "targets": TARGETS},
                      open(out_path, "w"), indent=2)
            print(f"Kalibrierung gespeichert: {out_path}")
            break
        elif key in (27, ord("q")):
            print("Abgebrochen, nichts gespeichert")
            break
    src.release()
    cv2.destroyAllWindows()
