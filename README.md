# soundtouch-cloud-revival

**Revive your Bose SoundTouch after the Cloud was shut down — Internet radio
on the physical preset buttons, configured from a web browser in under a
minute.**

On **2026-05-06** Bose decommissioned the cloud servers that powered the
SoundTouch family. Presets, the in-app station browser and firmware updates
stopped working overnight. The hardware itself still listens to AirPlay,
Bluetooth and Spotify Connect — but the convenience of *"come home, press 1,
SRF 3 plays"* was gone.

This project brings it back. A tiny daemon on a Raspberry Pi listens for
preset button presses on your speaker and starts an internet radio stream via
the speaker's own UPnP renderer. A web UI lets you pick the six stations from
a curated list (or add your own URL) — no SSH, no YAML editing, no Docker
fluency required.

```
┌────────────────────┐      mDNS + WebSocket      ┌────────────────────┐
│   Raspberry Pi     │ ◀──────────────────────────│  Bose SoundTouch   │
│   (~25 CHF)        │                            │  10 / 20 / 30 / …  │
│                    │      UPnP SetAVTransport   │                    │
│  ┌──────────────┐  │ ──────────────────────────▶│  source = UPNP     │
│  │ alinossier   │  │      AVTransport:Play      │  preset 1 plays    │
│  │ daemon       │  │ ──────────────────────────▶│  http://stream...  │
│  └──────────────┘  │                            └────────────────────┘
│  ┌──────────────┐  │
│  │ config-ui    │ ─┼────► http://soundtouch-pi.local:8181/
│  │ (Flask)      │  │
│  └──────────────┘  │
└────────────────────┘
```

## Why this exists

Several projects already address the Bose Cloud-EOL, each at a different
trade-off:

| Approach                                                                 | Eingriff am Speaker | Functionality           |
| ------------------------------------------------------------------------ | ------------------- | ----------------------- |
| **soundtouch-cloud-revival** (this repo)                                 | none                | preset buttons → radio  |
| [soundcork](https://github.com/deborahgu/soundcork)                      | USB-stick hack      | full cloud emulation    |
| [Bose-SoundTouch-Hybrid-2026](https://github.com/TJGigs/Bose-SoundTouch-Hybrid-2026) | USB-stick hack      | full + streaming services |

If all you want is *"press a preset → radio plays"*, this is the cheapest,
lowest-risk path. The speaker stays untouched and is reversible by powering
off the Pi.

## Hardware

- Any Linux box on the same WLAN as the speaker. A **Raspberry Pi Zero 2 W**
  is plenty (quad-core ARMv8, 512 MB RAM, ~0.7 W idle, ~25 CHF).
  - **Note:** The original Pi Zero W V1.1 (ARMv6) is **not supported** — the
    upstream daemon's `python:3.12-slim` base image has no ARMv6 build.
- A microSD card (8 GB is fine), Raspberry Pi OS Lite 64-bit (Bookworm or
  newer).
- A SoundTouch speaker with reachable firmware. Tested on SoundTouch 10
  (firmware 27.0.3) — the WebSocket + UPnP API is the same across the series,
  so SoundTouch 20 / 30 / 300 / 500 should work identically.

## Quick start

Flash the SD card with the Pi Imager. In the OS customisation panel set:

- Hostname: `soundtouch-pi` *(any name works — adjust the URLs below)*
- Username + password
- SSH on, ideally with public key auth
- Wi-Fi credentials of the network the speaker is on
- Locale to your timezone

Boot the Pi, SSH in, then:

```bash
curl -fsSL https://raw.githubusercontent.com/GrossmeisterB/soundtouch-cloud-revival/main/setup.sh | bash
```

The installer will:

1. Install Docker + Compose v2 (via `get.docker.com`)
2. Clone this repo and the upstream daemon into `~/soundtouch-cloud-revival/`
3. Write an empty `config.yaml`
4. Build and start both containers (`restart: unless-stopped`)

When it is done, open in your browser:

> **http://soundtouch-pi.local:8181/**

Pick the speaker from the discovery drop-down, choose six stations, hit
**Save**. The daemon restarts, and the next press of a preset button on the
SoundTouch plays the configured stream.

> **First press → amber LED only?** That's a one-time quirk of presets that
> were never used during the Bose Cloud era. Pull the SoundTouch's power for
> ten seconds; afterwards everything works. Details in
> [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## How it works

- **alinossier/soundtouch-local-presets** (the engine) opens a WebSocket to
  the speaker on port 8080 and listens for `<preset id="N">` events. When the
  user presses preset N, it sends a UPnP `SetAVTransportURI` + `Play` to the
  speaker's own renderer on port 8091. The speaker switches to the
  `UPNP` source and starts streaming the URL directly from the radio
  station's CDN — the Pi is not in the audio path.

- **config-ui** is a small Flask sidecar on port 8181. It:

  - browses `_soundtouch._tcp.local` over mDNS to discover speakers,
  - lets you assign one of the bundled `stations.yaml` entries (or a custom
    URL) to each of the six preset buttons,
  - writes the shared `config.yaml`,
  - restarts the daemon container via `/var/run/docker.sock` so the new
    config takes effect immediately,
  - displays a live tail of the daemon log and a per-preset *Play* button so
    you can trigger from the browser as well as from the speaker.

Both containers run in `network_mode: host` because mDNS discovery and the
SoundTouch WebSocket need direct LAN access.

## Adding your own stations

Edit `stations.yaml` and open a PR. Keep all URLs **HTTP, not HTTPS**
(SoundTouch UPnP has no TLS). Verify the URL with a one-byte range GET:

```bash
curl -sL --max-time 5 -r 0-1024 -o /dev/null \
     -w "%{http_code} %{content_type}\n" "<your stream URL>"
```

Expect `200 audio/mpeg` (or `audio/aac`). HEAD often returns `405` — that is
why we use `GET -r 0-1024`.

For one-off custom URLs, you can also enter them directly in the web UI per
preset; nothing in `stations.yaml` is required for that path.

## Updating

```bash
cd ~/soundtouch-cloud-revival
git pull
sudo docker compose up -d --build
```

…or just rerun `bash setup.sh`. The script is idempotent.

## Acknowledgements

- [@alinossier](https://github.com/alinossier) for
  [soundtouch-local-presets](https://github.com/alinossier/soundtouch-local-presets),
  which does all the heavy lifting. This repo is a wrapper that pairs the
  daemon with a web UI, a curated station list and a one-shot installer.
- [@deborahgu](https://github.com/deborahgu) and
  [@TJGigs](https://github.com/TJGigs) for showing how much of the SoundTouch
  cloud surface is reverse-engineerable.
- Bose for publishing the
  [SoundTouch Web API PDF](https://assets.bosecreative.com/m/496577402d128874/original/SoundTouch-Web-API.pdf)
  alongside the cloud shutdown — which is what made all of this legal and
  feasible.

## License

[MIT](LICENSE).
