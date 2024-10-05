import asyncio
import ssl

from nio import AsyncClient, AsyncClientConfig, RoomMessageText, RoomMessageNotice

from config import relay_config
from log_utils import get_logger
from message_handler import on_room_message

matrix_logger = get_logger("Matrix")
matrix_client = None

async def connect_matrix():
    """
    Connect to the Matrix server.
    """
    global matrix_client

    matrix_server = relay_config["matrix"]["homeserver"]
    access_token = relay_config["matrix"]["access_token"]
    user_id = relay_config["matrix"]["user_id"]

    ssl_context = ssl.create_default_context()

    config = AsyncClientConfig(encryption_enabled=False)
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

        # Register the message callback
        matrix_client.add_event_callback(
            on_room_message,
            (RoomMessageText, RoomMessageNotice),
        )

    except Exception as e:
        matrix_logger.error(f"Failed to connect to Matrix server: {e}")
        return None

    return matrix_client

async def join_matrix_rooms():
    """
    Join the Matrix rooms specified in the configuration.
    """
    matrix_rooms = relay_config["matrix_rooms"]
    for room in matrix_rooms:
        await join_matrix_room(matrix_client, room["id"])

async def join_matrix_room(matrix_client, room_id_or_alias: str) -> None:
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
            room["id"] = resolved_room_id
            break
