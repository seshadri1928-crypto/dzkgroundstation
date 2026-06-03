# DEAD ZONE KILLER - Ground Station 2

Computer-side live telemetry analytics center.

## Run Dashboard

```powershell
node server.js
```

Open:

```text
http://127.0.0.1:8082
```

The dashboard starts in simulator mode.

## Connect Ground Station 1 USB Serial

Open the dashboard in Chrome or Edge, press `CONNECT USB`, and select the ESP32 COM port.

Ground Station 1 now prints:

```text
TELEMETRY_PACKET:LAT:...|LON:...|BATTERY:...|TEMP:...|RSSI:...
```

Ground Station 2 uses that line for clean real-time packet decoding.

## Optional Python Server

`app.py` is also included for systems with Python and `pyserial`, but the Node/Web Serial dashboard needs no npm packages.
