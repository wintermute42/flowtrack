"""flowtrack: track fire/props with a camera and drive Resolume (or built-in effects) live.

  python -m flowtrack run        start tracking
  python -m flowtrack calibrate  calibrate camera to projector
  python -m flowtrack discover   list Resolume parameters (for config.yaml)
"""
import argparse
import sys
import time
from pathlib import Path

import cv2
import yaml

from . import calibrate
from .control import Mapper, RuleEngine
from .render import EFFECTS, Renderer, SyphonOut
from .resolume import Resolume
from .source import DemoSource, open_source
from .tracker import Calibration, Tracker


def load_config(path):
    return yaml.safe_load(Path(path).read_text()) or {}


def cmd_discover(cfg, args):
    res = Resolume(cfg.get("resolume", {}))
    try:
        params = res.discover()
    except Exception as e:
        sys.exit(f"Resolume not reachable at {res.base} ({e}).\n"
                 "Is the webserver on? Resolume → Preferences → Webserver → 'Enable Webserver & REST API'.")
    q = (args.filter or "").lower()
    for path, p in params.items():
        if q in path.lower():
            rng = f"  [{p['min']} .. {p['max']}]" if p.get("min") is not None else ""
            print(f"{p['valuetype']:<16} {path}{rng}")


def draw_preview(frame, f, fps, renderer, tracker_cfg):
    view = frame.copy()
    h, w = view.shape[:2]
    if tracker_cfg.get("show_mask"):
        view[f["mask"] > 0] = (0, 0, 255)
    for person in f.get("landmarks", []):  # skeleton from pose detection
        for x, y in person:
            cv2.circle(view, (int(x), int(y)), 3, (255, 200, 0), -1)
    for i, (x, y, a) in enumerate(f["blobs_cam"]):
        cv2.circle(view, (int(x), int(y)), 14, (0, 255, 0) if i == 0 else (0, 180, 255), 2)
    txt = (f"{fps:4.0f} fps  points {f['count']}  x {f['x']:.2f}  y {f['y']:.2f}  "
           f"speed {f['speed']:.2f}  threshold {tracker_cfg.get('threshold')}")
    if renderer:
        txt += f"  effect {renderer.effect}"
    cv2.putText(view, txt, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
    cv2.putText(view, "q quit | 1-4/n effect | +/- threshold | m mask", (10, h - 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
    return view


def cmd_run(cfg, args):
    cam = cfg.get("camera", {})
    tcfg = cfg.get("tracking", {})
    rcfg = dict(cfg.get("resolume", {}))
    if args.dry_run:
        rcfg.update(dry_run=True, log=True)
    src = open_source(args.source or cam.get("source", 0), cam.get("width", 1280), cam.get("height", 720),
                      cam.get("fps", 60), cam.get("exposure"))
    demo = isinstance(src, DemoSource)
    tracker = Tracker(tcfg, Calibration(cfg.get("calibration_file", "calibration.json")))

    res = Resolume(rcfg)
    if rcfg.get("enabled", True) and not args.dry_run:
        try:
            n = len(res.discover())
            print(f"[resolume] read {n} parameters")
            res.connect_ws()
        except Exception as e:
            print(f"[resolume] REST not reachable ({e}); skipping 'param:' mappings, OSC still works")

    rend_cfg = cfg.get("render", {})
    renderer = Renderer(rend_cfg) if rend_cfg.get("enabled", False) or args.render else None
    mapper = Mapper(cfg.get("outputs"), res)
    rules = RuleEngine(cfg.get("rules"), res, renderer)

    syphon = None
    if renderer and rend_cfg.get("syphon", True) and not args.headless:
        try:
            syphon = SyphonOut(rend_cfg.get("syphon_name", "flowtrack"))
            print("[syphon] server 'flowtrack' running, select it in Resolume under Sources → Syphon")
        except Exception as e:
            print(f"[syphon] not available ({e})")
    show_out = renderer and rend_cfg.get("window", True) and not args.headless
    if show_out:
        calibrate.projector_window("output", cfg)

    fps, last, n = 0.0, time.time(), 0
    target_dt = 1.0 / cam.get("fps", 60)
    while True:
        t_frame = time.time()
        frame = src.read()
        if frame is None:
            break
        now = src.n / src.fps if demo else time.time()
        f = tracker.update(frame, now)
        mapper.apply(f)
        rules.step(f, now)
        if renderer:
            out = renderer.frame(f, 1.0 / cam.get("fps", 60) if demo else max(time.time() - last, 1e-3))
            if syphon:
                syphon.send(out)
            if show_out:
                cv2.imshow("output", out)
        nowr = time.time()
        fps = 0.9 * fps + 0.1 / max(nowr - last, 1e-3)
        last = nowr
        n += 1
        if args.frames and n >= args.frames:
            break
        if args.headless:
            if args.verbose and n % 30 == 0:
                print(f"frame {n}: present={f['present']} count={f['count']} x={f['x']:.3f} y={f['y']:.3f} speed={f['speed']:.2f}")
            continue
        cv2.imshow("camera", draw_preview(frame, f, fps, renderer, tcfg))
        if demo:  # play the demo in real time
            time.sleep(max(0.0, target_dt - (time.time() - t_frame)))
        key = cv2.waitKey(1) & 0xFF
        if key in (27, ord("q")):
            break
        elif renderer and ord("1") <= key < ord("1") + len(EFFECTS):
            renderer.set_effect(EFFECTS[key - ord("1")])
        elif renderer and key == ord("n"):
            renderer.set_effect("next")
        elif key in (ord("+"), ord("=")):
            tcfg["threshold"] = min(255, tcfg.get("threshold", 200) + 5)
        elif key == ord("-"):
            tcfg["threshold"] = max(0, tcfg.get("threshold", 200) - 5)
        elif key == ord("m"):
            tcfg["show_mask"] = not tcfg.get("show_mask")
    src.release()
    tracker.close()
    if syphon:
        syphon.close()
    if not args.headless:
        cv2.destroyAllWindows()
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(prog="flowtrack")
    ap.add_argument("command", choices=["run", "calibrate", "discover"])
    ap.add_argument("-c", "--config", default="config.yaml")
    ap.add_argument("-s", "--source", help="camera number (0, 1, …), video file, 'demo' or 'demo-color'")
    ap.add_argument("--render", action="store_true", help="enable built-in effects")
    ap.add_argument("--dry-run", action="store_true", help="send nothing to Resolume, only print")
    ap.add_argument("--headless", action="store_true", help="no windows (testing)")
    ap.add_argument("--frames", type=int, help="stop after N frames (testing)")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--filter", help="discover: only paths containing this text")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    if args.command == "discover":
        cmd_discover(cfg, args)
    elif args.command == "calibrate":
        calibrate.run(cfg, args.source or cfg.get("camera", {}).get("source", 0),
                      cfg.get("calibration_file", "calibration.json"))
    else:
        cmd_run(cfg, args)


if __name__ == "__main__":
    main()
