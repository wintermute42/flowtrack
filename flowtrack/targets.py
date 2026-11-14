"""Extra OSC targets: send the tracking features to other programs besides Resolume.

Each target in `config.yaml` under `targets:` gets, every frame:
  <prefix>/x, /y, /speed, /count, /spread  (floats; x/y 0..1 on the projector image)
  <prefix>/present                        (1 or 0)
  <prefix>/points                         (x1 y1 x2 y2 … of all tracked points, projector 0..1)
and, when a rule fires, <prefix>/rule with the rule's name. The default prefix is /flowtrack.
"""
from pythonosc.udp_client import SimpleUDPClient

FEATURES = ("x", "y", "speed", "count", "spread")


class OscTargets:
    def __init__(self, specs, dry_run=False, log=False):
        self.dry_run = dry_run
        self.log = log
        self.targets = []
        for spec in specs or []:
            host = spec.get("host", "127.0.0.1")
            port = int(spec["port"])
            prefix = "/" + str(spec.get("prefix", "/flowtrack")).strip("/")
            self.targets.append({"client": SimpleUDPClient(host, port), "prefix": prefix,
                                 "points": spec.get("points", True), "name": f"{host}:{port}"})
        for t in self.targets:
            print(f"[targets] sending features to {t['name']} ({t['prefix']}/…)")

    def __bool__(self):
        return bool(self.targets)

    def _send(self, target, address, value):
        if self.log:
            print(f"[targets] {target['name']} {address} {value}")
        if not self.dry_run:
            target["client"].send_message(address, value)

    def send(self, f):
        """Sends one frame of features to every target."""
        for t in self.targets:
            p = t["prefix"]
            for k in FEATURES:
                if k in f:
                    self._send(t, f"{p}/{k}", float(f[k]))
            self._send(t, f"{p}/present", 1 if f.get("present") else 0)
            if t["points"]:
                flat = [float(c) for pt in f.get("blobs", []) for c in pt[:2]]
                self._send(t, f"{p}/points", flat)

    def rule(self, name):
        """Tells every target that a rule fired."""
        for t in self.targets:
            self._send(t, f"{t['prefix']}/rule", str(name))
