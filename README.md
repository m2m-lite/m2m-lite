# Meshtastic <=> Matrix Relay (Lite)

A powerful (yet lightweight!) and easy-to-use relay between Meshtastic devices and Matrix chat rooms, allowing seamless communication across platforms. This opens the door for bridging Meshtastic devices to [many other platforms](https://matrix.org/bridges/).

A lightweight fork of:
https://github.com/geoffwhittington/meshtastic-matrix-relay

## Features

- Bidirectional message relay between Meshtastic devices and Matrix chat rooms, capable of supporting multiple meshnets
- Supports both serial and network connections for Meshtastic devices
- Custom keys are embedded in Matrix messages which are used when relaying messages between two or more meshnets.
- Truncates long messages to fit within Meshtastic's payload size
- SQLite database to store Meshtastic longnames for improved functionality
- Customizable logging level for easy debugging
- Configurable through a simple YAML file
- Supports mapping multiple rooms and channels 1:1
- **New:** Now uses Meshtastic shortnames when relaying messages from remote meshnets
- **New:** Refactored session management to pave the way for Matrix E2EE support

## Custom Keys in Matrix Messages

This relay utilizes custom keys in Matrix messages. When a message is received from a remote meshnet, the relay includes the sender's longname and the meshnet name as custom keys in the Matrix message. This metadata helps identify the source of the message and provides context for users in the Matrix chat room.

Example message format with custom keys:

```
{
"msgtype": "m.text",
"body": "[Alice/VeryCoolMeshnet]: Hello from my very cool meshnet!",
"meshtastic_longname": "Alice",
"meshtastic_meshnet": "VeryCoolMeshnet"
"meshtastic_shortname": "Ally"
}
```

## Installation

Clone the repository:

```
git clone https://github.com/m2m-lite/m2m-lite.git
```

### Setup

Create a Python virtual environment in the project directory:

```
python3 -m venv .pyenv
```

Activate the virtual environment and install dependencies:

```
source .pyenv/bin/activate
pip install -r requirements.txt
```


### Configuration

Create a `config.yaml` in the project directory with the appropriate values. A sample configuration is provided below:

```yaml
matrix_rooms:  # Needs at least 1 room & channel, but supports all Meshtastic channels
  - id: "!someroomid:example.matrix.org"
    meshtastic_channel: 0
  - id: "!someroomid2:example.matrix.org"
    meshtastic_channel: 2

meshtastic:
  connection_type: serial  # Choose either "network" or "serial"
  serial_port: /dev/ttyUSB0  # Only used when connection is "serial"
  host: "meshtastic.local" # Only used when connection is "network"
  meshnet_name: "VeryCoolMeshnet" # This is displayed in full on Matrix, but is truncated when sent to a Meshnet
  broadcast_enabled: true

logging:
  level: "info"
  show_timestamps: true
  timestamp_format: '[%H:%M:%S]'
```

## Usage
Activate the virtual environment:
```
source .pyenv/bin/activate
```
Run the `main.py` script:
```
python main.py
```
Example output:
```

$ python main.py
2023-11-09 20:47:36 INFO:M<>M Relay:Connecting to radio using serial port /dev/ttyACM0 ...
First time setup detected.
Matrix homeserver URL (e.g., server.com or https://server.com): matrix.org
Matrix username: matrixmeshbot
Matrix password: 
Login successful. Credentials saved.
2023-11-09 20:47:56 INFO:M<>M Relay:Joined room '#meshtastic-matrix-relay:matrix.org' successfully
2023-11-09 20:47:57 INFO:M<>M Relay:Listening for inbound radio messages ...
2023-11-09 20:47:57 INFO:M<>M Relay:Syncing with Matrix server...
2023-11-09 20:48:03 INFO:M<>M Relay:Processing matrix message from @bob:matrix.org: Hi Alice!
2023-11-09 20:48:03 INFO:M<>M Relay:Sending radio message from Bob to radio broadcast
2023-11-09 20:48:49 INFO:M<>M Relay:Processing inbound radio message from !613501e4 on channel 0
2023-11-09 20:48:49 INFO:M<>M Relay:Relaying Meshtastic message from Alice to Matrix: [Alice/VeryCoolMeshnet]: Hey Bob!
2023-11-09 20:48:49 INFO:M<>M Relay:Sent inbound radio message to matrix room: !NrCTURbZDMWKMrTpFH:matrix.org
```



After the first login, session details are then saved to *credentials.json* for future use.
```
{"user_id": "@matrixmeshbot:matrix.org", "device_id": "THTNYIVVLX", "access_token": "syt_xxxxx, "homeserver": "https://matrix.org"}
```