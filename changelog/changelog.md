## Changelog

### 1.2.0

- Jellyfin 12.0 / 12.1 compatibility: update authentication to use `ApiKey` parameter and headers (resolving 401 Unauthorized errors caused by deprecated legacy auth removal)
- Update `jellyfin-apiclient-python` dependency to `>=1.19.0`
- Fix critical latent bug: `JellyfinMediaPlayer` controls (`play`, `pause`, `stop`, `next_track`, `previous_track`, `seek`) raising `AttributeError`
- Fix missing `supported_features` on `JellyfinMediaPlayer` (remote controls were hidden in Home Assistant)
- Implement `async_play_media` on `JellyfinMediaPlayer` for cast and media browser playback
- Fix `get_artwork` inverted argument bug and modernize image retrieval with async `aiohttp` client session
- Modernize Home Assistant architecture: adopt `entry.runtime_data`, `MediaPlayerState`, and `SensorEntity`
- Add connection and authentication validation in Config Flow and Options Flow
- Make WebSocket dispatching thread-safe using `call_soon_threadsafe`
- Prevent memory leaks by properly tracking and unsubscribing device update callbacks
- Harden upcoming media and YAMC data processing against missing/null fields and format dates safely
- Synchronize service schemas in `services.yaml` with integration handlers (add `search_term`, `yamc_setpage`, `yamc_setplaylist`)

### 1.1.2

- Handle `ManualPlaylistsFolder` type

### 1.1.1

- Fix `async_get_registry` warning

# 1.1.0

- Allow empty passwords
- Allow device deletion
- Add link to device
- Disable player by default
- Fix max channels
- Return appropriate mime-types

### 1.0.10

- Revert ignore folders

### 1.0.9

- Adjust for 2022.02
- Ignore folders

### 1.0.8

- Fix browse service (#21)

### 1.0.7

- Fix error handling

### 1.0.6

- Fix exception when item is not playable

### 1.0.5

- Fix IoT class
- Fix media play

### 1.0.4

- Fix Playlist folder

### 1.0.3

- Fix cast
- Info in YAMC

### 1.0.2

- Do not throttle data update

### 1.0.1

- Config flow fixes

### 1.0.0

- Initial public release
