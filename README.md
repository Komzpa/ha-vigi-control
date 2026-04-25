<p align="center">
  <img src="custom_components/vigi_control/brand/logo.png" alt="VIGI Control" width="520">
</p>

# VIGI Control for Home Assistant

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
- Image controls for brightness, contrast, saturation, chroma, sharpness, WDR gain, exposure gain, IR/white-light delays, flip, rotate, flicker, scene, white balance, exposure mode, and Smart IR where the camera exposes those fields.
- Switches for WDR, HLC, dehaze, EIS, anti-flicker, backlight compensation, lens distortion correction, full-color enhancements, camera motion detection, camera-side message alarm settings, and privacy/lens mask.
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
| `number` | White-light level, image brightness, contrast, saturation, chroma, sharpness, WDR gain, exposure gain, IR delay, white-light delay, motion digital sensitivity |
| `select` | Night-vision mode, flip, rotate, flicker, image scene mode, white balance, exposure type, Smart IR |
| `switch` | WDR, HLC, dehaze, EIS, auto-exposure anti-flicker, backlight compensation, lens distortion correction, full-color enhancement flags, camera motion detection flags, message alarm flags, privacy/lens mask |
| `sensor` | Firmware, current light/infrared state, stream resolution/encoding/bitrate, motion sensitivity, message alarm mode |

The exact entity set may change by model and firmware. Unsupported API sections are ignored so a camera can still expose the controls it supports.

## Frigate Setup

If your cameras are already in Frigate, keep them there. Add VIGI Control with the same camera host and local camera credentials from your Frigate config. During setup you can either enter those values manually or use **Import from Frigate config**.

The importer checks common Frigate paths first, including `/addon_configs/ccab4aaf_frigate/config.yaml`, then legacy `/config/frigate*.yml` paths. It can only read files that are visible from the Home Assistant Core container. On some HAOS add-on installs, Frigate's add-on config is visible to the SSH add-on but not to Core; in that case, enter the camera details manually from your Frigate config.

Recommended architecture:

1. Frigate manages RTSP streams, snapshots, recordings, and detections.
2. VIGI Control manages camera-side settings and illumination.
3. Automations combine both surfaces, for example turning the VIGI white light on when Frigate sees a person.

## Discovery

VIGI Control can search the LAN with ONVIF WS-Discovery. This is the same no-credential discovery family used by ONVIF tooling: cameras reply with their ONVIF service address and descriptive scopes, VIGI Control keeps only candidates whose ONVIF name/hardware/scopes look like VIGI, then asks for credentials only after you choose a camera.

Current setup paths:

- **Frigate import** discovers configured camera hosts from local Frigate RTSP URLs.
- **ONVIF discovery** discovers LAN cameras that answer WS-Discovery as `NetworkVideoTransmitter` devices and advertise VIGI identity in their ONVIF metadata.
- **Manual setup** validates one host by logging into the local VIGI API.
- **Feature detection** happens after login: each camera gets only the entities backed by fields it reported.

## Installation

### HACS custom repository

1. In HACS, add this repository as a custom integration repository.
2. Install **VIGI Control**.
3. Restart Home Assistant.
4. Add the integration from **Settings -> Devices & services**.

### Manual

Copy `custom_components/vigi_control` into Home Assistant's `custom_components` directory and restart Home Assistant.

## Known Notes

- VIGI C440-W white-light brightness is effectively a 5-step value, not a true 0-255 dimmer.
- Camera auto-exposure may make the visual brightness change look subtler than the API state change.
- The white-light off path is order-sensitive on tested firmware: the integration sets `wtl_type=auto` before switching `night_vision_mode` back to infrared.
- This integration does not create a camera entity by default, to avoid duplicate Frigate/ONVIF camera feeds.
- Camera-side motion/alarm controls affect the camera firmware itself. If Frigate is your detection source of truth, keep Frigate automations pointed at Frigate entities and use these switches only when you deliberately want to change camera-side behavior.

## Tested Hardware

| Model | Firmware | Notes |
| --- | --- | --- |
| VIGI C440-W | `3.0.2 Build 240611 Rel.77271n` | White light, image controls, motion/alarm controls, stream diagnostics |

## Troubleshooting

- **Frigate import cannot read the config**: enter the camera host and local credentials manually. HAOS add-on config directories are not always visible inside the Home Assistant Core container.
- **Brightness seems subtle**: the camera's auto-exposure may compensate for white-light changes. Check the white-light level entity or direct camera state rather than judging only by frame luma.
- **Light state looks delayed**: Home Assistant receives an optimistic state immediately, but the camera may take several seconds to report the settled white-light mode and level back through the coordinator.
- **Duplicate camera lights**: remove older prototype integrations such as `vigi_camera_lights` after VIGI Control is working.
- **Integration icon still says "not available"**: clear the browser cache or restart Home Assistant after installing; local custom brand assets are served by Home Assistant 2026.3 and newer.

## Development Status

Early local integration. Tested against VIGI C440-W firmware from a Home Assistant setup where Frigate already owns video.

Planned next mappings:

- Audio controls where the camera exposes stable fields.
- Camera event toggles only when they add value beyond Frigate events.
- More model/firmware reports from other VIGI cameras.
