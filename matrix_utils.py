import asyncio
import re
import ssl
import time
from typing import List, Union

import certifi
import meshtastic.protobuf.portnums_pb2
from nio import (
    AsyncClient,
    AsyncClientConfig,
    MatrixRoom,
    RoomMessageNotice,
    RoomMessageText,
    WhoamiError,
)

from config import relay_config
from log_utils import get_logger

# Do not import plugin_loader here to avoid circular imports
from meshtastic_utils import connect_meshtastic

# Extract Matrix configuration
matrix_homeserver = relay_config["matrix"]["homeserver"]
matrix_rooms: List[dict] = relay_config["matrix_rooms"]
# Use "user_id" for backwards compatibility, but also support "bot_user_id"
matrix_user_id = relay_config["matrix"].get(
    "bot_user_id", relay_config["matrix"].get("user_id")
)
matrix_access_token = relay_config["matrix"]["access_token"]

# Keep bot_user_id for compatibility with previous versions
bot_user_id = matrix_user_id
bot_user_name = None  # Detected upon logon
bot_start_time = int(
    time.time() * 1000
)  # Timestamp when the bot starts, used to filter out old messages

logger = get_logger(name="Matrix")

matrix_client = None

async def connect_matrix():
    """
    Establish a connection to the Matrix homeserver.
    Sets global matrix_client and detects the bot's display name.
    """
    global matrix_client
    global bot_user_name
    if matrix_client:
        return matrix_client

    # Create SSL context using certifi's certificates
    ssl_context = ssl.create_default_context(cafile=certifi.where())

    # Initialize the Matrix client with custom SSL context
    config = AsyncClientConfig(encryption_enabled=False)
    matrix_client = AsyncClient(
        homeserver=matrix_homeserver,
        user=bot_user_id,
        config=config,
        ssl=ssl_context,
    )

    # Set the access_token and user_id
    matrix_client.access_token = matrix_access_token
    matrix_client.user_id = bot_user_id

    # Attempt to retrieve the device_id using whoami()
    whoami_response = await matrix_client.whoami()
    if isinstance(whoami_response, WhoamiError):
        logger.error(f"Failed to retrieve device_id: {whoami_response.message}")
        matrix_client.device_id = None
    else:
        matrix_client.device_id = whoami_response.device_id
        if matrix_client.device_id:
            logger.debug(f"Retrieved device_id: {matrix_client.device_id}")
        else:
            logger.warning("device_id not returned by whoami()")

    # Fetch the bot's display name
    response = await matrix_client.get_displayname(bot_user_id)
    if hasattr(response, "displayname"):
        bot_user_name = response.displayname
    else:
        bot_user_name = bot_user_id  # Fallback if display name is not set

    return matrix_client

async def join_matrix_room(matrix_client, room_id_or_alias: str) -> None:
    """Join a Matrix room by its ID or alias."""
    try:
        if room_id_or_alias.startswith("#"):
            # If it's a room alias, resolve it to a room ID
            response = await matrix_client.room_resolve_alias(room_id_or_alias)
            if not response.room_id:
                logger.error(
                    f"Failed to resolve room alias '{room_id_or_alias}': {response.message}"
                )
                return
            room_id = response.room_id
            # Update the room ID in the matrix_rooms list
            for room_config in matrix_rooms:
                if room_config["id"] == room_id_or_alias:
                    room_config["id"] = room_id
                    break
        else:
            room_id = room_id_or_alias

        # Attempt to join the room if not already joined
        if room_id not in matrix_client.rooms:
            response = await matrix_client.join(room_id)
            if response and hasattr(response, "room_id"):
                logger.info(f"Joined room '{room_id_or_alias}' successfully")
            else:
                logger.error(
                    f"Failed to join room '{room_id_or_alias}': {response.message}"
                )
        else:
            logger.debug(f"Bot is already in room '{room_id_or_alias}'")
    except Exception as e:
        logger.error(f"Error joining room '{room_id_or_alias}': {e}")

