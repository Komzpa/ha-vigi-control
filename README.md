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
- Local API access only; no TP-Link cloud account is used.

## Frigate Setup

If your cameras are already in Frigate, keep them there. Add VIGI Control with the same camera host and local camera credentials from your Frigate config. During setup you can either enter those values manually or use **Import from Frigate config**.

The importer checks common Frigate paths first, including `/addon_configs/ccab4aaf_frigate/config.yaml`, then legacy `/config/frigate*.yml` paths. It can only read files that are visible from the Home Assistant Core container. On some HAOS add-on installs, Frigate's add-on config is visible to the SSH add-on but not to Core; in that case, enter the camera details manually from your Frigate config.

Recommended architecture:

1. Frigate manages RTSP streams, snapshots, recordings, and detections.
2. VIGI Control manages camera-side settings and illumination.
3. Automations combine both surfaces, for example turning the VIGI white light on when Frigate sees a person.

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

## Development Status

Early local integration. Tested against VIGI C440-W firmware from a Home Assistant setup where Frigate already owns video.

Planned next mappings:

- Image controls such as brightness, contrast, saturation, sharpness, mirror, flip, WDR where available.
- Audio controls where the camera exposes stable fields.
- Camera event toggles only when they add value beyond Frigate events.
- Optional Frigate config import helper for host/credential discovery.
