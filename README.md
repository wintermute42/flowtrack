# flowtrack

Live tracking of fire, LED poi, coloured props or the performer's body from a camera image, driving
[Resolume Avenue](https://resolume.com) in real time via OSC, the REST/WebSocket API and Syphon.

```
camera ──► detection ──► smoothing ──► calibration ──┬─► OSC (x/y, 60×/s) ─────────► Resolume
                                                      ├─► WebSocket/REST (params) ───► Resolume
                                                      ├─► rules (trigger clips …) ───► Resolume
                                                      └─► own effects ─► projector / Syphon ─► Resolume
```

Status: prototype, not yet tested on real hardware.

## Quick start (macOS)

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 -m flowtrack run --source demo --render --dry-run   # no camera, no Resolume needed
```

Settings live in `config.yaml`. The full user guide (German) is in [docs/guide.de.md](docs/guide.de.md).

## Tests

```bash
python3 -m pip install pytest
python3 -m pytest
```

## License

[MIT](LICENSE)
