"""Meshtastic utilities for m2m-lite."""

import asyncio
import threading

import meshtastic.ble_interface
import meshtastic.serial_interface
import meshtastic.tcp_interface
import serial
import serial.tools.list_ports
from bleak.exc import BleakDBusError, BleakError
from pubsub import pub

from config import relay_config
from db_utils import get_longname, get_shortname, save_longname, save_shortname
from log_utils import get_logger

meshtastic_logger = get_logger("Meshtastic")

# Use module-level variables
meshtastic_interface = None
meshtastic_event_loop = None  # Will be set in main()
meshtastic_lock = (
    threading.Lock()
)  # To prevent race conditions when accessing the Meshtastic interface
reconnecting = False  # Flag to indicate if a reconnection attempt is in progress
shutting_down = False  # Flag to indicate if the application is shutting down
reconnect_task = None  # To keep track of the reconnection task


def serial_port_exists(port_name):
    """
    Check if the specified serial port exists.

    Args:
        port_name (str): The name of the serial port (e.g., /dev/ttyUSB0, COM3).

    Returns:
        bool: True if the port exists, False otherwise.
    """
    ports = [port.device for port in serial.tools.list_ports.comports()]
    return port_name in ports


async def connect_meshtastic(force_connect=False):
    """
    Establish a connection to the Meshtastic device.

    This function attempts to connect to a Meshtastic device using the configured connection type
    (serial, BLE, or TCP). It handles retries with exponential backoff and prevents multiple
    connection attempts while a reconnection is in progress or the application is shutting down.

    Args:
        force_connect (bool): If True, force a new connection even if one already exists.

    Returns:
        meshtastic.mesh_interface.MeshInterface or None: The Meshtastic interface object if
        successful, None otherwise.
    """
    global meshtastic_interface, shutting_down, reconnecting, meshtastic_event_loop

    if shutting_down:
        meshtastic_logger.info("Shutdown in progress. Not attempting to connect.")
        return None

    with meshtastic_lock:
        if meshtastic_interface and not force_connect:
            # Connection already exists and force_connect is False
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

        while (
            not successful
            and (retry_limit == 0 or attempts <= retry_limit)
            and not shutting_down
        ):
            try:
                if connection_type == "serial":
                    serial_port = relay_config["meshtastic"]["serial_port"]
                    meshtastic_logger.info(
                        f"Connecting to serial port {serial_port} ..."
                    )

                    # Check if serial port exists before attempting connection
                    if not serial_port_exists(serial_port):
                        meshtastic_logger.warning(
                            f"Serial port {serial_port} does not exist. Waiting..."
                        )
                        await asyncio.sleep(5)
                        attempts += 1
                        continue

                    meshtastic_interface = meshtastic.serial_interface.SerialInterface(
                        serial_port
                    )

                elif connection_type == "ble":
                    # BLE connection
                    ble_address = relay_config["meshtastic"].get("ble_address")
                    if ble_address:
                        meshtastic_logger.info(
                            f"Connecting to BLE address {ble_address} ..."
                        )
                        meshtastic_interface = meshtastic.ble_interface.BLEInterface(
                            address=ble_address,
                            noProto=False,
                            debugOut=None,
                            noNodes=False,
                        )
                    else:
                        meshtastic_logger.error("No BLE address provided.")
                        return None

                else:  # connection_type == "tcp"
                    target_host = relay_config["meshtastic"]["host"]
                    meshtastic_logger.info(f"Connecting to radio at {target_host} ...")
                    meshtastic_interface = meshtastic.tcp_interface.TCPInterface(
                        hostname=target_host
                    )

                successful = True
                node_info = meshtastic_interface.getMyNodeInfo()
                meshtastic_logger.info(
                    f"Connected to {node_info['user']['shortName']} / {node_info['user']['hwModel']}"
                )

                # Subscribe to relevant events using pubsub
                pub.subscribe(on_meshtastic_message, "meshtastic.receive")
                pub.subscribe(
                    on_lost_meshtastic_connection, "meshtastic.connection.lost"
                )

                # Subscribe to messages from Matrix
                pub.subscribe(
                    send_to_meshtastic_from_matrix, "matrix.send_to_meshtastic"
                )

            except (
                serial.SerialException,
                BleakDBusError,
                BleakError,
                Exception,
            ) as e:
                if shutting_down:
                    meshtastic_logger.info(
                        "Shutdown in progress. Aborting connection attempts."
                    )
                    break
                attempts += 1
                if retry_limit == 0 or attempts <= retry_limit:
                    wait_time = min(
                        attempts * 2, 30
                    )  # Exponential backoff, capped at 30 seconds
                    meshtastic_logger.warning(
                        f"Attempt #{attempts - 1} failed. Retrying in {wait_time} secs: {e}"
                    )
                    await asyncio.sleep(wait_time)  # Wait before retrying
                else:
                    meshtastic_logger.error(
                        f"Could not connect after {retry_limit} attempts: {e}"
                    )
                    return None

    return meshtastic_interface


