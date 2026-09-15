import asyncio
import errno
import logging
import socket
from gettext import gettext as _

import asyncudp

from .transport import Transport, TransportStatus

logger = logging.getLogger(__name__)

# WSAEADDRINUSE only exists on Windows; EADDRINUSE covers the rest.
_ADDR_IN_USE = {
    errno.EADDRINUSE,
    getattr(errno, "WSAEADDRINUSE", errno.EADDRINUSE),
}


class UdpTransport(Transport):
    def __init__(self, host: str, port: int, local_port: int | None = None):
        super().__init__()
        self.host = host
        self.host_ip = socket.gethostbyname(host)
        self.port = port
        self.local_port = local_port
        self.reader: asyncudp.Socket | None = None
        self.writer: asyncudp.Socket | None = None
        self._running = False
        self._reconnect_interval = 5
        self._connection_task: asyncio.Task | None = None
        # Set when a bind to a fixed local port fails; cleared on the
        # next successful connect. Lets diagnostics UI show *why* a
        # response-port channel never came up, after the fact.
        self.last_bind_error: str | None = None

    @property
    def is_connected(self) -> bool:
        """Check if the transport is actively connected."""
        return self.writer is not None

    async def connect(self) -> None:
        if self.is_connected:
            return

        self._running = True
        self.status_changed.send(self, status=TransportStatus.CONNECTING)
        logger.info(f"Connecting to server at {self.host}:{self.port}...")
        try:
            local_addr = None
            if self.local_port is not None:
                local_addr = ("0.0.0.0", self.local_port)
            reuse_port = (
                hasattr(socket, "SO_REUSEPORT") if local_addr else None
            )
            self.reader = await asyncudp.create_socket(
                local_addr=local_addr,
                remote_addr=(self.host_ip, self.port),
                reuse_port=reuse_port,
            )
            self.writer = self.reader
            self.last_bind_error = None

            self.status_changed.send(self, status=TransportStatus.CONNECTED)
            logger.info(f"Successfully connected to {self.host}:{self.port}.")
            # Connection is successful, start the management task
            self._connection_task = asyncio.create_task(
                self._manage_connection()
            )
        except OSError as e:
            # Failed to connect, report error and re-raise so caller knows.
            logger.error(f"Failed to connect to {self.host}:{self.port}: {e}")
            message = str(e)
            in_use = self.local_port is not None and e.errno in _ADDR_IN_USE
            if in_use:
                # A bind to a fixed local port (e.g. the Ruida response
                # port) fails this way when something else already
                # holds it -- most likely another SwiftCut instance.
                # Only EADDRINUSE means that; every other OSError keeps
                # its own text so it is not misreported as a conflict.
                message = _("port in use (another SwiftCut instance?)")
                self.last_bind_error = message
            self.status_changed.send(
                self, status=TransportStatus.ERROR, message=message
            )
            if in_use:
                # Re-raise with the operator-facing text, preserving
                # errno so callers can still branch on it.
                raise OSError(e.errno, message) from e
            raise

    async def _manage_connection(self) -> None:
        """
        Manages an active connection: receives data and handles disconnects.
        """
        try:
            await self._receive_loop()
        except OSError as e:
            self.status_changed.send(
                self, status=TransportStatus.ERROR, message=str(e)
            )
        finally:
            # Connection was lost or an error occurred.
            if self.writer:
                self.writer.close()
            self.writer = None
            self.reader = None
            self.status_changed.send(self, status=TransportStatus.DISCONNECTED)

    async def disconnect(self) -> None:
        logger.info(f"Disconnecting from server at {self.host}:{self.port}...")
        self._running = False
        if self._connection_task:
            self._connection_task.cancel()
            try:
                await self._connection_task
            except asyncio.CancelledError:
                pass  # Expected
        if self.writer:
            try:
                self.writer.close()
            except ConnectionResetError:
                pass  # The other end might have already closed it.
        self.writer = None
        self.reader = None
        self.status_changed.send(self, status=TransportStatus.DISCONNECTED)
        logger.info(f"Disconnected from {self.host}:{self.port}.")

    async def send(self, data: bytes) -> None:
        if not self.writer:
            raise ConnectionError("Not connected")
        self.writer.sendto(data)

    async def purge(self) -> None:
        """
        Clear any buffered data in the UDP transport.

        Discards any pending data in the receive buffer to resync
        communications. Does not affect the connection state.
        """
        if not self.reader:
            return

        try:
            while True:
                data, _ = await asyncio.wait_for(
                    self.reader.recvfrom(), timeout=0.1
                )
                if not data:
                    break
                logger.debug(f"Purged data: {data!r}")
        except asyncio.TimeoutError:
            pass
        except OSError as e:
            logger.warning(f"Error during purge: {e}")

    async def _receive_loop(self) -> None:
        while self.reader:
            try:
                data, _ = await self.reader.recvfrom()
                if data:
                    self.received.send(self, data=data)
                else:
                    logger.info(
                        f"Connection to {self.host}:{self.port} "
                        "closed by peer."
                    )
                    break
            except asyncio.CancelledError:
                break
            except OSError as e:
                self.status_changed.send(
                    self, status=TransportStatus.ERROR, message=str(e)
                )
                break
