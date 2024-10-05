import asyncio
import threading
import time

import meshtastic.tcp_interface
import meshtastic.serial_interface
import serial.tools.list_ports
from pubsub import pub

from config import relay_config
from db_utils import save_longname, save_shortname, get_longname, get_shortname
from log_utils import get_logger

meshtastic_logger = get_logger("Meshtastic")

# Use module-level variables
meshtastic_interface = None
meshtastic_event_loop = None  # Will be set in main()
meshtastic_lock = threading.Lock()
reconnecting = False
shutting_down = False
reconnect_task = None

def serial_port_exists(port_name):
    """
    Check if the specified serial port exists.
    """
    ports = [port.device for port in serial.tools.list_ports.comports()]
    return port_name in ports

async def connect_meshtastic(force_connect=False):
    """
    Establish a connection to the Meshtastic device.
    """
    global meshtastic_interface, shutting_down, reconnecting, meshtastic_event_loop

    if shutting_down:
        meshtastic_logger.info("Shutdown in progress. Not attempting to connect.")
        return None

    with meshtastic_lock:
        if meshtastic_interface and not force_connect:
            return meshtastic_interface

        # Close existing connection if any
        if meshtastic_interface:
            try:
                meshtastic_interface.close()
            except Exception as e:
                meshtastic_logger.warning(f"Error closing previous connection: {e}")
            meshtastic_interface = None

        connection_type = relay_config["meshtastic"]["connection_type"]
        retry_limit = 0  # 0 for infinite retries
        attempts = 1
        successful = False

        while not successful and (retry_limit == 0 or attempts <= retry_limit) and not shutting_down:
            try:
                if connection_type == "serial":
                    serial_port = relay_config["meshtastic"]["serial_port"]
                    meshtastic_logger.info(f"Connecting to serial port {serial_port} ...")

                    # Check if serial port exists
                    if not serial_port_exists(serial_port):
                        meshtastic_logger.warning(f"Serial port {serial_port} does not exist. Waiting...")
                        await asyncio.sleep(5)
                        attempts += 1
                        continue

                    meshtastic_interface = meshtastic.serial_interface.SerialInterface(serial_port)
                else:
                    target_host = relay_config["meshtastic"]["host"]
                    meshtastic_logger.info(f"Connecting to radio at {target_host} ...")
                    meshtastic_interface = meshtastic.tcp_interface.TCPInterface(hostname=target_host)

                successful = True
                node_info = meshtastic_interface.getMyNodeInfo()
                meshtastic_logger.info(f"Connected to {node_info['user']['shortName']} / {node_info['user']['hwModel']}")

                # Subscribe to message events
                pub.subscribe(on_meshtastic_message, "meshtastic.receive")
                pub.subscribe(on_lost_meshtastic_connection, "meshtastic.connection.lost")

                # Subscribe to messages from Matrix
                pub.subscribe(send_to_meshtastic_from_matrix, "matrix.send_to_meshtastic")

            except Exception as e:
                if shutting_down:
                    meshtastic_logger.info("Shutdown in progress. Aborting connection attempts.")
                    break
                attempts += 1
                if retry_limit == 0 or attempts <= retry_limit:
                    wait_time = min(attempts * 2, 30)  # Cap wait time to 30 seconds
                    meshtastic_logger.warning(f"Attempt #{attempts - 1} failed. Retrying in {wait_time} secs: {e}")
                    await asyncio.sleep(wait_time)
                else:
                    meshtastic_logger.error(f"Could not connect after {retry_limit} attempts: {e}")
                    return None

    return meshtastic_interface

def on_lost_meshtastic_connection(interface=None):
    """
    Callback function invoked when the Meshtastic connection is lost.
    """
    global meshtastic_interface, reconnecting, shutting_down, meshtastic_event_loop, reconnect_task
    with meshtastic_lock:
        if shutting_down:
            meshtastic_logger.info("Shutdown in progress. Not attempting to reconnect.")
            return
        if reconnecting:
            meshtastic_logger.info("Reconnection already in progress. Skipping additional reconnection attempt.")
            return
        reconnecting = True
        meshtastic_logger.error("Lost connection to Meshtastic device. Attempting to reconnect...")

        if meshtastic_interface:
            try:
                meshtastic_interface.close()
            except Exception as e:
                meshtastic_logger.warning(f"Error closing Meshtastic client: {e}")
            meshtastic_interface = None

        if meshtastic_event_loop:
            reconnect_task = meshtastic_event_loop.create_task(reconnect())

