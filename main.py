"""
This script connects a Meshtastic mesh network to Matrix chat rooms by relaying messages between them.
It uses Meshtastic-python and Matrix nio client library to interface with the radio and the Matrix server respectively.
"""
import asyncio
import time
import logging
import re
import sqlite3
import yaml
import certifi
import ssl
import os
import json
import meshtastic.tcp_interface
import meshtastic.serial_interface
from nio import (
    AsyncClient,
    AsyncClientConfig,
    LoginResponse,
    MatrixRoom,
    RoomMessageText,
    RoomMessageNotice,
)
from pubsub import pub
from yaml.loader import SafeLoader
from typing import List, Union
#from config_editor import load_config

credentials = None

class CustomFormatter(logging.Formatter):
    def __init__(self, fmt=None, datefmt=None, style="%", converter=None):
        super().__init__(fmt, datefmt, style)
        self.converter = converter or time.localtime

    def formatTime(self, record, datefmt=None):
        ct = self.converter(record.created, None)  # Add None as the second argument
        if datefmt:
            s = time.strftime(datefmt, ct)
        else:
            t = time.strftime(self.default_time_format, ct)
            s = self.default_msec_format % (t, record.msecs)
        return s


def utc_converter(timestamp, _):
    return time.gmtime(timestamp)

# Timestamp when the bot starts, used to filter out old messages
bot_start_time = int(time.time() * 1000)

# Load configuration
with open("config.yaml", "r") as f:
    relay_config = yaml.load(f, Loader=SafeLoader)

# Configure logging
logger = logging.getLogger(name="M<>M Relay")
log_level = getattr(logging, relay_config["logging"]["level"].upper())


logger.setLevel(log_level)
logger.propagate = False  # Add this line to prevent double logging

formatter = CustomFormatter(
    fmt="%(asctime)s %(levelname)s:%(name)s:%(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    converter=utc_converter,
)
handler = logging.StreamHandler()
handler.setFormatter(formatter)
logger.addHandler(handler)


# Initialize SQLite database
def initialize_database():
    with sqlite3.connect("meshtastic.sqlite") as conn:
        cursor = conn.cursor()
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS longnames (meshtastic_id TEXT PRIMARY KEY, longname TEXT)")
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS shortnames (meshtastic_id TEXT PRIMARY KEY, shortname TEXT)")
        conn.commit()

async def login_and_save(username, password, homeserver):
    client = AsyncClient(homeserver, username)
    response = await client.login(password)
    if isinstance(response, LoginResponse):
        credentials = {
            "user_id": response.user_id,
            "device_id": response.device_id,
            "access_token": response.access_token,
            "homeserver": homeserver
        }
        with open("credentials.json", "w") as f:
            json.dump(credentials, f)
        print("Login successful. Credentials saved.")
        return client, credentials
    else:
        print("Login failed. Please check your username/password and try again.")
        return None, None


# Get the longname for a given Meshtastic ID
def get_longname(meshtastic_id):
    with sqlite3.connect("meshtastic.sqlite") as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT longname FROM longnames WHERE meshtastic_id=?", (meshtastic_id,))
        result = cursor.fetchone()
    return result[0] if result else None

def get_shortname(meshtastic_id):
    with sqlite3.connect("meshtastic.sqlite") as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT shortname FROM shortnames WHERE meshtastic_id=?", (meshtastic_id,))
        result = cursor.fetchone()
    return result[0] if result else None


def save_longname(meshtastic_id, longname):
    with sqlite3.connect("meshtastic.sqlite") as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO longnames (meshtastic_id, longname) VALUES (?, ?)",
            (meshtastic_id, longname),
        )
        conn.commit()


def save_shortname(meshtastic_id, shortname):
    with sqlite3.connect("meshtastic.sqlite") as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO shortnames (meshtastic_id, shortname) VALUES (?, ?)",
            (meshtastic_id, shortname),
        )
        conn.commit()








def update_longnames():
    if meshtastic_interface.nodes:
        for node in meshtastic_interface.nodes.values():
            user = node.get("user")
            if user:
                meshtastic_id = user["id"]
                longname = user.get("longName", "N/A")
                save_longname(meshtastic_id, longname)


def update_shortnames():
    if meshtastic_interface.nodes:
        for node in meshtastic_interface.nodes.values():
            user = node.get("user")
            if user:
                meshtastic_id = user["id"]
                shortname = user.get("shortName", "N/A")
                save_shortname(meshtastic_id, shortname)


