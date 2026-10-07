# Master Architecture Prompt: KNACKSAT OBC SpaceFruit

This document serves as the master architecture reference for the KNACKSAT OBC SpaceFruit project. It outlines the system components, communication protocols, deployment pipeline, and testing environments. Next agents should use this as context when implementing further improvements.

## 1. System Overview
The KNACKSAT OBC SpaceFruit project is a satellite On-Board Computer (OBC) firmware built for an STM32 microcontroller, coupled with a robust suite of Python-based subsystem emulators. The system includes an Electrical Power System (EPS) and a Virtual Reality (VR) Payload. Communication across the system heavily relies on the KISS protocol over Serial/UART.

## 2. Hardware and Deployment Pipeline
The development and testing environment is structured into three main layers:

*   **Host Machine**: The developer's primary machine where code is written and compiled.
*   **HIL (Hardware-In-the-Loop) Machine**: A Raspberry Pi (or similar Linux machine) physically connected to the STM32 board via serial interfaces. It runs the emulator scripts (`eps.py` and `vr.py`) to simulate external satellite components.
*   **Target Board**: The STM32 microcontroller running the actual OBC firmware (`main.c`).

### Deployment Scripts:
*   `unison_sync.sh`: Syncs the payload emulator (`vr.py`) and ground station core (`gs_core.py`) from the Host machine to the remote HIL machine via SSH.
*   `program.sh`: Compiles the STM32 firmware (`make`) and flashes it to the board using `openocd`. It supports remote flashing (`--remote`) through the HIL machine.

## 3. Core Firmware Architecture (`Core/Src/main.c`)
The STM32 firmware is built on FreeRTOS and manages the core satellite operations.
*   **Tasks**: Features dedicated threads including `mainTask`, `usbTask`, `sensorQueryTask`, `uartRx`, and `printTask`.
*   **Interfaces**: 
    *   Ground Station communication via UART4 (or USB CDC).
    *   EPS communication via UART2.
    *   Storage via SPI1 (SD Card) and SPI2 (NOR Flash).
*   **Protocols**: Implements KISS protocol wrappers to serialize and route packets reliably over UART.
*   **Modular Submodules**: The project uses git submodules for reusability:
    *   `obc-drivers`: Hardware drivers including `mt25ql` (NOR flash), `rv3028c7` (RTC), and `tmp1075` (Temperature sensor).
    *   `obc-protocols`: Protocol definitions for `kiss_protocol`, `eps_protocol`, and `payload_protocol`.
    *   `littlefs`: Lightweight fail-safe file system for the NOR flash.

## 4. Ground Station Emulation
*   `subsystem_emulators/gs_core.py`: The core ground station backend. It connects to the OBC via Serial, parses incoming KISS frames (like EPS beacons), and exposes a TCP server for clients. Handles complex logic like automatic chunked file downloading and retries.
*   `subsystem_emulators/gs_cli.py`: The frontend command-line interface that connects to `gs_core.py` over TCP to issue manual commands (Ping, List Files, Download, Capture, Status).

## 5. Subsystem Emulators
When testing without physical hardware, Python emulators simulate the behavior of various satellite subsystems.

### 5.1 VR Payload Emulator (`eps_and_payload_emulator/kiss_file_transfer/vr.py`)
*   **Role**: Simulates the VR camera payload.
*   **Execution**: Runs on the HIL machine connected to the actual STM32 board.
*   **Capabilities**: Responds to Pings, returns Pi hardware telemetry (CPU, RAM, Temp, Disk usage) to simulate payload status (`VR_PID_PI_STATUS`), triggers image captures, and serves images back to the OBC via chunked transfer.

### 5.2 EPS Emulator (`eps_and_payload_emulator/OBC_EPS_Script/eps.py`)
*   **Role**: Simulates the Electrical Power System (EPS).
*   **Execution**: Runs on the HIL machine connected to the actual STM32 board.
*   **Capabilities**: Listens for EPS-specific KISS frames. Responds to telemetry polling with simulated data for Solar Voltage/Current, Output Power, Battery Temperatures, and allows toggling virtual power switches.

### 5.3 OBC Emulator (`subsystem_emulators/OBC.py`)
*   **Role**: Simulates the STM32 hardware itself for pure software-in-the-loop testing of the Ground Station.
*   **Capabilities**: Receives requests from the Ground Station, parses the custom payload, and correctly routes to either the virtual `OBC_SUBSYSTEM` (0x00) or `VR_SUBSYSTEM` (0x01). It can mock SD card file systems, broadcast dummy EPS beacons, and stream dummy file chunks.

### 5.4 Traffic Sniffer (`subsystem_emulators/Sniffer.py`)
*   **Role**: Passive serial traffic monitor.
*   **Capabilities**: Listens on a serial port and decodes raw KISS frames in real-time, providing colorized output of protocols, payloads, file transfers, and EPS beacons for debugging communication between the OBC, Ground Station, and Emulators.

