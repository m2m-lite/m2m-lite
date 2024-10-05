import asyncio
import threading
import time

import meshtastic.tcp_interface
import meshtastic.serial_interface
import serial.tools.list_ports
from pubsub import pub

from config import relay_config
from db_utils import save_longname, save_shortname
from log_utils import get_logger
from message_handler import handle_meshtastic_message

meshtastic_logger = get_logger("Meshtastic")

meshtastic_interface = None
event_loop = None  # Will be set in main()
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
    global meshtastic_interface, shutting_down, reconnecting, event_loop

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
    global meshtastic_interface, reconnecting, shutting_down, event_loop, reconnect_task
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

        if event_loop:
            reconnect_task = event_loop.create_task(reconnect())

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

def on_meshtastic_message(packet):
    """
    Handle incoming Meshtastic messages.
    """
    if shutting_down:
        return

    # Process the message
    asyncio.run_coroutine_threadsafe(handle_meshtastic_message(packet), event_loop)

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
