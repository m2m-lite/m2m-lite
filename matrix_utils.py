import asyncio
import ssl
import time
import re
from typing import Union

from nio import (
    AsyncClient,
    AsyncClientConfig,
    MatrixRoom,
    RoomMessageText,
    RoomMessageNotice,
)
from pubsub import pub

from config import relay_config
from log_utils import get_logger

matrix_logger = get_logger("Matrix")

# Use module-level variables
matrix_client = None
matrix_event_loop = None  # Will be set in main()

# Timestamp when the bot starts, used to filter out old messages
bot_start_time = int(time.time() * 1000)

async def connect_matrix():
    """
    Connect to the Matrix server.
    """
    global matrix_client
    global bot_user_name

    matrix_server = relay_config["matrix"]["homeserver"]
    access_token = relay_config["matrix"]["access_token"]
    user_id = relay_config["matrix"]["user_id"]

    ssl_context = ssl.create_default_context()

    config = AsyncClientConfig(encryption_enabled=False, store_sync_tokens=True)
    matrix_client = AsyncClient(
        matrix_server,
        user_id,
        config=config,
        ssl=ssl_context,
    )
    matrix_client.access_token = access_token

    try:
        # Sync to verify connection
        await matrix_client.sync(timeout=3000)
        matrix_logger.info("Connected to Matrix server.")

        # Get bot's display name
        response = await matrix_client.get_displayname(user_id)
        bot_user_name = response.displayname

        # Register the message callback
        matrix_client.add_event_callback(
            on_room_message,
            (RoomMessageText, RoomMessageNotice),
        )

        # Subscribe to Meshtastic messages
        pub.subscribe(handle_meshtastic_relay, "meshtastic.send_to_matrix")

    except Exception as e:
        matrix_logger.error(f"Failed to connect to Matrix server: {e}")
        matrix_client = None  # Ensure matrix_client is set to None
        return None

    return matrix_client

async def join_matrix_rooms():
    """
    Join the Matrix rooms specified in the configuration.
    """
    matrix_rooms = relay_config["matrix_rooms"]
    for room in matrix_rooms:
        await join_matrix_room(room["id"])

async def join_matrix_room(room_id_or_alias: str) -> None:
    """Join a Matrix room by its ID or alias."""
    try:
        if room_id_or_alias.startswith("#"):
            response = await matrix_client.room_resolve_alias(room_id_or_alias)
            if not response.room_id:
                matrix_logger.error(
                    f"Failed to resolve room alias '{room_id_or_alias}': {response.message}"
                )
                return
            room_id = response.room_id
            update_matrix_room_id(room_id_or_alias, room_id)
        else:
            room_id = room_id_or_alias

        if room_id not in matrix_client.rooms:
            response = await matrix_client.join(room_id)
            if response and hasattr(response, "room_id"):
                matrix_logger.info(f"Joined room '{room_id_or_alias}' successfully")
                update_matrix_room_id(room_id_or_alias, room_id)
            else:
                matrix_logger.error(
                    f"Failed to join room '{room_id_or_alias}': {response.message}"
                )
        else:
            matrix_logger.debug(f"Bot is already in room '{room_id_or_alias}'")
    except Exception as e:
        matrix_logger.error(f"Error joining room '{room_id_or_alias}': {e}")

def update_matrix_room_id(room_id_or_alias: str, resolved_room_id: str):
    matrix_rooms = relay_config["matrix_rooms"]
    for room in matrix_rooms:
        if room["id"] == room_id_or_alias:
            room["resolved_id"] = resolved_room_id
            break

def get_room_id(room_id_or_alias: str) -> str:
    """
    Get the resolved room ID for a given room ID or alias.
    """
    matrix_rooms = relay_config["matrix_rooms"]
    for room in matrix_rooms:
        if room["id"] == room_id_or_alias or room.get("resolved_id") == room_id_or_alias:
            return room.get("resolved_id", room["id"])
    return room_id_or_alias  # Return original if not found

async def matrix_relay(room_id_or_alias, message, longname, shortname, meshnet_name):
    room_id = get_room_id(room_id_or_alias)
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
            timeout=5.0,
        )
        matrix_logger.info(f"Sent inbound radio message to matrix room: {room_id}")
    except asyncio.TimeoutError:
        matrix_logger.error("Timed out while waiting for Matrix response")
    except Exception as e:
        matrix_logger.error(f"Error sending radio message to matrix room {room_id}: {e}")

def handle_meshtastic_relay(room_id, message, longname, shortname, meshnet_name):
    if matrix_event_loop is None:
        matrix_logger.error("matrix_event_loop is None")
        return
    matrix_logger.debug(f"handle_meshtastic_relay called with room_id={room_id}, message='{message}'")
    asyncio.run_coroutine_threadsafe(
        matrix_relay(
            room_id,
            message,
            longname,
            shortname,
            meshnet_name,
        ),
        loop=matrix_event_loop,
    )

def truncate_message(text, max_bytes=227):
    """
    Truncate the given text to fit within the specified byte size.
    """
    truncated_text = text.encode("utf-8")[:max_bytes].decode("utf-8", "ignore")
    return truncated_text

async def on_room_message(room: MatrixRoom, event: Union[RoomMessageText, RoomMessageNotice]) -> None:
    if event.sender == matrix_client.user_id:
        return  # Skip processing if the message is from the bot itself

    full_display_name = "Unknown user"

    message_timestamp = event.server_timestamp

    if message_timestamp < bot_start_time:
        # Ignore old messages
        return

    text = event.body.strip()

    # Handle events with missing or malformed content
    try:
        longname = event.source["content"].get("meshtastic_longname")
        shortname = event.source["content"].get("meshtastic_shortname", None)
        meshnet_name = event.source["content"].get("meshtastic_meshnet")
    except AttributeError:
        # Handle cases where 'content' is None or missing expected keys
        longname = None
        shortname = None
        meshnet_name = None

    local_meshnet_name = relay_config["meshtastic"]["meshnet_name"]

    if longname and meshnet_name:
        full_display_name = f"{longname}/{meshnet_name}"
        if meshnet_name != local_meshnet_name:
            matrix_logger.info(f"Processing message from remote meshnet: {text}")
            short_meshnet_name = meshnet_name[:4]

            if shortname is None:
                shortname = longname[:3]
            prefix = f"{shortname}/{short_meshnet_name}: "
            text = re.sub(rf"^\[{re.escape(full_display_name)}\]: ", "", text)
            text = truncate_message(text)
            full_message = f"{prefix}{text}"
        else:
            return
    else:
        display_name_response = await matrix_client.get_displayname(
            event.sender
        )
        full_display_name = display_name_response.displayname or event.sender
        short_display_name = full_display_name[:5]
        prefix = f"{short_display_name}[M]: "
        matrix_logger.info(f"Processing matrix message from [{full_display_name}]: {text}")
        text = truncate_message(text)
        full_message = f"{prefix}{text}"

    room_config = None
    for config in relay_config["matrix_rooms"]:
        if get_room_id(config["id"]) == room.room_id:
            room_config = config
            break

    if room_config:
        meshtastic_channel = room_config["meshtastic_channel"]

        if relay_config["meshtastic"].get("broadcast_enabled", True):
            matrix_logger.info(
                f"Sending radio message from {full_display_name} to radio broadcast"
            )
            matrix_logger.debug(f"Publishing message to Meshtastic: {full_message}")
            pub.sendMessage("matrix.send_to_meshtastic", text=full_message, channelIndex=meshtastic_channel)
        else:
            matrix_logger.debug(
                f"Broadcast not supported: Message from {full_display_name} dropped."
            )