async def join_matrix_room(matrix_client, room_id_or_alias: str) -> None:
    """Join a Matrix room by its ID or alias."""
    try:
        if room_id_or_alias.startswith("#"):
            response = await matrix_client.room_resolve_alias(room_id_or_alias)
            if not response.room_id:
                logger.error(
                    f"Failed to resolve room alias '{room_id_or_alias}': {response.message}"
                )
                return
            room_id = response.room_id
        else:
            room_id = room_id_or_alias

        if room_id not in matrix_client.rooms:
            response = await matrix_client.join(room_id)
            if response and hasattr(response, "room_id"):
                logger.info(f"Joined room '{room_id_or_alias}' successfully")
                update_matrix_room_id(room_id_or_alias, room_id)  # Update the room ID in matrix_rooms
            else:
                logger.error(
                    f"Failed to join room '{room_id_or_alias}': {response.message}"
                )
        else:
            logger.debug(f"Bot is already in room '{room_id_or_alias}'")
    except Exception as e:
        logger.error(f"Error joining room '{room_id_or_alias}': {e}")


# Initialize Meshtastic interface
connection_type = relay_config["meshtastic"]["connection_type"]
if connection_type == "serial":
    serial_port = relay_config["meshtastic"]["serial_port"]
    logger.info(f"Connecting to radio using serial port {serial_port} ...")
    meshtastic_interface = meshtastic.serial_interface.SerialInterface(serial_port)
else:
    target_host = relay_config["meshtastic"]["host"]
    logger.info(f"Connecting to radio at {target_host} ...")
    meshtastic_interface = meshtastic.tcp_interface.TCPInterface(hostname=target_host)

matrix_client = None

# Get the rooms from the config
matrix_rooms: List[dict] = relay_config["matrix_rooms"]

def update_matrix_room_id(room_id_or_alias: str, resolved_room_id: str):
    for room in matrix_rooms:
        if room["id"] == room_id_or_alias:
            room["id"] = resolved_room_id
            break


# Send message to the Matrix room
async def matrix_relay(matrix_client, room_id, message, longname, shortname, meshnet_name):
    try:
        content = {
            "msgtype": "m.text",
            "body": message,
            "meshtastic_longname": longname,
            "meshtastic_shortname": shortname,
            "meshtastic_meshnet": meshnet_name,
        }
        await asyncio.wait_for(
            matrix_client.room_send(
                room_id=room_id,
                message_type="m.room.message",
                content=content,
            ),
            timeout=0.5,
        )
        logger.info(f"Sent inbound radio message to matrix room: {room_id}")

    except asyncio.TimeoutError:
        logger.error("Timed out while waiting for Matrix response")
    except Exception as e:
        logger.error(f"Error sending radio message to matrix room {room_id}: {e}")


# Callback for new messages from Meshtastic
def on_meshtastic_message(packet, loop=None):
    sender = packet["fromId"]

    if "text" in packet["decoded"] and packet["decoded"]["text"]:
        text = packet["decoded"]["text"]

        if "channel" in packet:
            channel = packet["channel"]
        else:
            if packet["decoded"]["portnum"] == "TEXT_MESSAGE_APP":
                channel = 0
            else:
                logger.debug("Unknown packet")
                return

        # Check if the channel is mapped to a Matrix room in the configuration
        channel_mapped = False
        for room in matrix_rooms:
            if room["meshtastic_channel"] == channel:
                channel_mapped = True
                break

        if not channel_mapped:
            logger.debug(f"Skipping message from unmapped channel {channel}")
            return

        logger.info(f"Processing inbound radio message from {sender} on channel {channel}")

        longname = get_longname(sender) or sender
        shortname = get_shortname(sender) or sender
        meshnet_name = relay_config["meshtastic"]["meshnet_name"]

        formatted_message = f"[{longname}/{meshnet_name}]: {text}"
        logger.info(f"Relaying Meshtastic message from {longname} to Matrix: {formatted_message}")

        for room in matrix_rooms:
            if room["meshtastic_channel"] == channel:
                asyncio.run_coroutine_threadsafe(
                    matrix_relay(
                        matrix_client,
                        room["id"],
                        formatted_message,
                        longname,
                        shortname,
                        meshnet_name,
                    ),
                    loop=loop,
                )
    else:
        portnum = packet["decoded"]["portnum"]
        if portnum == "TELEMETRY_APP":
            logger.debug("Ignoring Telemetry packet")
        elif portnum == "POSITION_APP":
            logger.debug("Ignoring Position packet")
        elif portnum == "ADMIN_APP":
            logger.debug("Ignoring Admin packet")
        else:
            logger.debug("Ignoring Unknown packet")


def truncate_message(text, max_bytes=227):
    """
    Truncate the given text to fit within the specified byte size.

    :param text: The text to truncate.
    :param max_bytes: The maximum allowed byte size for the truncated text.
    :return: The truncated text.
    """
    truncated_text = text.encode("utf-8")[:max_bytes].decode("utf-8", "ignore")
    return truncated_text