def on_lost_meshtastic_connection(interface=None):
    """
    Callback function invoked when the Meshtastic connection is lost.

    This function initiates the reconnection process unless the application is shutting down or
    a reconnection is already in progress.

    Args:
        interface (meshtastic.mesh_interface.MeshInterface): The Meshtastic interface object.
            This is not used but provided by the pubsub event.
    """
    global meshtastic_interface, reconnecting, shutting_down, meshtastic_event_loop, reconnect_task
    with meshtastic_lock:
        if shutting_down:
            meshtastic_logger.info("Shutdown in progress. Not attempting to reconnect.")
            return
        if reconnecting:
            meshtastic_logger.info(
                "Reconnection already in progress. Skipping additional reconnection attempt."
            )
            return
        reconnecting = True
        meshtastic_logger.error(
            "Lost connection to Meshtastic device. Attempting to reconnect..."
        )

        # Close the existing Meshtastic interface if it exists
        if meshtastic_interface:
            try:
                meshtastic_interface.close()
            except OSError as e:
                if e.errno == 9:
                    # Bad file descriptor error, the interface is likely already closed.
                    pass
                else:
                    meshtastic_logger.warning(f"Error closing Meshtastic client: {e}")
            except Exception as e:
                meshtastic_logger.warning(f"Error closing Meshtastic client: {e}")
            meshtastic_interface = None

        # Create a task to handle the reconnection process
        if meshtastic_event_loop:
            reconnect_task = meshtastic_event_loop.create_task(reconnect())


async def reconnect():
    """
    Attempt to reconnect to the Meshtastic device with exponential backoff.

    This function is run as a task and will continuously attempt to reconnect to the Meshtastic
    device until successful or until the application is shutting down. It uses an exponential
    backoff strategy to avoid overloading the system with reconnection attempts.
    """
    global reconnecting
    backoff_time = 5  # Initial backoff time in seconds

    try:
        while not shutting_down:
            await connect_meshtastic(force_connect=True)
            if meshtastic_interface:
                meshtastic_logger.info("Reconnected to Meshtastic device.")
                break  # Reconnection successful, exit the loop

            meshtastic_logger.warning(
                f"Reconnection failed. Retrying in {backoff_time} seconds..."
            )
            await asyncio.sleep(backoff_time)
            backoff_time = min(
                backoff_time * 2, 300
            )  # Increase backoff time, capped at 5 minutes

    except asyncio.CancelledError:
        meshtastic_logger.info("Reconnection task cancelled.")
    finally:
        reconnecting = False  # Reset the reconnection flag


def update_longnames():
    """
    Update the database with longnames from the Meshtastic node DB.
    """
    if meshtastic_interface and meshtastic_interface.nodes:
        for node in meshtastic_interface.nodes.values():
            user = node.get("user")
            if user:
                meshtastic_id = user["id"]
                longname = user.get("longName", "N/A")
                save_longname(meshtastic_id, longname)


def update_shortnames():
    """
    Update the database with shortnames from the Meshtastic node DB.
    """
    if meshtastic_interface and meshtastic_interface.nodes:
        for node in meshtastic_interface.nodes.values():
            user = node.get("user")
            if user:
                meshtastic_id = user["id"]
                shortname = user.get("shortName", "N/A")
                save_shortname(meshtastic_id, shortname)


def on_meshtastic_message(packet, interface):
    """
    Handle incoming Meshtastic messages.

    This function is called when a message is received from the Meshtastic network. It filters out
    unwanted packets (e.g., non-text messages, reaction packets), determines the appropriate
    channel, and relays the message to the corresponding Matrix room(s) via pubsub.

    Args:
        packet (dict): The received Meshtastic packet.
        interface (meshtastic.mesh_interface.MeshInterface): The Meshtastic interface object.
    """
    if shutting_down:
        return

    asyncio.run_coroutine_threadsafe(
        handle_meshtastic_message(packet), meshtastic_event_loop
    )


