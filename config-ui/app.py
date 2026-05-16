"""soundtouch-cloud-revival — configuration UI sidecar.

Discovers SoundTouch speakers on the LAN, lets the user pick six radio
stations from the bundled master list (or a custom URL) and writes the
shared config.yaml that the alinossier/soundtouch-local-presets daemon
consumes. The daemon container is restarted after every save so the new
configuration takes effect immediately.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

import docker
import requests
import yaml
from flask import Flask, jsonify, redirect, render_template, request, url_for
from zeroconf import ServiceBrowser, ServiceListener, Zeroconf

APP_DIR = Path(__file__).parent
CONFIG_PATH = Path(os.environ.get("CONFIG_PATH", "/data/config.yaml"))
STATIONS_PATH = Path(os.environ.get("STATIONS_PATH", APP_DIR / "stations.yaml"))
DAEMON_CONTAINER = os.environ.get("DAEMON_CONTAINER", "soundtouch-presets")
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "8181"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("revival-ui")

app = Flask(__name__)

# --- Zeroconf-based speaker discovery -------------------------------------------------

_speakers_lock = threading.Lock()
_speakers: dict[str, dict] = {}


class SoundTouchListener(ServiceListener):
    def _record(self, zc: Zeroconf, type_: str, name: str) -> None:
        info = zc.get_service_info(type_, name, timeout=2000)
        if not info or not info.addresses:
            return
        ip = ".".join(str(b) for b in info.addresses[0])
        speaker_name = name.split(f".{type_}")[0]
        with _speakers_lock:
            _speakers[speaker_name] = {"ip": ip, "last_seen": time.time()}
        log.info("Discovered %s at %s", speaker_name, ip)

    def add_service(self, zc, type_, name):
        self._record(zc, type_, name)

    def update_service(self, zc, type_, name):
        self._record(zc, type_, name)

    def remove_service(self, zc, type_, name):
        speaker_name = name.split(f".{type_}")[0]
        with _speakers_lock:
            _speakers.pop(speaker_name, None)


def start_discovery() -> None:
    try:
        zc = Zeroconf()
        ServiceBrowser(zc, "_soundtouch._tcp.local.", SoundTouchListener())
        log.info("mDNS discovery started")
    except Exception as exc:
        log.warning("mDNS discovery failed to start: %s", exc)


# --- Config helpers --------------------------------------------------------------------

def load_stations() -> list[dict]:
    with STATIONS_PATH.open() as f:
        return yaml.safe_load(f).get("stations", [])


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {"speaker": {"name": "", "preferred_ip": None}, "presets": {}}
    with CONFIG_PATH.open() as f:
        return yaml.safe_load(f) or {}


def save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_PATH.open("w") as f:
        yaml.safe_dump(cfg, f, sort_keys=False, allow_unicode=True)


# --- Daemon control --------------------------------------------------------------------

def _docker_client():
    return docker.from_env()


def restart_daemon() -> tuple[bool, str | None]:
    try:
        client = _docker_client()
        container = client.containers.get(DAEMON_CONTAINER)
        container.restart(timeout=10)
        return True, None
    except Exception as exc:
        return False, str(exc)


def get_daemon_logs(tail: int = 80) -> str:
    try:
        client = _docker_client()
        container = client.containers.get(DAEMON_CONTAINER)
        return container.logs(tail=tail).decode("utf-8", errors="replace")
    except Exception as exc:
        return f"[error reading daemon logs: {exc}]"


# --- Speaker resolution ----------------------------------------------------------------

def resolve_speaker_ip(cfg: dict) -> str | None:
    ip = (cfg.get("speaker") or {}).get("preferred_ip")
    if ip:
        return ip
    name = (cfg.get("speaker") or {}).get("name")
    if not name:
        return None
    with _speakers_lock:
        entry = _speakers.get(name)
    return entry["ip"] if entry else None


# --- Routes ----------------------------------------------------------------------------

@app.route("/")
def index():
    cfg = load_config()
    stations = load_stations()
    with _speakers_lock:
        speakers = dict(_speakers)
    return render_template(
        "index.html",
        cfg=cfg,
        stations=stations,
        station_urls={s["stream_url"] for s in stations},
        speakers=speakers,
    )


@app.route("/save", methods=["POST"])
def save():
    form = request.form
    speaker_name = form.get("speaker_name", "").strip()
    speaker_ip = form.get("speaker_ip", "").strip() or None

    if not speaker_name:
        return "Speaker name is required", 400

    presets: dict[int, dict] = {}
    for i in range(1, 7):
        url_choice = form.get(f"preset_{i}_url", "").strip()
        custom_url = form.get(f"preset_{i}_custom", "").strip()
        custom_name = form.get(f"preset_{i}_custom_name", "").strip()

        if url_choice == "__none__" or (not url_choice and not custom_url):
            continue

        if url_choice == "__custom__":
            if not custom_url:
                continue
            stream_url = custom_url
            name = custom_name or f"Preset {i}"
        else:
            stream_url = url_choice
            name = form.get(f"preset_{i}_name", "").strip() or f"Preset {i}"

        if stream_url.lower().startswith("https://"):
            return (
                f"Preset {i}: Bose SoundTouch UPnP cannot handle HTTPS streams. "
                "Use the http:// variant — see TROUBLESHOOTING.md.",
                400,
            )

        presets[i] = {"name": name, "stream_url": stream_url}

    cfg = {
        "speaker": {"name": speaker_name, "preferred_ip": speaker_ip},
        "presets": presets,
    }
    save_config(cfg)

    ok, err = restart_daemon()
    if ok:
        return redirect(url_for("status", just_saved=1))
    return f"Saved config, but daemon restart failed: {err}", 500


@app.route("/status")
def status():
    cfg = load_config()
    just_saved = bool(request.args.get("just_saved"))
    return render_template(
        "status.html",
        cfg=cfg,
        logs=get_daemon_logs(),
        just_saved=just_saved,
    )


@app.route("/logs.json")
def logs_json():
    return jsonify({"logs": get_daemon_logs()})


@app.route("/trigger/<int:preset_id>", methods=["POST"])
def trigger(preset_id):
    if not 1 <= preset_id <= 6:
        return "Invalid preset", 400
    cfg = load_config()
    speaker_ip = resolve_speaker_ip(cfg)
    if not speaker_ip:
        return "Speaker IP unknown — not yet discovered, set a preferred_ip", 503

    headers = {"Content-Type": "application/xml"}
    url = f"http://{speaker_ip}:8090/key"
    try:
        requests.post(
            url,
            data=f'<key state="press" sender="Gabbo">PRESET_{preset_id}</key>',
            headers=headers,
            timeout=5,
        )
        time.sleep(0.2)
        requests.post(
            url,
            data=f'<key state="release" sender="Gabbo">PRESET_{preset_id}</key>',
            headers=headers,
            timeout=5,
        )
    except Exception as exc:
        return f"Trigger failed: {exc}", 500
    return "OK"


@app.route("/healthz")
def healthz():
    return jsonify({"ok": True})


# --- Entrypoint ------------------------------------------------------------------------

if __name__ == "__main__":
    start_discovery()
    app.run(host="0.0.0.0", port=LISTEN_PORT, debug=False)
