# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Open Battery Information (OBI) is a battery diagnostics and repair tool for Makita LXT batteries. It reads BMS (Battery Management System) data via an Arduino acting as a OneWire bridge, allowing users to diagnose faults, read cell voltages/temperatures, reset errors, and test LEDs on batteries that may have been unnecessarily locked by false fault detection.

## Commands

### Python Desktop Application (`OpenBatteryInformation/`)

```bash
# Install dependencies
pip install -r OpenBatteryInformation/requirements.txt

# Run the application
cd OpenBatteryInformation && python main.py

# Build Windows executable
cd OpenBatteryInformation && pyinstaller obi.spec
```

### Arduino Firmware (`ArduinoOBI/`)

Requires PlatformIO (VS Code extension or CLI):

```bash
# Build for Arduino Uno
cd ArduinoOBI && pio run -e uno

# Build for Arduino Nano
cd ArduinoOBI && pio run -e nano

# Upload to board
cd ArduinoOBI && pio run -e uno -t upload
```

## Architecture

The system is a two-part stack: a Python GUI talks to an Arduino over serial, and the Arduino communicates with the battery via OneWire protocol.

```
Tkinter GUI (main.py)
  → Module plugin (modules/*.py)
    → Interface plugin (interfaces/*.py)
      → Serial (pyserial, 9600 baud)
        → Arduino firmware (ArduinoOBI/src/main.cpp)
          → OneWire → Battery BMS
```

### Plugin System

`main.py` dynamically discovers and loads plugins at startup using `pkgutil.iter_modules()`. There are two plugin types:

**Modules** (`OpenBatteryInformation/modules/`): Battery-specific diagnostic logic and UI. Each module file must export:
- `get_display_name()` → string shown in the dropdown
- `ModuleApplication(parent, interface_module, obi_instance)` → tk.Frame subclass
- `set_interface(interface_instance)` method on ModuleApplication

**Interfaces** (`OpenBatteryInformation/interfaces/`): Hardware communication backends. Each interface file must export:
- `get_display_name()` → string shown in the dropdown
- `Interface(parent, obi_instance)` → tk.Frame subclass with a `request(command, max_attempts)` method

### Serial Protocol

Commands sent from Python to Arduino follow the frame format: `[0x01, data_length, response_length, command_type, ...data]`. The Arduino dispatches based on command_type (`0x33` for cmd_and_read_33, `0xCC` for cmd_and_read_cc, `0x01` for version query, `0x31`/`0x32` for F0513 model/version).

### Battery Command Variants

The Makita module (`makita_lxt.py`) supports two battery protocol versions:
- **Standard**: Uses `0xCC`-prefixed commands for model/data reads and `0x33`-prefixed for test mode/resets
- **F0513**: Older version with limited diagnostics (individual cell voltage reads only, no pack voltage in single command)

Detection is automatic: the module tries standard commands first, falls back to F0513 on failure.

## CI/CD

GitHub Actions workflow (`.github/workflows/pyinstaller-windows.yml`) builds a Windows `.exe` on pushes/PRs to `main` and attaches it to tagged releases.
