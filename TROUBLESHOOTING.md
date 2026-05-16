# Troubleshooting

If something does not work, this page is your first stop. Three quirks in the
Bose firmware cost most of the head-scratching during this project.

## 1. First preset press → amber LED only, no audio

**Symptom:** You press preset 1 (or any other), the LED next to that button
flashes amber, and nothing plays. The daemon log shows no `Detected preset N`
entry — the speaker just goes into an `INVALID_SOURCE` state.

**Why:** After Bose disabled the SoundTouch cloud on 2026-05-06, preset slots
that were never actively used before the cut-off do not have an internal
content-item cache. The recall path still queries `content.api.bose.io`,
times out, and silently drops the WebSocket preset event. The daemon never
gets a chance to push the UPnP override.

**Fix (one-time):** Pull the SoundTouch's power, count to ten, plug it back
in. On next boot the slot is reloaded from flash and behaves like a normal
preset. After this single power-cycle the speaker is stable.

## 2. Selected stream is HTTPS — speaker stays silent

**Symptom:** You added a custom URL like `https://example.com/stream.mp3`.
The daemon logs `UPnP AVTransport SetAVTransportURI on … returned HTTP 500:
Can't play. No URI supplied.`

**Why:** The SoundTouch UPnP renderer has no TLS stack. It can follow `30x`
redirects from an HTTPS frontend onto an HTTP CDN node, but it cannot complete
the initial TLS handshake itself.

**Fix:** Use the plain `http://` variant of the stream. The web UI rejects
HTTPS URLs at save time to prevent this footgun. For SRG-SSR streams, the
canonical `http://stream.srg-ssr.ch/m/<station>/mp3_128` URLs already redirect
into the load-balanced HTTP nodes — exactly the path Bose handles cleanly.

## 3. Preset switch ignored mid-playback

**Symptom:** A station is already playing via UPnP, you press another preset,
the daemon logs `UPnP playback request accepted`, but `/now_playing` keeps
showing the old stream.

**Why:** When the SoundTouch is in the `LOCAL_INTERNET_RADIO` source state
and is still trying to resolve a (now-dead) cloud URL, it silently swallows
incoming UPnP `SetAVTransportURI` calls — the response is HTTP 200 but the
state machine does not switch.

**Fix:** Only seen consistently before the one-time power-cycle from quirk
#1. After that, the daemon's `enforce_presets: true` mode keeps the override
clean. If it ever recurs: hold the speaker's power button until standby, then
press a preset again.

## 4. Web UI cannot restart the daemon container

**Symptom:** Saving in the UI succeeds, but you get `Saved config but daemon
restart failed: permission denied while trying to connect to the Docker
daemon socket`.

**Why:** The config-ui container needs to talk to `/var/run/docker.sock`.
This is wired through in `docker-compose.yml`, but on hardened hosts the
socket may have a stricter group than the container expects.

**Fix:** Run `ls -l /var/run/docker.sock` on the host. Make sure the socket
is owned by group `docker` and the daemon-control container is allowed to
access it. The default Pi OS / `get.docker.com` install handles this out of
the box.

## 5. No speakers discovered

**Symptom:** The "Discovered speakers" drop-down stays empty.

**Why:** mDNS (Bonjour) discovery uses multicast. The Pi and the SoundTouch
must be on the same Layer-2 segment. WLAN guest networks, VLAN-isolated
SSIDs, and some mesh setups block this traffic.

**Fix:** Confirm both devices are on the same SSID/VLAN. As a fallback, fill
in the speaker name and `Preferred IP` fields manually in the UI. The name is
visible in the SoundTouch app or via:

```
curl http://<speaker-ip>:8090/info | grep '<name>'
```

## 6. Adding a new station

The bundled list lives at `stations.yaml`. To contribute additions:

1. Confirm the URL is HTTP (not HTTPS).
2. Probe it once:
   ```
   curl -sL --max-time 5 -r 0-1024 -o /dev/null \
        -w "%{http_code} %{content_type}\n" "<your URL>"
   ```
   Expect `200 audio/mpeg` (or `audio/aac`). Many stream servers return `405`
   on HEAD requests — that is why we use a one-byte range GET.
3. Open a PR adding the entry to the right country block.
