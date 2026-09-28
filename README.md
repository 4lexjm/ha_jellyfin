# jellyfin_ha

Jellyfin integration for Home Assistant.

Forked version to solve the name conflict with the official Jellyfin integration.

All thanks and rights go to the authors of the integration.

## Installation:

- Go to HACS
- Press the three dots in the upper right corner
- Press Custom repositories
- In the Repository field, enter `4lexjm/jellyfin_ha`
- In the Category field, select `Integration`
- Search for the added integration in HACS and install it
- Configure your Jellyfin server
- After a restart, you will have media_player and sensor entities.

---

## Migration from the old HACS integration

> ⚠️ **Important**: This version uses the `jellyfin_custom` domain instead of `jellyfin`.
> If you had the old HACS integration installed (domain `jellyfin`), you must follow 
> the steps below to migrate. Reconfiguration is only required once.

### Step 1 — Backup your Lovelace configuration

Before making any changes, note down the following information so you can enter it again later:

- The **URL** of your Jellyfin server (e.g. `http://192.168.1.10:8096`)
- Your Jellyfin **username** and **password**
- The **entities** used in your dashboards (e.g. `sensor.jellyfin_media_server`, `media_player.jellyfin_...`)
- The **services** called in your automations (e.g. `jellyfin.trigger_scan`)

### Step 2 — Remove the old integration

1. In Home Assistant, go to **Settings → Devices & Services**
2. Find the **Jellyfin** card (old domain)
3. Click the three dots `⋮` → **Delete**
4. Confirm the deletion

> After deletion, the associated entities (`media_player`, `sensor`) will disappear automatically.

### Step 3 — Remove the old HACS repository (optional but recommended)

1. In HACS, go to **Integrations**
2. Search for **Jellyfin** (old version)
3. Click on it → **Remove** (or **Uninstall**)

### Step 4 — Add this repository in HACS

If not already done:

1. In HACS, click the three dots `⋮` in the top right corner
2. Select **Custom repositories**
3. In the **Repository** field, enter: `4lexjm/jellyfin_ha`
4. In the **Category** field, select: `Integration`
5. Click **Add**

### Step 5 — Install the new integration

1. In HACS → **Integrations**, search for **Jellyfin Custom**
2. Click → **Download**
3. **Restart Home Assistant**

### Step 6 — Configure the integration

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **Jellyfin Custom**
3. Enter the server URL, username, and password
4. Enable the desired options (*Upcoming Media*, *YAMC*)
5. Submit — the `media_player` and `sensor` entities will reappear

### Step 7 — Update your automations and dashboards

Entity IDs may have changed. Verify and update:

- **Entities** in Lovelace: find your old `jellyfin_*` entities and replace them with the new ones
- **Services** in your automations:

  | Old service | New service |
  |---|---|
  | `jellyfin.trigger_scan` | `jellyfin_custom.trigger_scan` |
  | `jellyfin.browse` | `jellyfin_custom.browse` |
  | `jellyfin.delete` | `jellyfin_custom.delete` |
  | `jellyfin.search` | `jellyfin_custom.search` |

- **Upcoming Media Card**: update the sensor entity name if necessary

---

## Features

### Entities

- 1 media_player entity per device
- 1 sensor per server
- Supports the "upcoming-media-card" custom card

### Media Browser

- Browse media and start playback from within Home Assistant

### Media Source

- Browse and stream to a cast device (e.g. Chromecast)

### Services

- `trigger_scan`: Trigger a server media scan
- `browse`: Show media info on a device
- `delete`: Delete media
- `search`: Search for media (for compatible frontends)
- `yamc_setpage`: Navigate pages on YAMC card
- `yamc_setplaylist`: Switch active playlist on YAMC card

### Upcoming Media Card

###### Sample for ui-lovelace.yaml:

```
- type: custom:upcoming-media-card
  entity: sensor.jellyfin_media_server
  title: Latest Media
```

More configuration options can be found in the [upcoming-media-card](https://github.com/custom-cards/upcoming-media-card#options) repo.

---

#### [View Changelog](changelog/changelog.md)
