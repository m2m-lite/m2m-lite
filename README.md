# Meshtastic <=> Matrix Relay (Lite)

A powerful (yet lightweight!) and easy-to-use relay between Meshtastic devices and Matrix chat rooms, allowing seamless communication across platforms. This opens the door for bridging Meshtastic devices to [many other platforms](https://matrix.org/bridges/).

A lightweight fork of:
<https://github.com/geoffwhittington/meshtastic-matrix-relay>

## Features

- Bidirectional message relay between Meshtastic devices and Matrix chat rooms, capable of supporting multiple meshnets
- Supports serial, BLE, and network connections for Meshtastic devices
- Custom keys are embedded in Matrix messages which are used when relaying messages between two or more meshnets.
- Truncates long messages to fit within Meshtastic's payload size
- SQLite database to store Meshtastic longnames and shortnames for improved functionality
- Customizable logging level for easy debugging
- Configurable through a simple YAML file
- Supports mapping multiple rooms and channels 1:1
- Now uses Meshtastic shortnames when relaying messages from remote meshnets
- Refactored session management to pave the way for Matrix E2EE support
- Robust connection handling with automatic reconnections
- Detection sensor data forwarding
- Logging to file

## Custom Keys in Matrix Messages

This relay utilizes custom keys in Matrix messages. When a message is received from a remote meshnet, the relay includes the sender's longname, shortname, and the meshnet name as custom keys in the Matrix message. This metadata helps identify the source of the message and provides context for users in the Matrix chat room.

Example message format with custom keys:

```json
{
  "msgtype": "m.text",
  "body": "[Alice/VeryCoolMeshnet]: Hello from my very cool meshnet!",
  "meshtastic_longname": "Alice",
  "meshtastic_meshnet": "VeryCoolMeshnet",
  "meshtastic_shortname": "Ally"
}
```

## Installation

Clone the repository:

```bash
git clone https://github.com/m2m-lite/m2m-lite.git
cd m2m-lite
```

### Setup

Create a Python virtual environment in the project directory:

```bash
python3 -m venv .pyenv
```

Activate the virtual environment and install dependencies:

```bash
source .pyenv/bin/activate
pip install -r requirements.txt
```

### Configuration

Create a `config.yaml` in the project directory with the appropriate values. A sample configuration is provided below:

```yaml
# m2m-lite Configuration

# --- Matrix Settings ---
matrix:
  homeserver: https://matrix.org # Your Matrix homeserver URL
  # user_id and access_token only needed for backwards compatibility
  # user_id: "@your-user:matrix.org"
  # access_token: "YOUR_ACCESS_TOKEN"

# --- Matrix Rooms ---
# Define the Matrix rooms where the bot will operate and the corresponding Meshtastic channels.
# You need at least one room and channel, but you can add more.
matrix_rooms:
  - id: "#m2m-test:matrix.org" # The Matrix room ID or alias (e.g., #myroom:matrix.org)
    meshtastic_channel: 0 # The Meshtastic channel index (0 for the primary channel)
  - id: "!anotherroomid:matrix.org" # You can use room IDs directly as well
    meshtastic_channel: 2 # Example: Meshtastic channel index 2

# --- Meshtastic Settings ---
meshtastic:
  connection_type: serial # Choose the connection type: "serial", "ble", or "network"
  serial_port: /dev/ttyUSB0 # The serial port of your Meshtastic device (e.g., /dev/ttyUSB0, COM3) - Required for "serial" connection
  ble_address: XX:XX:XX:XX:XX:XX # The Bluetooth MAC address of your Meshtastic device - Required for "ble" connection
  host: meshtastic.local # The hostname or IP address of your Meshtastic device - Required for "network" connection
  meshnet_name: MESHNET # A name for your Meshtastic mesh network (will be displayed in Matrix messages)
  broadcast_enabled: true # Set to 'true' to relay messages to the Meshtastic network, 'false' otherwise
  detection_sensor: false # Set to 'true' to enable relaying of detection sensor data, 'false' otherwise

# --- Logging Settings ---
logging:
  level: INFO # The logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
  log_to_file: true # Set to 'true' to log to a file, 'false' to log only to the console
  log_file: m2m-lite.log # The name of the log file (if log_to_file is true)
```

## Usage

Activate the virtual environment:

```bash
source .pyenv/bin/activate
```

Run the `main.py` script:

```bash
python main.py
```

Example output:

```text
$ python main.py
2023-11-09 20:47:36.000 INFO:Meshtastic:Connecting to radio at /dev/ttyACM0 ...
First time setup detected.
Matrix homeserver URL (e.g., server.com or https://server.com): matrix.org
Matrix username: matrixmeshbot
Matrix password:
Login successful. Credentials saved.
2023-11-09 20:47:56.000 INFO:Matrix:Joined room '#m2m-test:matrix.org' successfully
2023-11-09 20:47:57.000 INFO:Meshtastic:Connected to MyRadio/T-Beam
2023-11-09 20:47:57.000 INFO:Matrix:Listening for inbound radio messages ...
2023-11-09 20:47:57.000 INFO:Matrix:Starting Matrix sync loop...
2023-11-09 20:48:03.000 INFO:Matrix:Processing matrix message from @bob:matrix.org: Hi Alice!
2023-11-09 20:48:03.000 INFO:Matrix:Sending radio message from Bob to radio broadcast
2023-11-09 20:48:49.000 INFO:Meshtastic:Processing inbound radio message from !613501e4 on channel 0
2023-11-09 20:48:49.000 INFO:Meshtastic:Relaying Meshtastic message from Alice to Matrix: [Alice/MESHNET]: Hey Bob!
2023-11-09 20:48:49.000 INFO:Matrix:Sent inbound radio message to matrix room: #m2m-test:matrix.org
```

After the first login, session details are then saved to `credentials.json` for future use.

```json
{
  "user_id": "@matrixmeshbot:matrix.org",
  "access_token": "syt_xxxxx",
  "homeserver": "https://matrix.org"
}
```
