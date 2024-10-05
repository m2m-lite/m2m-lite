import asyncio
import re
from typing import Union

from nio import MatrixRoom, RoomMessageText, RoomMessageNotice

from config import relay_config
from db_utils import get_longname, get_shortname
from log_utils import get_logger
from meshtastic_utils import meshtastic_interface
from matrix_utils import matrix_client

message_logger = get_logger("MessageHandler")

# Timestamp when the bot starts, used to filter out old messages
bot_start_time = int(time.time() * 1000)

def truncate_message(text, max_bytes=227):
    """
    Truncate the given text to fit within the specified byte size.
    """
    truncated_text = text.encode("utf-8")[:max_bytes].decode("utf-8", "ignore")
    return truncated_text

async def matrix_relay(room_id, message, longname, shortname, meshnet_name):
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
        message_logger.info(f"Sent inbound radio message to matrix room: {room_id}")

    except asyncio.TimeoutError:
        message_logger.error("Timed out while waiting for Matrix response")
    except Exception as e:
        message_logger.error(f"Error sending radio message to matrix room {room_id}: {e}")

async def handle_meshtastic_message(packet):
    sender = packet["fromId"]

    if "text" in packet["decoded"] and packet["decoded"]["text"]:
        text = packet["decoded"]["text"]

        if "channel" in packet:
            channel = packet["channel"]
        else:
            if packet["decoded"]["portnum"] == "TEXT_MESSAGE_APP":
                channel = 0
            else:
                message_logger.debug("Unknown packet")
                return

        # Check if the channel is mapped to a Matrix room in the configuration
        channel_mapped = False
        for room in relay_config["matrix_rooms"]:
            if room["meshtastic_channel"] == channel:
                channel_mapped = True
                break

        if not channel_mapped:
            message_logger.debug(f"Skipping message from unmapped channel {channel}")
            return

        message_logger.info(f"Processing inbound radio message from {sender} on channel {channel}")

        longname = get_longname(sender) or sender
        shortname = get_shortname(sender) or sender
        meshnet_name = relay_config["meshtastic"]["meshnet_name"]

        formatted_message = f"[{longname}/{meshnet_name}]: {text}"
        message_logger.info(f"Relaying Meshtastic message from {longname} to Matrix: {formatted_message}")

        for room in relay_config["matrix_rooms"]:
            if room["meshtastic_channel"] == channel:
                asyncio.run_coroutine_threadsafe(
                    matrix_relay(
                        room["id"],
                        formatted_message,
                        longname,
                        shortname,
                        meshnet_name,
                    ),
                    loop=asyncio.get_event_loop(),
                )
    else:
        portnum = packet["decoded"]["portnum"]
        if portnum == "TELEMETRY_APP":
            message_logger.debug("Ignoring Telemetry packet")
        elif portnum == "POSITION_APP":
            message_logger.debug("Ignoring Position packet")
        elif portnum == "ADMIN_APP":
            message_logger.debug("Ignoring Admin packet")
        else:
            message_logger.debug("Ignoring Unknown packet")

async def on_room_message(room: MatrixRoom, event: Union[RoomMessageText, RoomMessageNotice]) -> None:
    if event.sender == matrix_client.user:
        return  # Skip processing if the message is from the bot itself

    full_display_name = "Unknown user"

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
                message_logger.info(f"Processing message from remote meshnet: {text}")
                short_meshnet_name = meshnet_name[:4]

                if shortname is None:
                    shortname = longname[:3]
                prefix = f"{shortname}/{short_meshnet_name}: "
                text = re.sub(rf"^\[{full_display_name}\]: ", "", text)
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
            message_logger.info(f"Processing matrix message from [{full_display_name}]: {text}")
            text = truncate_message(text)
            full_message = f"{prefix}{text}"

        room_config = None
        for config in relay_config["matrix_rooms"]:
            if config["id"] == room.room_id:
                room_config = config
                break

        if room_config:
            meshtastic_channel = room_config["meshtastic_channel"]

            if relay_config["meshtastic"]["broadcast_enabled"]:
                message_logger.info(
                    f"Sending radio message from {full_display_name} to radio broadcast"
                )
                meshtastic_interface.sendText(
                    text=full_message, channelIndex=meshtastic_channel
                )
            else:
                message_logger.debug(
                    f"Broadcast not supported: Message from {full_display_name} dropped."
                )
