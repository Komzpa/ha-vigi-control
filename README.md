<p align="center">
  <img src="custom_components/vigi_control/brand/logo.png" alt="VIGI Control" width="520">
</p>

# VIGI Control for Home Assistant

[![Open your Home Assistant instance and add this repository to HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Komzpa&repository=ha-vigi-control&category=integration)

Local Home Assistant controls for TP-Link VIGI cameras.

This integration is intentionally designed to sit next to Frigate instead of replacing it:

- Frigate remains the source of truth for camera streams, recordings, snapshots, and object detection.
- Home Assistant's ONVIF/Frigate entities can keep handling the video surface.
- VIGI Control exposes local camera controls that are not available through Frigate or basic ONVIF.

The first tested device is TP-Link VIGI C440-W. The local VIGI HTTPS API is not formally documented for every camera model, so unsupported models may expose fewer controls until their fields are mapped.

## Features

- White-light/floodlight entity with Home Assistant brightness control.
- Slider-safe brightness handling: the first value is sent immediately, rapid follow-up values are coalesced.
- Night-vision mode selector for the known infrared/white-light modes.
- White-light level number entity using the camera's real 1-5 step scale.
- Image controls for brightness, contrast, saturation, chroma, sharpness, WDR gain, exposure gain, night-vision auto-switch delays, flip, rotate, flicker, scene, white balance, exposure mode, and Smart IR where the camera exposes those fields.
- Switches for WDR, HLC, dehaze, EIS, anti-flicker, backlight compensation, lens distortion correction, full-color enhancements, camera motion detection, camera-side message alarm settings, and privacy/lens mask.
- Buttons to start and stop the camera's manual alarm immediately, where the firmware supports VIGI/Tapo `manual_msg_alarm`.
- Speaker volume control, where the camera exposes `audio_config.speaker.volume`.
- Optional Assist satellite announcement entity for Home Assistant TTS/announcements and microphone capture through a configured go2rtc `vigi://` stream.
- Diagnostic sensors for current white-light/infrared/smart-white-light state and firmware metadata when available.
- Optional setup path that reads local Frigate YAML and imports camera host/credentials from RTSP URLs.
- Feature detection from the camera's first API payload: entities are created only for fields the camera actually reports.
- ONVIF WS-Discovery setup path for finding LAN cameras without sending credentials during discovery.
- Local API access only; no TP-Link cloud account is used.

## Entities

For each configured camera, VIGI Control creates a Home Assistant device with entities in these groups:

| Platform | Entities |
| --- | --- |
| `light` | White light / floodlight with brightness |
| `button` | Manual alarm start/stop |
| `assist_satellite` | Optional Assist announcement and start-conversation surface backed by go2rtc talk-back plus camera microphone audio |
| `number` | White-light level, speaker volume, image brightness, contrast, saturation, chroma, sharpness, WDR gain, exposure gain, infrared/white-light auto-switch delays, motion digital sensitivity |
| `select` | Night-vision mode, flip, rotate, flicker, image scene mode, white balance, exposure type, Smart IR |
| `switch` | WDR, HLC, dehaze, EIS, auto-exposure anti-flicker, backlight compensation, lens distortion correction, full-color enhancement flags, camera motion detection flags, message alarm flags, privacy/lens mask |
| `sensor` | Firmware, current light/infrared state, stream resolution/encoding/bitrate, motion sensitivity, message alarm mode |

The exact entity set may change by model and firmware. Unsupported API sections are ignored so a camera can still expose the controls it supports.

Home Assistant placement is intentionally split by how often the control is useful:

- **Controls**: the everyday white-light entity with on/off and brightness.
- **Configuration**: camera tuning such as night-vision mode, privacy/lens mask, the raw white-light level, speaker volume, image adjustment numbers/selects, camera-side motion detection, message alarm settings, manual alarm buttons, and auto-switch delays.
- **Diagnostic**: read-only firmware, stream, light-state, motion, and alarm sensors.

## Frigate Setup

If your cameras are already in Frigate, keep them there. Add VIGI Control with the same camera host and local camera credentials from your Frigate config. During setup you can either enter those values manually or use **Import from Frigate config**.

The importer checks common Frigate paths first, including `/addon_configs/ccab4aaf_frigate/config.yaml`, then legacy `/config/frigate*.yml` paths. It can only read files that are visible from the Home Assistant Core container. On some HAOS add-on installs, Frigate's add-on config is visible to the SSH add-on but not to Core; in that case, enter the camera details manually from your Frigate config.

Recommended architecture:

1. Frigate manages RTSP streams, snapshots, recordings, and detections.
2. VIGI Control manages camera-side settings and illumination.
3. Automations combine both surfaces, for example turning the VIGI white light on when Frigate sees a person.

## Assist Satellite

VIGI Control can expose an optional Assist satellite entity that plays Home Assistant announcements through the camera's two-way-audio speaker path and reads the camera microphone for Home Assistant STT. This requires a reachable go2rtc API with a stream defined as `vigi://...` for the same camera. Configure these per camera from the integration options:

- **go2rtc API URL**: for example `http://192.168.100.30:19840`
- **go2rtc stream**: for example `living_vigi`
- **go2rtc microphone stream**: optional separate receive stream for the camera microphone, for example Frigate's `living_sub`; if empty, VIGI Control reuses the talk-back stream.
- **Assist listen seconds**: microphone capture window for Home Assistant STT, default `5` seconds. Increase it for longer commands; keep it short for alarm/wake phrases.
- **Save Assist audio captures**: debugging option that saves each Assist microphone capture as a 16 kHz mono WAV file plus a JSON sidecar under `/config/vigi_assist_captures`. Keep it disabled unless you are collecting STT regression fixtures.
- **Assist audio retention (MiB)**: disk budget for saved Assist captures, default `1024` MiB. Oldest captures are pruned after each new capture when the directory grows past this budget; set `0` to disable pruning.

If go2rtc is embedded in the Frigate Home Assistant add-on, prefer the add-on DNS name from Home Assistant Core, for example `http://ccab4aaf-frigate:1984`, instead of running a second go2rtc instance.

VIGI Control does not create a standalone `media_player` for generic Home Assistant TTS/media playback. For that use case, expose the same go2rtc stream with the HACS WebRTC Camera integration (`platform: webrtc`) and keep VIGI Control focused on camera controls plus the Assist satellite microphone flow.

When talk-back is configured, VIGI Control also exposes an Assist satellite entity. It supports announcements and start-conversation actions: after the start announcement, VIGI Control reads the camera microphone from the configured go2rtc microphone stream for the configured listen window, normalizes the low camera-mic level, streams raw 16 kHz mono PCM to Home Assistant's configured STT provider, and forwards the recognized text to the configured Home Assistant conversation agent. If that HA agent is missing, VIGI Control falls back to Home Assistant's built-in conversation agent instead of failing before STT. Continuous wake-word listening is a separate always-on microphone loop and is not enabled by default.

## Discovery

VIGI Control can search the LAN with ONVIF WS-Discovery. This is the same no-credential discovery family used by ONVIF tooling: cameras reply with their ONVIF service address and descriptive scopes, VIGI Control keeps only candidates whose ONVIF name/hardware/scopes look like VIGI, then asks for credentials only after you choose a camera.

Current setup paths:

- **Frigate import** discovers configured camera hosts from local Frigate RTSP URLs.
- **ONVIF discovery** discovers LAN cameras that answer WS-Discovery as `NetworkVideoTransmitter` devices and advertise VIGI identity in their ONVIF metadata.
- **Manual setup** validates one host by logging into the local VIGI API.
- **Feature detection** happens after login: each camera gets only the entities backed by fields it reported.

## Frigate Device Linking

Home Assistant merges entities into one device when integrations report a shared device identifier. VIGI Control can link a camera to an existing Frigate camera device:

- Frigate import links automatically when the Frigate camera key matches a live Frigate device.
- Manual and ONVIF setup let you choose an existing Frigate camera from **Link to Frigate camera**.

When linked, VIGI Control adds the matching Frigate device identifier alongside its own VIGI identifier, so the Frigate camera entity and VIGI controls appear under the same Home Assistant device.

## Installation

### HACS custom repository

1. Click the HACS badge above, or in HACS add `https://github.com/Komzpa/ha-vigi-control` as a custom integration repository.
2. Install **VIGI Control**.
3. Restart Home Assistant.
4. Add the integration from **Settings -> Devices & services**.

### Manual

Copy `custom_components/vigi_control` into Home Assistant's `custom_components` directory and restart Home Assistant.

## Known Notes

- VIGI C440-W white-light brightness is effectively a 5-step value, not a true 0-255 dimmer.
- Camera auto-exposure may make the visual brightness change look subtler than the API state change.
- The white-light off path is order-sensitive on tested firmware: the integration sets `wtl_type=auto` before switching `night_vision_mode` back to infrared.
- Message alarm switches configure camera-side detection alarm behavior; use the manual alarm start/stop buttons when an automation needs the camera to sound immediately.
- This integration does not create a camera entity by default, to avoid duplicate Frigate/ONVIF camera feeds.
- Camera-side motion/alarm controls affect the camera firmware itself. If Frigate is your detection source of truth, keep Frigate automations pointed at Frigate entities and use these switches only when you deliberately want to change camera-side behavior.

## Tested Hardware

| Model | Firmware | Notes |
| --- | --- | --- |
| VIGI C440-W | `3.0.2 Build 240611 Rel.77271n` | White light, speaker volume, manual alarm buttons, image controls, motion/alarm controls, stream diagnostics |

## Troubleshooting

- **Frigate import cannot read the config**: enter the camera host and local credentials manually. HAOS add-on config directories are not always visible inside the Home Assistant Core container.
- **Brightness seems subtle**: the camera's auto-exposure may compensate for white-light changes. Check the white-light level entity or direct camera state rather than judging only by frame luma.
- **Light state looks delayed**: Home Assistant receives an optimistic state immediately, but the camera may take several seconds to report the settled white-light mode and level back through the coordinator.
- **Duplicate camera lights**: remove older prototype integrations such as `vigi_camera_lights` after VIGI Control is working.
- **Integration icon still says "not available"**: clear the browser cache or restart Home Assistant after installing; local custom brand assets are served by Home Assistant 2026.3 and newer.

## Development Status

Early local integration. Tested against VIGI C440-W firmware from a Home Assistant setup where Frigate already owns video.

Planned next mappings:

- Camera event toggles only when they add value beyond Frigate events.
- More model/firmware reports from other VIGI cameras.