async def handle_meshtastic_message(packet):
    """
    Handle incoming Meshtastic messages, filter out unwanted packets, and relay to Matrix.

    Filters:
      - Reaction packets (emoji or replyId in decoded payload)
      - Non-text messages (unless it's a detection sensor packet and the feature is enabled)
      - Messages from unmapped channels

    Args:
        packet (dict): The received Meshtastic packet.
    """
    sender = packet["fromId"]

    decoded = packet["decoded"]

    if "text" in decoded and decoded["text"]:
        text = decoded["text"]

        # Filter out reaction packets
        if "emoji" in decoded or "replyId" in decoded:
            meshtastic_logger.debug(
                "Filtered out reaction packet due to presence of 'emoji' or 'replyId'."
            )
            return

        if "channel" in packet:
            channel = packet["channel"]
        else:
            # If no channel is specified in the packet data, infer the channel from portnum
            if decoded["portnum"] == "TEXT_MESSAGE_APP":
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

        meshtastic_logger.info(
            f"Processing inbound radio message from {sender} on channel {channel}"
        )

        # Get longname and shortname from the database, or use the sender ID if not found
        longname = get_longname(sender) or sender
        shortname = get_shortname(sender) or sender
        meshnet_name = relay_config["meshtastic"]["meshnet_name"]

        formatted_message = f"[{longname}/{meshnet_name}]: {text}"
        meshtastic_logger.info(
            f"Relaying Meshtastic message from {longname} to Matrix: {formatted_message}"
        )

        # Publish the message to be sent to Matrix via the "meshtastic.send_to_matrix" topic
        for room in relay_config["matrix_rooms"]:
            if room["meshtastic_channel"] == channel:
                meshtastic_logger.debug(
                    f"Publishing message to Matrix room {room['id']}"
                )
                pub.sendMessage(
                    "meshtastic.send_to_matrix",
                    room_id=room["id"],
                    message=formatted_message,
                    longname=longname,
                    shortname=shortname,
                    meshnet_name=meshnet_name,
                )

    else:
        # Handle non-text messages (currently, only detection sensor packets are supported)
        portnum = decoded["portnum"]
        if portnum == "DETECTION_SENSOR_APP":
            if relay_config["meshtastic"].get("detection_sensor", False):
                meshtastic_logger.info("Processing detection sensor data")
                # Construct the message to send to Matrix
                detection_data_message = (
                    f"Detection Sensor: {decoded.get('raw', {}).get('json', 'No data')}"
                )

                # Send the detection data message to the appropriate Matrix room(s)
                for room in relay_config["matrix_rooms"]:
                    if (
                        room["meshtastic_channel"] == 0
                    ):  # Assuming channel 0 for detection sensor
                        meshtastic_logger.debug(
                            f"Publishing detection data message to Matrix room {room['id']}"
                        )
                        pub.sendMessage(
                            "meshtastic.send_to_matrix",
                            room_id=room["id"],
                            message=detection_data_message,
                            longname=None,
                            shortname=None,
                            meshnet_name=None,
                        )
            else:
                meshtastic_logger.debug("Ignoring Detection Sensor packet")
        # We don't need to specifically handle TEXT_MESSAGE_APP here since it's already handled above
        elif portnum != "TEXT_MESSAGE_APP":
            # Any other portnum we don't care about and can be silently ignored
            pass


def send_to_meshtastic_from_matrix(text, channelIndex):
    """
    Send a message from Matrix to Meshtastic.

    Args:
        text (str): The text of the message to send.
        channelIndex (int): The Meshtastic channel index to send the message on.
    """
    meshtastic_logger.debug(
        f"send_to_meshtastic_from_matrix called with text='{text}', channelIndex={channelIndex}"
    )
    if meshtastic_interface:
        try:
            meshtastic_interface.sendText(text=text, channelIndex=channelIndex)
            meshtastic_logger.info("Sent message to Meshtastic")
        except Exception as e:
            meshtastic_logger.error(f"Error sending message to Meshtastic: {e}")
    else:
        meshtastic_logger.warning(
            "Cannot send message: Meshtastic client is not connected."
        )


async def check_connection():
    """
    Periodically checks the Meshtastic connection by sending a ping.
    If an error occurs, it attempts to reconnect.
    """
    global meshtastic_interface, shutting_down
    connection_type = relay_config["meshtastic"]["connection_type"]
    while not shutting_down:
        if meshtastic_interface:
            try:
                meshtastic_interface.sendPing()
            except Exception as e:
                meshtastic_logger.error(
                    f"{connection_type.capitalize()} connection lost: {e}"
                )
                on_lost_meshtastic_connection(meshtastic_interface)
        await asyncio.sleep(5)  # Check connection every 5 seconds