async def matrix_relay(
    room_id,
    message,
    longname,
    shortname,
    meshnet_name,
    portnum,
    meshtastic_id=None,
    meshtastic_text=None,
):
    """
    Relay a message from Meshtastic to Matrix.
    """
    matrix_client = await connect_matrix()

    try:
        # Always use our own local meshnet_name for outgoing events
        local_meshnet_name = relay_config["meshtastic"]["meshnet_name"]
        content = {
            "msgtype": "m.text",
            "body": message,
            "meshtastic_longname": longname,
            "meshtastic_shortname": shortname,
            "meshtastic_meshnet": local_meshnet_name,
            "meshtastic_portnum": portnum,
        }
        if meshtastic_id is not None:
            content["meshtastic_id"] = meshtastic_id

        if meshtastic_text is not None:
            content["meshtastic_text"] = meshtastic_text

        await asyncio.wait_for(
            matrix_client.room_send(
                room_id=room_id,
                message_type="m.room.message",
                content=content,
            ),
            timeout=5.0,
        )
        logger.info(f"Sent inbound radio message to matrix room: {room_id}")

    except asyncio.TimeoutError:
        logger.error("Timed out while waiting for Matrix response")
    except Exception as e:
        logger.error(f"Error sending radio message to matrix room {room_id}: {e}")

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
async def on_room_message(
    room: MatrixRoom,
    event: Union[RoomMessageText, RoomMessageNotice],
) -> None:
    """
    Handle new messages in Matrix.
    """

    full_display_name = "Unknown user"
    message_timestamp = event.server_timestamp

    # We do not relay messages that occurred before the bot started
    if message_timestamp < bot_start_time:
        return

    # Find the room_config that matches this room, if any
    room_config = None
    for config in matrix_rooms:
        if config["id"] == room.room_id:
            room_config = config
            break

    # Only proceed if the room is supported
    if not room_config:
        return

    text = event.body.strip() if hasattr(event, "body") else ""

    longname = event.source["content"].get("meshtastic_longname")
    shortname = event.source["content"].get("meshtastic_shortname", None)
    meshnet_name = event.source["content"].get("meshtastic_meshnet")
    suppress = event.source["content"].get("mmrelay_suppress")

    # If a message has suppress flag, do not process
    if suppress:
        return

    local_meshnet_name = relay_config["meshtastic"]["meshnet_name"]

    # For Matrix->Mesh messages from a remote meshnet, rewrite the message format
    if longname and meshnet_name:
        # Always include the meshnet_name in the full display name.
        full_display_name = f"{longname}/{meshnet_name}"

        if meshnet_name != local_meshnet_name:
            # A message from a remote meshnet relayed into Matrix, now going back out
            logger.info(f"Processing message from remote meshnet: {meshnet_name}")
            short_meshnet_name = meshnet_name[:4]
            # If shortname is not available, derive it from the longname
            if shortname is None:
                shortname = longname[:3] if longname else "???"
            # Remove the original prefix "[longname/meshnet]: " to avoid double-tagging
            text = re.sub(rf"^\[{full_display_name}\]: ", "", text)
            text = truncate_message(text)
            full_message = f"{shortname}/{short_meshnet_name}: {text}"
        else:
            # If this message is from our local meshnet (loopback), we ignore it
            return
    else:
        # Normal Matrix message from a Matrix user
        display_name_response = await matrix_client.get_displayname(event.sender)
        full_display_name = display_name_response.displayname or event.sender
        short_display_name = full_display_name[:5]
        prefix = f"{short_display_name}[M]: "
        logger.debug(f"Processing matrix message from [{full_display_name}]: {text}")
        full_message = f"{prefix}{text}"
        text = truncate_message(text)

    # Connect to Meshtastic
    meshtastic_interface = connect_meshtastic()
    from meshtastic_utils import logger as meshtastic_logger

    meshtastic_channel = room_config["meshtastic_channel"]

    # If message is from Matrix and broadcast_enabled is True, relay to Meshtastic
    if event.sender != bot_user_id:
        if relay_config["meshtastic"]["broadcast_enabled"]:
            portnum = event.source["content"].get("meshtastic_portnum")
            if portnum == "DETECTION_SENSOR_APP":
                # If detection_sensor is enabled, forward this data as detection sensor data
                if relay_config["meshtastic"].get("detection_sensor", False):
                    meshtastic_interface.sendData(
                        data=full_message.encode("utf-8"),
                        channelIndex=meshtastic_channel,
                        portNum=meshtastic.protobuf.portnums_pb2.PortNum.DETECTION_SENSOR_APP,
                    )

                else:
                    meshtastic_logger.debug(
                        f"Detection sensor packet received from {full_display_name}, but detection sensor processing is disabled."
                    )
            else:
                meshtastic_logger.info(
                    f"Relaying message from {full_display_name} to radio broadcast"
                )
                meshtastic_interface.sendText(
                    text=full_message, channelIndex=meshtastic_channel
                )
        else:
            logger.debug(
                f"Broadcast not supported: Message from {full_display_name} dropped."
            )