async def reconnect():
    """
    Attempt to reconnect to the Meshtastic device with exponential backoff.
    """
    global reconnecting
    backoff_time = 5

    try:
        while not shutting_down:
            await connect_meshtastic(force_connect=True)
            if meshtastic_interface:
                meshtastic_logger.info("Reconnected to Meshtastic device.")
                break

            meshtastic_logger.warning(f"Reconnection failed. Retrying in {backoff_time} seconds...")
            await asyncio.sleep(backoff_time)
            backoff_time = min(backoff_time * 2, 300)  # Cap at 5 minutes

    except asyncio.CancelledError:
        meshtastic_logger.info("Reconnection task cancelled.")

    finally:
        reconnecting = False

def update_longnames():
    if meshtastic_interface and meshtastic_interface.nodes:
        for node in meshtastic_interface.nodes.values():
            user = node.get("user")
            if user:
                meshtastic_id = user["id"]
                longname = user.get("longName", "N/A")
                save_longname(meshtastic_id, longname)

def update_shortnames():
    if meshtastic_interface and meshtastic_interface.nodes:
        for node in meshtastic_interface.nodes.values():
            user = node.get("user")
            if user:
                meshtastic_id = user["id"]
                shortname = user.get("shortName", "N/A")
                save_shortname(meshtastic_id, shortname)

def truncate_message(text, max_bytes=227):
    """
    Truncate the given text to fit within the specified byte size.
    """
    truncated_text = text.encode("utf-8")[:max_bytes].decode("utf-8", "ignore")
    return truncated_text

def on_meshtastic_message(packet, interface):
    """
    Handle incoming Meshtastic messages.
    """
    if shutting_down:
        return

    asyncio.run_coroutine_threadsafe(handle_meshtastic_message(packet), meshtastic_event_loop)

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
                meshtastic_logger.debug("Unknown packet")
                return

        # Check if the channel is mapped to a Matrix room in the configuration
        channel_mapped = False
        for room in relay_config["matrix_rooms"]:
            if room["meshtastic_channel"] == channel:
                channel_mapped = True
                break

        if not channel_mapped:
            meshtastic_logger.debug(f"Skipping message from unmapped channel {channel}")
            return

        meshtastic_logger.info(f"Processing inbound radio message from {sender} on channel {channel}")

        longname = get_longname(sender) or sender
        shortname = get_shortname(sender) or sender
        meshnet_name = relay_config["meshtastic"]["meshnet_name"]

        formatted_message = f"[{longname}/{meshnet_name}]: {text}"
        meshtastic_logger.info(f"Relaying Meshtastic message from {longname} to Matrix: {formatted_message}")

        # Publish the message to be sent to Matrix
        for room in relay_config["matrix_rooms"]:
            if room["meshtastic_channel"] == channel:
                meshtastic_logger.debug(f"Publishing message to Matrix room {room['id']}")
                pub.sendMessage(
                    "meshtastic.send_to_matrix",
                    room_id=room["id"],
                    message=formatted_message,
                    longname=longname,
                    shortname=shortname,
                    meshnet_name=meshnet_name,
                )
    else:
        portnum = packet["decoded"]["portnum"]
        if portnum == "TELEMETRY_APP":
            meshtastic_logger.debug("Ignoring Telemetry packet")
        elif portnum == "POSITION_APP":
            meshtastic_logger.debug("Ignoring Position packet")
        elif portnum == "ADMIN_APP":
            meshtastic_logger.debug("Ignoring Admin packet")
        else:
            meshtastic_logger.debug("Ignoring Unknown packet")

def send_to_meshtastic_from_matrix(text, channelIndex):
    meshtastic_logger.debug(f"send_to_meshtastic_from_matrix called with text='{text}', channelIndex={channelIndex}")
    if meshtastic_interface:
        try:
            meshtastic_interface.sendText(text=text, channelIndex=channelIndex)
            meshtastic_logger.info("Sent message to Meshtastic")
        except Exception as e:
            meshtastic_logger.error(f"Error sending message to Meshtastic: {e}")
    else:
        meshtastic_logger.warning("Cannot send message: Meshtastic client is not connected.")
