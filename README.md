# Home Assistant Integration for Wiser for KNX (Local API)

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/default)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A Home Assistant custom integration for **Schneider Electric Wiser for KNX** (and compatible **spaceLYnk** / **LogicMachine** controllers) using their local API.

---

## ✨ Features

- **Automatic Discovery on LAN**:
  - **mDNS / Zeroconf**: Automatically identifies controllers broadcasting `_http._tcp.local.` (matching `wiser*`, `spacelynk*`, `logicmachine*`) or `_knx._udp.local.`.
  - **DHCP Snooping**: Automatically detects Schneider Electric & Embedded Systems hardware by MAC address prefix (`00:0C:C6`, `00:00:54`, `E0:4F:43`).
- **Dynamic API Endpoint Parsing**:
  - Automatically probes and identifies the active local API type:
    - **OpenAPI / Swagger REST API** (`/api/openapi.json`, `/api/v1/objects`)
    - **SCADA Remote JSON API** (`/scada-remote/request`)
    - **Services JSON API** (`/services/json/`)
- **Seamless Credential Handling**:
  - Prompts for credentials (HTTP Basic Auth / API credentials) directly within the Home Assistant UI during configuration.
- **Automatic Entity Generation**:
  - **Lights** (`light`): Standard on/off lights and dimmers (DPT 5 / percentage or 0-255).
  - **Switches** (`switch`): Relay switches, sockets, and binary actuators (DPT 1).
  - **Sensors** (`sensor`): Temperature, humidity, illuminance (lux), power (W), energy (kWh), voltage, current, and CO2 (DPT 9, 12, 13, 14, etc.).
  - **Covers** (`cover`): Blinds, shutters, and curtains with position control (DPT 1 / DPT 5).
  - **Climate** (`climate`): Thermostats with target temperature setpoint control.

---

## 🚀 Installation

### Option 1: Via HACS (Recommended)

1. Open **HACS** in your Home Assistant instance.
2. Click the three dots in the top right corner and choose **Custom repositories**.
3. Paste the URL of this repository:
   ```
   https://github.com/<your-github-username>/ha-wiser-for-knx
   ```
4. Category: **Integration**.
5. Click **Add**, find **Wiser for KNX**, and click **Download**.
6. Restart Home Assistant.

### Option 2: Manual Installation

1. Copy the `custom_components/wiser_for_knx` folder from this repository into your Home Assistant's `config/custom_components/` directory:
   ```text
   config/
   └── custom_components/
       └── wiser_for_knx/
           ├── __init__.py
           ├── manifest.json
           ├── config_flow.py
           ├── const.py
           ├── api.py
           ├── coordinator.py
           ├── entity.py
           ├── light.py
           ├── switch.py
           ├── sensor.py
           ├── cover.py
           ├── climate.py
           ├── strings.json
           └── translations/
               └── en.json
   ```
2. Restart Home Assistant.

---

## ⚙️ Configuration

1. In Home Assistant, go to **Settings** -> **Devices & Services**.
2. If your Wiser for KNX is powered on and connected to the same LAN, Home Assistant will show a **"Discovered"** notification card.
3. Click **Configure**, enter your **Username** (default: `admin`) and **Password**, and click **Submit**.
4. If auto-discovery is not enabled on your network:
   - Click **Add Integration** in the bottom right corner.
   - Search for **Wiser for KNX**.
   - Enter your controller's IP address and credentials.

---

## 🛠️ How to Upload this Project to GitHub

To push this project to GitHub from your computer:

```bash
cd "ha-wiser-for-knx"
git init
git add .
git commit -m "Initial commit of Wiser for KNX Home Assistant integration"
git branch -M main
git remote add origin https://github.com/<your-username>/ha-wiser-for-knx.git
git push -u origin main
```

Once pushed, you can share it or link it directly in HACS.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
