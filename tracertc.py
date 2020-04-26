import asyncio
from collections import namedtuple
import errno
import logging
import os
import socket
import struct
import time

logger = logging.getLogger('tracertc')


class Probe:
    def __init__(self):
        self._complete = asyncio.Event()
        self.reset()

    def reset(self):
        self._start = None
        self._end = None
        self._outcome = None
        self._icmp_addr = None
        self._complete.clear()

    def start(self, message):
        self.reset()
        self.expected_response = message.replace('ping', 'pong')
        self._start = time.time()

    def wait(self):
        return self._complete.wait()

    def complete(self, outcome):
        self._outcome = outcome
        self._complete.set()

    def icmp_stop(self, icmp_addr, icmp_received):
        self._icmp_addr = icmp_addr
        self._end = icmp_received
        self.complete('icmp')

    def response_stop(self):
        self._end = time.time()
        self.complete('response')

    def timeout_stop(self):
        self._end = time.time()
        self.complete('timeout')

    @property
    def rtt(self):
        return self._end - self._start

    @property
    def outcome(self):
        return self._outcome

    @property
    def icmp_addr(self):
        return self._icmp_addr


ProbeResult = namedtuple('ProbeResult', 'ttl outcome rtt icmp_addr')
sock_extended_err = struct.Struct('IBBBxII')
ee_size = socket.CMSG_SPACE(sock_extended_err.size * 2)
sockaddr_in = struct.Struct('HH4B8x')

max_packet_size = 65535
SO_EE_ORIGIN_ICMP = 2
IP_RECVERR = 11

class Tracer:
    def __init__(self, channel):
        self.channel = channel
        self.n = 0

        self._sctp = self.channel.transport
        self._protocol = self._sctp.transport.transport._connection._nominated[1].protocol
        self._sock = self._protocol.transport.get_extra_info('socket')

        self._probe = Probe()
        self._warmup = Probe()

        @self.channel.on('message')
        def on_message(message):
            logger.debug(f'Received {message}')
            if message.startswith('pong pre-'):
                if message == self._warmup.expected_response:
                    self._warmup.response_stop()
                else:
                    logger.warning(f"Unexpected {message}, expected {self._warmup.expected_response}")
            elif message.startswith('pong'):
                if message == self._probe.expected_response:
                    self._probe.response_stop()
                else:
                    logger.warning(f"Unexpected {message}, expected {self._probe.expected_response}")
            else:
                logger.warning(f"Unexpected message {message}, ignoring")

        def error_received(protocol_self, exc):
            if not (isinstance(exc, OSError) and exc.errno == 113):
                return

            drain = False

            while True:
                try:
                    # FIXME: this is quite nasty, we should make aioice support this explicitly
                    data, ancdata, flags, addr = self._sock.recvmsg(max_packet_size, ee_size, socket.MSG_ERRQUEUE | socket.MSG_DONTWAIT)
                    if flags & socket.MSG_CTRUNC:
                        logger.warn("Returned ancillary data was truncated")
                    elif flags & socket.MSG_ERRQUEUE and not drain:
                        icmp_received = time.time()
                        for cmsg_level, cmsg_type, cmsg_data in ancdata:
                            if cmsg_level == socket.SOL_IP and cmsg_type == IP_RECVERR:
                                ee_errno, ee_origin, ee_type, ee_code, ee_info, ee_data = sock_extended_err.unpack_from(cmsg_data)
                                if (ee_errno, ee_origin, ee_type) != (errno.EHOSTUNREACH, SO_EE_ORIGIN_ICMP, IP_RECVERR):
                                    continue
                                sin_family, sin_port, *sin_addr = sockaddr_in.unpack_from(cmsg_data, sock_extended_err.size)
                                icmp_addr = '%d.%d.%d.%d' % tuple(sin_addr)
                                logger.info(f"ICMP response from {icmp_addr}")
                                drain = True

                except BlockingIOError:
                    break

            if drain:
                self._probe.icmp_stop(icmp_addr, icmp_received)

        self._on_message = on_message
        self._orig_error_received = self._protocol.error_received
        self._orig_ttl = self._sock.getsockopt(socket.IPPROTO_IP, socket.IP_TTL)

        self._protocol.error_received = error_received.__get__(self._protocol, self._protocol.__class__)

        orig_recverr = self._sock.getsockopt(socket.SOL_IP, IP_RECVERR)
        if orig_recverr != 0:
            raise ValueError("Socket already has extended error message queueing enabled")
        self._sock.setsockopt(socket.SOL_IP, IP_RECVERR, 1)

    def __del__(self):
        # Reusing a channel isn't supported but let's clean things up in case of an exception
        self.channel.remove_listener('message', self._on_message)
        self._protocol.error_received = self._orig_error_received
        self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_TTL, self._orig_ttl)

    async def send_probes(self, min_ttl=1, max_ttl=30):
        trace = []

        for ttl in range(min_ttl, max_ttl + 1):

            for attempt in [1, 2]:
                # Prepare by sending a warmup ping
                # We might need to retry rarely
                msg = f'ping pre-{self.n}-{attempt}'
                self._warmup.start(msg)
                self.channel.send(msg)
                await self._sctp._data_channel_flush()
                try:
                    await asyncio.wait_for(self._warmup.wait(), timeout=1.5)
                except asyncio.TimeoutError:
                    logger.error(f"Warmup ping timed out")
                except Exception as e:
                    logger.error(f"Unexpected exception: {e}")
                else:
                    break

            logger.info(f"Sending probe {self.n} with TTL {ttl}")
            self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_TTL, ttl)
            msg = f'ping {self.n}'
            self._probe.start(msg)
            self.channel.send(msg)
            await self._sctp._data_channel_flush()
            self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_TTL, self._orig_ttl)

            try:
                await asyncio.wait_for(self._probe.wait(), timeout=1)
            except asyncio.TimeoutError:
                self._probe.timeout_stop()
                logger.info(f"Probe timed out after {self._probe.rtt * 1000:0.1f} ms")
            except Exception as e:
                logger.error(f"Unexpected exception: {e}")
            else:
                trace.append(ProbeResult(ttl, self._probe.outcome, self._probe.rtt, self._probe.icmp_addr))
                logger.info(f"RTT for TTL {ttl}: {self._probe.rtt * 1000:0.1f} ms")

            if self._probe.outcome == 'icmp':
                # FIXME: why is this needed?
                # Also, why can't I reduce timeout to below 1?
                # Is there a sleep somewhere?
                await asyncio.sleep(1)

            if self._probe.outcome == 'response':
                break

            self.n += 1

        return trace


