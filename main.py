"""
m2m-lite: A minimalist Meshtastic-to-Matrix relay.

This script connects a Meshtastic mesh network to Matrix chat rooms by relaying messages between them.
It uses the Meshtastic-python library to interface with the radio and the Matrix nio client library
to interact with the Matrix server.
"""

import asyncio
import signal
import sys

import matrix_utils
import meshtastic_utils
from db_utils import initialize_database
from log_utils import get_logger

logger = get_logger("m2m-lite")

shutdown_event = asyncio.Event()  # Event to signal shutdown


async def main():
    """
    Main function to set up and run the relay.
    """
    global shutdown_event

    # Initialize the SQLite database
    initialize_database()

    # Set up signal handling for graceful shutdown
    loop = asyncio.get_running_loop()
    meshtastic_utils.meshtastic_event_loop = (
        loop  # Set the event loop for meshtastic_utils
    )
    matrix_utils.matrix_event_loop = loop  # Set the event loop for matrix_utils

    async def shutdown():
        """
        Gracefully shut down the relay.

        This function closes connections to Matrix and Meshtastic, cancels pending tasks,
        and sets the shutdown_event to stop the main loop.
        """
        logger.info("Shutdown signal received. Closing down...")
        meshtastic_utils.shutting_down = (
            True  # Set the shutting_down flag in meshtastic_utils
        )
        shutdown_event.set()  # Signal the main loop to exit

    if sys.platform != "win32":
        # Signal handling is different on Windows (no SIGTERM)
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))
    else:
        # On Windows, rely on KeyboardInterrupt (Ctrl+C)
        pass

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
                        meshtastic_utils.meshtastic_logger.warning(
                            "Meshtastic client is not connected."
                        )
                    matrix_utils.matrix_logger.info("Starting Matrix sync loop...")
                    sync_task = asyncio.create_task(
                        matrix_utils.matrix_client.sync_forever(timeout=30000)
                    )
                    shutdown_task = asyncio.create_task(shutdown_event.wait())
                    done, pending = await asyncio.wait(
                        [sync_task, shutdown_task],  # Await both tasks
                        return_when=asyncio.FIRST_COMPLETED,  # Return when either task completes
                    )
                    if shutdown_event.is_set():
                        matrix_utils.matrix_logger.info(
                            "Shutdown event detected. Stopping sync loop..."
                        )
                        sync_task.cancel()  # Cancel the sync task
                        try:
                            await sync_task  # Await the cancelled task to ensure it's cleaned up
                        except asyncio.CancelledError:
                            pass
                        break  # Exit the loop
                except Exception as e:
                    if shutdown_event.is_set():
                        break  # Ignore errors during shutdown
                    matrix_utils.matrix_logger.error(
                        f"Error syncing with Matrix server: {e}"
                    )
                    await asyncio.sleep(5)  # Wait before retrying
        except KeyboardInterrupt:
            await shutdown()  # Handle Ctrl+C as a shutdown signal
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
                    meshtastic_utils.meshtastic_logger.warning(
                        f"Error closing Meshtastic client: {e}"
                    )
            else:
                meshtastic_utils.meshtastic_logger.warning(
                    "Meshtastic client was not initialized."
                )

            # Cancel the reconnect task if it exists
            if meshtastic_utils.reconnect_task:
                meshtastic_utils.reconnect_task.cancel()
                meshtastic_utils.meshtastic_logger.info(
                    "Cancelled Meshtastic reconnect task."
                )

            # Cancel any remaining tasks
            tasks = [t for t in asyncio.all_tasks(loop) if not t.done()]
            for task in tasks:
                task.cancel()
                try:
                    await task  # Await cancelled tasks to ensure they're cleaned up
                except asyncio.CancelledError:
                    pass
            matrix_utils.matrix_logger.info("Shutdown complete.")

    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")


if __name__ == "__main__":
    asyncio.run(main())
