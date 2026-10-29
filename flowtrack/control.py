"""Mappings (feature -> Resolume parameter, every frame) and rules (event -> action)."""
import operator
import re
import time

OPS = {">": operator.gt, "<": operator.lt, ">=": operator.ge, "<=": operator.le, "==": operator.eq}
COND_RE = re.compile(r"^\s*(\w+)\s*(>=|<=|==|>|<)\s*([-\d.]+)\s*$")


def scale(v, src, dst, invert=False, clamp=True):
    lo, hi = src
    t = (v - lo) / (hi - lo) if hi != lo else 0.0
    if clamp:
        t = min(max(t, 0.0), 1.0)
    if invert:
        t = 1.0 - t
    return dst[0] + t * (dst[1] - dst[0])


class Mapper:
    def __init__(self, outputs, resolume):
        self.res = resolume
        self.outputs = []
        for o in outputs or []:
            o = dict(o)
            if "param" in o:
                o["_path"] = resolume.find(o["param"]) if resolume.params else None
                if o["_path"] is None:
                    print(f"[mapping] '{o['param']}' skipped: Resolume parameters not read")
                    continue
            self.outputs.append(o)

    def apply(self, f):
        for o in self.outputs:
            if o.get("only_when_present") and not f["present"]:
                continue
            v = scale(f[o["feature"]], o.get("in", [0, 1]), o.get("range", [0, 1]), o.get("invert", False))
            if "osc" in o:
                self.res.send_osc(o["osc"], float(v))
            else:
                self.res.set_param(o["_path"], float(v), normalized=not o.get("raw", False))


class Rule:
    def __init__(self, spec):
        self.spec = spec
        self.when = spec["when"].strip()
        self.hold = spec.get("for", 0.0)
        self.cooldown = spec.get("cooldown", 0.0)
        self.actions = spec["do"] if isinstance(spec["do"], list) else [spec["do"]]
        self.since = None
        self.fired = False
        self.last_fire = -1e9

    def condition(self, f):
        if self.when == "present":
            return f["present"]
        if self.when == "absent":
            return not f["present"]
        m = COND_RE.match(self.when)
        if not m:
            raise ValueError(f"Rule not understood: '{self.when}'")
        return OPS[m.group(2)](f[m.group(1)], float(m.group(3)))

    def step(self, f, now):
        """True when the rule fires at this moment (once each time the condition becomes true)."""
        if not self.condition(f):
            self.since, self.fired = None, False
            return False
        if self.since is None:
            self.since = now
        if not self.fired and now - self.since >= self.hold and now - self.last_fire >= self.cooldown:
            self.fired, self.last_fire = True, now
            return True
        return False


class RuleEngine:
    def __init__(self, specs, resolume, renderer=None):
        self.rules = [Rule(s) for s in specs or []]
        self.res = resolume
        self.renderer = renderer

    def step(self, f, now=None):
        now = time.time() if now is None else now
        for r in self.rules:
            if r.step(f, now):
                print(f"[rule] {r.spec.get('name', r.when)} fired")
                for a in r.actions:
                    self.run(a)

    def run(self, a):
        if "clip" in a:
            self.res.trigger_clip(*a["clip"])
        elif "osc" in a:
            self.res.send_osc(a["osc"], a.get("value", 1))
        elif "param" in a:
            self.res.set_param(self.res.find(a["param"]), a["value"], normalized=not a.get("raw", False))
        elif "effect" in a and self.renderer:
            self.renderer.set_effect(a["effect"])