# Callback for new messages in Matrix room
async def on_room_message(room: MatrixRoom, event: Union[RoomMessageText, RoomMessageNotice]) -> None:

    global credentials  # Now we're using the global variable 'credentials'
    if not credentials or event.sender == credentials['user_id']:
        return  # Skip processing if we have no credentials or if the message is from the bot itself


    bot_user_id = credentials['user_id'] if credentials else None

    full_display_name = "Unknown user"
    
    if event.sender != credentials['user_id']:
        message_timestamp = event.server_timestamp

        if message_timestamp > bot_start_time:
            text = event.body.strip()

            longname = event.source["content"].get("meshtastic_longname")
            shortname = event.source["content"].get("meshtastic_shortname", None)
            meshnet_name = event.source["content"].get("meshtastic_meshnet")
            local_meshnet_name = relay_config["meshtastic"]["meshnet_name"]

            if longname and meshnet_name:
                full_display_name = f"{longname}/{meshnet_name}"
                if meshnet_name != local_meshnet_name:
                    logger.info(f"Processing message from remote meshnet: {text}")
                    short_meshnet_name = meshnet_name[:4]

                    # If shortname is None, truncate the longname to 3 characters
                    if shortname is None:
                        shortname = longname[:3]
                    prefix = f"{shortname}/{short_meshnet_name}: "
                    text = re.sub(rf"^\[{full_display_name}\]: ", "", text)  # Remove the original prefix from the text
                    text = truncate_message(text)
                    full_message = f"{prefix}{text}"
                else:
                    # This is a message from a local user, it should be ignored no log is needed
                    return
            else:
                display_name_response = await matrix_client.get_displayname(
                    event.sender
                )
                full_display_name = display_name_response.displayname or event.sender
                short_display_name = full_display_name[:5]
                prefix = f"{short_display_name}[M]: "
                logger.info(f"Processing matrix message from [{full_display_name}]: {text}")
                text = truncate_message(text)
                full_message = f"{prefix}{text}"

            room_config = None
            for config in matrix_rooms:
                if config["id"] == room.room_id:
                    room_config = config
                    break

            if room_config:
                meshtastic_channel = room_config["meshtastic_channel"]

                if relay_config["meshtastic"]["broadcast_enabled"]:
                    logger.info(
                        f"Sending radio message from {full_display_name} to radio broadcast"
                    )
                    meshtastic_interface.sendText(text=full_message, channelIndex=meshtastic_channel
                    )
                else:
                    logger.debug(
                        f"Broadcast not supported: Message from {full_display_name} dropped."
                    )


async def main():
    global matrix_client, credentials

    # Initialize the SQLite database
    initialize_database()

    # Create SSL context using certifi's certificates
    ssl_context = ssl.create_default_context(cafile=certifi.where())

    # Check if credentials.json exists
    if os.path.isfile("credentials.json"):
        # Load existing credentials
        with open("credentials.json", "r") as f:
            credentials = json.load(f)
    else:
        # Prompt the user for their username, password, and homeserver
        print("First time setup detected.")
        print("(Note: You must have already created a bot user account separate from your personal Matrix account.)")
        print("Please enter the following information:")
        homeserver = input("Bot user's Matrix homeserver URL: ")
        username = input("Bot user's Matrix username: ")
        password = input("Bot user's Matrix password: ")


        # Call the login_and_save function and await its response
        matrix_client, new_credentials = await login_and_save(username, password, homeserver)
        
        if matrix_client is None:
            print("Could not log in with the provided credentials.")
            return  # Exit the function if login failed
        credentials = new_credentials  # Update the global credentials with the new ones

    # Configure the Matrix client
    config = AsyncClientConfig(encryption_enabled=False)
    matrix_client = AsyncClient(
        credentials["homeserver"], credentials["user_id"], config=config, ssl=ssl_context
    )
    matrix_client.restore_login(
        user_id=credentials["user_id"],
        device_id=credentials["device_id"],
        access_token=credentials["access_token"]
    )

    # Register the message callback with bot_user_id
    matrix_client.add_event_callback(
        on_room_message, 
        (RoomMessageText, RoomMessageNotice)
    )

    # Get the rooms from the config
    matrix_rooms: List[dict] = relay_config["matrix_rooms"]

    # Join the rooms specified in the config.yaml
    for room in matrix_rooms:
        await join_matrix_room(matrix_client, room["id"])

    # Register the Meshtastic message callback
    logger.info("Listening for inbound radio messages ...")
    pub.subscribe(
        on_meshtastic_message, "meshtastic.receive", loop=asyncio.get_event_loop()
    )

    # Start the Matrix client
    while True:
        try:
            # Update longname & shortname
            update_longnames()
            update_shortnames()

            logger.info("Syncing with Matrix server...")
            await matrix_client.sync_forever(timeout=30000)
            logger.info("Sync completed.")
        except Exception as e:
            logger.error(f"Error syncing with Matrix server: {e}")

        await asyncio.sleep(60)  # Update longnames every 60 seconds

asyncio.run(main())