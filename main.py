import asyncio
import signal
import sys
import threading

from config import relay_config
from db_utils import initialize_database
from log_utils import get_logger
from meshtastic_utils import (
    connect_meshtastic,
    meshtastic_interface,
    meshtastic_logger,
    reconnect_task,
    shutting_down,
    update_longnames,
    update_shortnames,
)
from matrix_utils import (
    connect_matrix,
    join_matrix_rooms,
    matrix_client,
    matrix_logger,
)
from message_handler import bot_start_time

logger = get_logger("M<>M Relay")

shutdown_event = asyncio.Event()
event_loop = None  # Will be set in main()

async def main():
    global event_loop, shutting_down

    # Initialize the SQLite database
    initialize_database()

    # Set up signal handling
    loop = asyncio.get_running_loop()
    event_loop = loop  # Set the global event loop

    async def shutdown():
        logger.info("Shutdown signal received. Closing down...")
        shutting_down = True
        shutdown_event.set()

    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))
    else:
        pass  # On Windows, rely on KeyboardInterrupt

    try:
        # Connect to Matrix
        await connect_matrix()

        # Join Matrix rooms
        await join_matrix_rooms()

        # Connect to Meshtastic
        await connect_meshtastic()

        # Start the Matrix client sync loop
        try:
            while not shutdown_event.is_set():
                try:
                    if meshtastic_interface:
                        # Update longnames & shortnames
                        update_longnames()
                        update_shortnames()
                    else:
                        meshtastic_logger.warning("Meshtastic client is not connected.")

                    matrix_logger.info("Starting Matrix sync loop...")
                    sync_task = asyncio.create_task(
                        matrix_client.sync_forever(timeout=30000)
                    )
                    shutdown_task = asyncio.create_task(shutdown_event.wait())
                    done, pending = await asyncio.wait(
                        [sync_task, shutdown_task],
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if shutdown_event.is_set():
                        matrix_logger.info("Shutdown event detected. Stopping sync loop...")
                        sync_task.cancel()
                        try:
                            await sync_task
                        except asyncio.CancelledError:
                            pass
                        break
                except Exception as e:
                    if shutdown_event.is_set():
                        break
                    matrix_logger.error(f"Error syncing with Matrix server: {e}")
                    await asyncio.sleep(5)  # Wait before retrying
        except KeyboardInterrupt:
            await shutdown()
        finally:
            # Cleanup
            matrix_logger.info("Closing Matrix client...")
            await matrix_client.close()
            if meshtastic_interface:
                meshtastic_logger.info("Closing Meshtastic client...")
                try:
                    meshtastic_interface.close()
                except Exception as e:
                    meshtastic_logger.warning(f"Error closing Meshtastic client: {e}")

            # Cancel the reconnect task if it exists
            if reconnect_task:
                reconnect_task.cancel()
                meshtastic_logger.info("Cancelled Meshtastic reconnect task.")

            # Cancel any remaining tasks
            tasks = [t for t in asyncio.all_tasks(loop) if not t.done()]
            for task in tasks:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            matrix_logger.info("Shutdown complete.")

    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    asyncio.run(main())
