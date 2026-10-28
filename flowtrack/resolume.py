"""Anbindung an Resolume: OSC für schnelle Live-Werte, REST zum Auslesen der Komposition,
WebSocket zum Setzen von Parametern über ihre ID (ohne OSC-Adressen abtippen zu müssen)."""
import json
import threading
import time

import requests
from pythonosc.udp_client import SimpleUDPClient

LIST_KEYS_BY_NAME = {"effects"}  # Listen, deren Einträge über ihren Namen statt über die Nummer adressiert werden


def _name(node):
    n = node.get("name") if isinstance(node, dict) else None
    if isinstance(n, dict):
        n = n.get("value")
    return n


def walk_params(node, path=()):
    """Durchläuft das Kompositions-JSON und liefert (pfad, parameter-dict) für jeden Parameter."""
    if isinstance(node, dict):
        if "id" in node and "valuetype" in node:
            yield "/".join(path), node
            return
        for k, v in node.items():
            yield from walk_params(v, path + (str(k),))
    elif isinstance(node, list):
        seen = {}
        for i, item in enumerate(node):
            seg = str(i + 1)
            if path and path[-1] in LIST_KEYS_BY_NAME and _name(item):
                seg = _name(item)
                seen[seg] = seen.get(seg, 0) + 1
                if seen[seg] > 1:
                    seg = f"{seg}#{seen[seg]}"
            yield from walk_params(item, path + (seg,))


class Resolume:
    def __init__(self, cfg):
        self.host = cfg.get("host", "127.0.0.1")
        self.osc = SimpleUDPClient(self.host, cfg.get("osc_port", 7000))
        self.base = f"http://{self.host}:{cfg.get('http_port', 8080)}/api/v1"
        self.ws_url = f"ws://{self.host}:{cfg.get('ws_port', cfg.get('http_port', 8080))}/api/v1"
        self.params = {}  # pfad -> {id, min, max, valuetype}
        self.ws = None
        self._ws_lock = threading.Lock()
        self._rest_last = {}
        self.dry_run = cfg.get("dry_run", False)
        self.log = cfg.get("log", False)

    # ---------- REST ----------
    def discover(self, timeout=2.0):
        r = requests.get(f"{self.base}/composition", timeout=timeout)
        r.raise_for_status()
        self.params = {}
        for path, p in walk_params(r.json(), ("composition",)):
            self.params[path] = {"id": p["id"], "valuetype": p.get("valuetype"),
                                 "min": p.get("min"), "max": p.get("max"), "value": p.get("value")}
        return self.params

    def find(self, query):
        """Exakter Pfad oder eindeutige Teilzeichenkette (Groß-/Kleinschreibung egal)."""
        if query in self.params:
            return query
        q = query.lower()
        hits = [p for p in self.params if q in p.lower()]
        if len(hits) == 1:
            return hits[0]
        if not hits:
            raise KeyError(f"Kein Resolume-Parameter passt zu '{query}'")
        raise KeyError(f"'{query}' ist mehrdeutig: {hits[:5]}")

    # ---------- WebSocket ----------
    def connect_ws(self):
        try:
            import websocket  # websocket-client
            self.ws = websocket.create_connection(self.ws_url, timeout=2)
            # Resolume schickt beim Verbinden den Zustand; den lesen wir im Hintergrund weg.
            threading.Thread(target=self._drain, daemon=True).start()
            return True
        except Exception as e:
            print(f"[resolume] WebSocket nicht verfügbar ({e}), nutze REST als Ersatz")
            self.ws = None
            return False

    def _drain(self):
        while self.ws:
            try:
                self.ws.recv()
            except Exception:
                time.sleep(0.5)

    # ---------- Setzen ----------
    def send_osc(self, address, value):
        if self.log:
            print(f"[osc] {address} {value}")
        if not self.dry_run:
            self.osc.send_message(address, value)

    def set_param(self, path, value, normalized=True):
        p = self.params[path]
        if normalized and p.get("min") is not None and p.get("max") is not None:
            value = p["min"] + value * (p["max"] - p["min"])
        if self.log:
            print(f"[param] {path} = {value}")
        if self.dry_run:
            return
        msg = {"action": "set", "parameter": f"/parameter/by-id/{p['id']}", "value": value}
        if self.ws:
            try:
                with self._ws_lock:
                    self.ws.send(json.dumps(msg))
                return
            except Exception:
                self.ws = None
        # REST-Ersatz, auf ~20 Updates/s je Parameter begrenzt
        now = time.time()
        if now - self._rest_last.get(path, 0) < 0.05:
            return
        self._rest_last[path] = now
        try:
            requests.put(f"{self.base}/parameter/by-id/{p['id']}", json={"value": value}, timeout=0.2)
        except requests.RequestException:
            pass

    def trigger_clip(self, layer, clip):
        self.send_osc(f"/composition/layers/{layer}/clips/{clip}/connect", 1)
