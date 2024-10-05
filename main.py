import asyncio
import signal
import sys

from config import relay_config
from db_utils import initialize_database
from log_utils import get_logger
import meshtastic_utils  # Import the module instead of variables
import matrix_utils  # Import the module instead of variables

logger = get_logger("M<>M Relay")

shutdown_event = asyncio.Event()

async def main():
    global shutdown_event

    # Initialize the SQLite database
    initialize_database()

    # Set up signal handling
    loop = asyncio.get_running_loop()
    meshtastic_utils.meshtastic_event_loop = loop  # Set the event loop in meshtastic_utils
    matrix_utils.matrix_event_loop = loop  # Set the event loop in matrix_utils

    async def shutdown():
        logger.info("Shutdown signal received. Closing down...")
        meshtastic_utils.shutting_down = True
        shutdown_event.set()

    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))
    else:
        pass  # On Windows, rely on KeyboardInterrupt

    try:
        # Connect to Matrix
        await matrix_utils.connect_matrix()
        if matrix_utils.matrix_client is None:
            logger.error("Failed to connect to Matrix server. Exiting.")
            return

        # Join Matrix rooms
        await matrix_utils.join_matrix_rooms()

        # Connect to Meshtastic
        await meshtastic_utils.connect_meshtastic()
        if meshtastic_utils.meshtastic_interface is None:
            logger.error("Failed to connect to Meshtastic device. Exiting.")
            return

        # Start the Matrix client sync loop
        try:
            while not shutdown_event.is_set():
                try:
                    if meshtastic_utils.meshtastic_interface:
                        # Update longnames & shortnames
                        meshtastic_utils.update_longnames()
                        meshtastic_utils.update_shortnames()
                    else:
                        meshtastic_utils.meshtastic_logger.warning("Meshtastic client is not connected.")

                    matrix_utils.matrix_logger.info("Starting Matrix sync loop...")
                    sync_task = asyncio.create_task(
                        matrix_utils.matrix_client.sync_forever(timeout=30000)
                    )
                    shutdown_task = asyncio.create_task(shutdown_event.wait())
                    done, pending = await asyncio.wait(
                        [sync_task, shutdown_task],
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if shutdown_event.is_set():
                        matrix_utils.matrix_logger.info("Shutdown event detected. Stopping sync loop...")
                        sync_task.cancel()
                        try:
                            await sync_task
                        except asyncio.CancelledError:
                            pass
                        break
                except Exception as e:
                    if shutdown_event.is_set():
                        break
                    matrix_utils.matrix_logger.error(f"Error syncing with Matrix server: {e}")
                    await asyncio.sleep(5)  # Wait before retrying
        except KeyboardInterrupt:
            await shutdown()
        finally:
            # Cleanup
            if matrix_utils.matrix_client:
                matrix_utils.matrix_logger.info("Closing Matrix client...")
                await matrix_utils.matrix_client.close()
            else:
                matrix_utils.matrix_logger.warning("Matrix client was not initialized.")

            if meshtastic_utils.meshtastic_interface:
                meshtastic_utils.meshtastic_logger.info("Closing Meshtastic client...")
                try:
                    meshtastic_utils.meshtastic_interface.close()
                except Exception as e:
                    meshtastic_utils.meshtastic_logger.warning(f"Error closing Meshtastic client: {e}")
            else:
                meshtastic_utils.meshtastic_logger.warning("Meshtastic client was not initialized.")

            # Cancel the reconnect task if it exists
            if meshtastic_utils.reconnect_task:
                meshtastic_utils.reconnect_task.cancel()
                meshtastic_utils.meshtastic_logger.info("Cancelled Meshtastic reconnect task.")

            # Cancel any remaining tasks
            tasks = [t for t in asyncio.all_tasks(loop) if not t.done()]
            for task in tasks:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            matrix_utils.matrix_logger.info("Shutdown complete.")

    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    asyncio.run(main())
