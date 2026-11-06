"""macOS Bonjour advertisement, using the system DNS-SD library (no packages)."""

import ctypes
import ipaddress
import logging
import select
import socket
import sys
import threading

SERVICE_TYPE = "_uniremote._tcp"


def txt_record(address):
    # Metadata only. Credentials and pairing codes must never be advertised.
    entries = [b"api=1", b"pairing=code"]
    ip = ipaddress.ip_address(address)
    if not ip.is_unspecified and not ip.is_loopback:
        entries.append(f"address={ip}".encode("ascii"))
    return b"".join(bytes([len(entry)]) + entry for entry in entries)


class Bonjour:
    def __init__(self, address, port):
        self.address, self.port = address, port
        self.stop = threading.Event()
        self.thread = None

    def start(self):
        if sys.platform != "darwin" or ipaddress.ip_address(self.address).is_loopback:
            return
        self.thread = threading.Thread(target=self.run, name="bonjour", daemon=True)
        self.thread.start()

    def run(self):
        while not self.stop.is_set():
            self.register()
            self.stop.wait(5)

    def register(self):
        # DNSServiceRef owns a connection to mDNSResponder. When this process
        # exits (even on a crash), macOS removes the service; no orphan helper.
        ref = ctypes.c_void_p()
        try:
            lib = ctypes.CDLL("/usr/lib/libdns_sd.dylib")
            callback_type = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_uint32,
                                           ctypes.c_int32, ctypes.c_char_p,
                                           ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p)

            def registered(_ref, _flags, error, name, _type, _domain, _context):
                if error:
                    logging.error("Bonjour registration failed: %d", error)
                else:
                    logging.info("Bonjour advertised %s.%s", name.decode(), SERVICE_TYPE)

            callback = callback_type(registered)
            lib.DNSServiceRegister.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint32,
                                              ctypes.c_uint32, ctypes.c_char_p, ctypes.c_char_p,
                                              ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint16,
                                              ctypes.c_uint16, ctypes.c_void_p, callback_type, ctypes.c_void_p]
            lib.DNSServiceRegister.restype = ctypes.c_int32
            lib.DNSServiceRefSockFD.argtypes = [ctypes.c_void_p]
            lib.DNSServiceRefSockFD.restype = ctypes.c_int
            lib.DNSServiceProcessResult.argtypes = [ctypes.c_void_p]
            lib.DNSServiceProcessResult.restype = ctypes.c_int32
            lib.DNSServiceRefDeallocate.argtypes = [ctypes.c_void_p]
            record = txt_record(self.address)
            error = lib.DNSServiceRegister(ctypes.byref(ref), 0, 0, b"Butler Lights",
                                          SERVICE_TYPE.encode(), None, None,
                                          socket.htons(self.port), len(record), record, callback, None)
            if error:
                raise OSError(f"DNSServiceRegister: {error}")
            fd = lib.DNSServiceRefSockFD(ref)
            while not self.stop.is_set():
                if select.select([fd], [], [], 0.5)[0]:
                    error = lib.DNSServiceProcessResult(ref)
                    if error:
                        raise OSError(f"DNSServiceProcessResult: {error}")
        except (OSError, ValueError):
            logging.exception("Bonjour unavailable; lighting manager remains running")
        finally:
            if ref.value:
                lib.DNSServiceRefDeallocate(ref)

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=2)
