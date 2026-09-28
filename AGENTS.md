# AGENTS.md

## Project Overview

**jellyfin_ha** is a Home Assistant custom integration for [Jellyfin](https://jellyfin.org/), a free and open-source media server.
It is a maintained fork of [koying/jellyfin_ha](https://github.com/koying/jellyfin_ha), published under [`4lexjm/jellyfin_ha`](https://github.com/4lexjm/jellyfin_ha), designed to resolve the name conflict with the official Jellyfin integration by using the domain `jellyfin_custom`.

### Key technologies

| Layer | Technology |
|---|---|
| Language | Python 3.x |
| Framework | Home Assistant custom component |
| HA config system | Config Flow (UI-based setup, no YAML required) |
| Jellyfin client | `jellyfin-apiclient-python>=1.19.0` |
| Distribution | HACS (Home Assistant Community Store) |
| CI | GitHub Actions (HACS validation) |

### Integration domain

```
custom_components/jellyfin_custom/
```

The HA domain name is `jellyfin_custom`. Only one instance of the integration can be configured at a time (unique ID enforced in config flow).

---

## Repository Structure

```
jellyfin_ha/
├── custom_components/
│   └── jellyfin_custom/           # Integration source code
│       ├── __init__.py     # Core logic: setup, coordinator, services, state management
│       ├── config_flow.py  # UI config flow + options flow
│       ├── const.py        # All constants (domain, services, defaults, playlists)
│       ├── media_player.py # MediaPlayer entity implementation
│       ├── media_source.py # MediaSource platform (browsing, streaming)
│       ├── sensor.py       # Sensor entity (upcoming media / server info)
│       ├── services.yaml   # Service definitions for HA UI
│       ├── strings.json    # Translation keys (source of truth)
│       ├── manifest.json   # Integration metadata and requirements
│       └── translations/   # Locale files (en.json, fr.json, de.json)
├── changelog/
│   └── changelog.md        # Version history
├── .github/
│   └── workflows/
│       └── validate.yaml   # HACS validation CI (runs on push, PR, daily)
├── .agents/
│   └── skills/
│       └── home-assistant-custom-integration/  # Agent skill for HA integration patterns
├── hacs.json               # HACS metadata
└── README.md               # User-facing documentation
```

---

## Setup & Development Environment

This project has **no build step** and **no package manager**. It is pure Python loaded directly by Home Assistant.

### Prerequisites

- A running Home Assistant instance (Core, OS, or Container)
- Python 3.11+ (matching the HA version you target)
- (Optional) A virtual environment for linting/type checking

### Local development setup

```bash
# Clone the repository
git clone https://github.com/4lexjm/jellyfin_ha.git
cd jellyfin_ha

# (Optional) Create a virtual environment for tooling
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # Linux/macOS

# Install the Jellyfin API client (for IDE support / linting)
pip install jellyfin-apiclient-python==1.7.2

# Install Home Assistant as a library (for type checking and IDE support)
pip install homeassistant
```

### Deploying to a local Home Assistant instance

1. Copy `custom_components/jellyfin/` into the `custom_components/` directory of your HA configuration folder.
2. Restart Home Assistant.
3. Go to **Settings → Devices & Services → Add Integration** and search for **Jellyfin**.

---

## Configuration

The integration is fully configured through the UI (Config Flow). No YAML configuration is required.

### Required fields

| Field | Description |
|---|---|
| `url` | Full URL of the Jellyfin server (e.g., `http://192.168.1.10:8096`) |
| `username` | Jellyfin username |
| `password` | Jellyfin password (can be empty) |

### Optional fields

| Field | Default | Description |
|---|---|---|
| `verify_ssl` | `True` | Verify SSL certificate |
| `generate_upcoming` | `False` | Generate a sensor with upcoming media |
| `generate_yamc` | `False` | Generate YAMC-compatible upcoming media playlists |

---

## Code Style & Conventions

This project follows the **Home Assistant code style** for custom integrations:

- **Python**: PEP 8 compliant, type hints encouraged for new code.
- **Async-first**: All I/O operations must be `async`. Use `async def` and `await`. Never block the event loop.
- **Logging**: Use `logging.getLogger(__name__)`. Log at appropriate levels (`DEBUG` for verbose, `WARNING`/`ERROR` for problems). Never log credentials.
- **Constants**: All constants live in `const.py`. Never hardcode strings or values inline.
- **Naming**:
  - Files: `snake_case.py`
  - Classes: `PascalCase`
  - Constants: `UPPER_SNAKE_CASE`
  - Functions/variables: `snake_case`
  - Async methods: prefix with `async_` (HA convention, e.g., `async_setup_entry`)
- **Error handling**: Catch only specific exceptions. Log with full context. Never swallow silently.
- **No breaking changes to the domain name**: The domain `jellyfin_custom` must remain stable — changing it would require users to reconfigure.

### Translation files

- `strings.json` is the **source of truth** for translation keys.
- Corresponding locale files are in `translations/` (`en.json`, `fr.json`, `de.json`).
- When adding new config flow fields or error messages, update **both** `strings.json` and all locale files.

---

## Services

Defined in `services.yaml` and registered in `__init__.py`:

| Service | Description |
|---|---|
| `jellyfin_custom.trigger_scan` | Trigger a media library scan on the server |
| `jellyfin_custom.browse` | Display media info on a device |
| `jellyfin_custom.delete` | Delete a media item |
| `jellyfin_custom.search` | Search for media (compatible frontends) |
| `jellyfin_custom.yamc_setpage` | Set the active page for the YAMC upcoming media card |
| `jellyfin_custom.yamc_setplaylist` | Set the active playlist for the YAMC upcoming media card |

When adding a new service:
1. Add the constant to `const.py`.
2. Register the handler in `__init__.py` using `hass.services.async_register(...)`.
3. Add the service definition to `services.yaml`.

---

## Testing

This project has **no automated test suite** at this time. The only automated check is HACS validation.

### Running CI validation locally

The CI uses the official HACS GitHub Action. To validate HACS compliance locally, you can use the HACS action container:

```bash
# Via Docker (mirrors what CI does)
docker run -v $(pwd):/github/workspace \
  -e INPUT_CATEGORY=integration \
  hacs/action:main
```

### Manual testing checklist

Before submitting a change, verify:

- [ ] Integration loads without errors in Home Assistant logs
- [ ] Config flow completes successfully (setup + options)
- [ ] `media_player` entities appear and reflect correct states (Playing, Paused, Idle, Off)
- [ ] `sensor` entity updates with server info
- [ ] Services (`trigger_scan`, `browse`, `delete`, `search`) execute without errors
- [ ] Media Browser browsing works
- [ ] Cast/Media Source streaming works (if applicable to the change)

---

## CI/CD

**Workflow**: `.github/workflows/validate.yaml`

- **Triggers**: every push, every pull request, daily at midnight UTC
- **Job**: HACS validation — checks that the integration meets HACS publishing requirements (manifest, domain, file structure, etc.)
- **No build or deploy step**: users install directly via HACS from this repository.

---

## Pull Request Guidelines

- **Commit messages**: Follow [Conventional Commits](https://www.conventionalcommits.org/):
  ```
  <type>(<scope>): <short description>
  ```
  Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`.
  Example: `fix(media_player): handle missing album art gracefully`

- **Changelog**: Update `changelog/changelog.md` for every user-facing change under the relevant version heading.

- **HACS compliance**: Ensure `manifest.json` is valid and up to date (version, requirements, codeowners).

- **Before submitting**:
  - HACS validation passes
  - No credentials or sensitive data in code
  - All new constants added to `const.py`
  - Translation files updated if config flow is modified

---

## Debugging & Troubleshooting

### Enable debug logging in Home Assistant

Add to your HA `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.jellyfin: debug
```

### Common issues

| Symptom | Likely cause | Fix |
|---|---|---|
| Integration fails to load | Missing dependency | Check `manifest.json` requirements; reinstall via HACS |
| Cannot connect error | Wrong URL or network issue | Verify the Jellyfin server URL is reachable from HA |
| Entity not appearing | Setup not complete | Check HA logs for errors during `async_setup_entry` |
| SSL error | Self-signed certificate | Disable `verify_ssl` in the options flow |
| YAMC sensor empty | `generate_yamc` not enabled | Enable the option in integration settings |

### Key files for debugging

- **`__init__.py`**: Entry point, coordinator, all service registrations — start here for any non-UI issues.
- **`config_flow.py`**: All UI setup/options logic — start here for configuration issues.
- **`media_player.py`**: Playback state, transport controls — start here for player entity issues.
- **`media_source.py`**: Media browsing and streaming — start here for Media Browser / cast issues.

---

## Key Design Decisions

- **Single instance only**: The integration uses `await self.async_set_unique_id(DOMAIN)` to prevent multiple configurations, since the domain `jellyfin_custom` enforces a unique entry.
- **IoT class `local_push`**: The Jellyfin client library pushes state updates via WebSocket; polling is not used for session state.
- **Forked to avoid name conflict**: The upstream integration `koying/jellyfin_ha` uses the `jellyfin` domain, which conflicts with the official HA integration. This fork uses `jellyfin_custom` to allow both integrations to coexist.
