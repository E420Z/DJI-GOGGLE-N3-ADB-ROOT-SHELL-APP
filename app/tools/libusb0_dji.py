"""Minimal ctypes binding to DJI's libusb-win32 fork (libusb0_device.dll).

Why this exists: the goggles' vendor interfaces (MI_03..MI_07) are bound to
the `libusb0_device` service from DJI's BULK_DRIVER INF. libusb-1.0 can see
the descriptors but cannot claim them ("Entity not found"), and pyusb's own
libusb0 backend crashes on this fork. The matching 64-bit DLL ships with
DJI Assistant 2 and exports the classic libusb0 API, so we call it directly.

Struct layouts follow libusb-win32 usb.h (MSVC x64 default alignment,
PATH_MAX 512).
"""
import ctypes as C
import os
import sys

DEFAULT_DLLS = [
    r'C:\Program Files (x86)\DJI Product\DJI Assistant 2 (Consumer Drones Series)'
    r'\Drivers\Drivers_Win10\BULK_DRIVER\bulk_amd64\libusb0_device.dll',
    r'C:\Program Files (x86)\DJI Product\DJI Assistant 2 (Consumer Drones Series)'
    r'\Drivers\Drivers_Win10\DJI_BULK\bulk_amd64\libusb0_dji.dll',
    r'C:\Program Files (x86)\DJI Product\DJI Assistant 2 (Consumer Drones Series)'
    r'\Drivers\Drivers_Win10\DJI_BULK\bulk_amd64\libusb0.dll',
]

PATH_MAX = 512


class UsbDeviceDescriptor(C.Structure):
    _fields_ = [
        ('bLength', C.c_uint8), ('bDescriptorType', C.c_uint8),
        ('bcdUSB', C.c_uint16),
        ('bDeviceClass', C.c_uint8), ('bDeviceSubClass', C.c_uint8),
        ('bDeviceProtocol', C.c_uint8), ('bMaxPacketSize0', C.c_uint8),
        ('idVendor', C.c_uint16), ('idProduct', C.c_uint16),
        ('bcdDevice', C.c_uint16),
        ('iManufacturer', C.c_uint8), ('iProduct', C.c_uint8),
        ('iSerialNumber', C.c_uint8), ('bNumConfigurations', C.c_uint8),
    ]


class UsbDevice(C.Structure):
    pass


UsbDevice._fields_ = [
    ('next', C.POINTER(UsbDevice)), ('prev', C.POINTER(UsbDevice)),
    ('filename', C.c_char * PATH_MAX),
    ('bus', C.c_void_p),
    ('descriptor', UsbDeviceDescriptor),
    ('config', C.c_void_p),
    ('dev', C.c_void_p),
    ('devnum', C.c_uint8),
    ('num_children', C.c_char),
    ('children', C.POINTER(C.POINTER(UsbDevice))),
]

UsbDeviceP = C.POINTER(UsbDevice)


class UsbBus(C.Structure):
    pass


UsbBus._fields_ = [
    ('next', C.POINTER(UsbBus)), ('prev', C.POINTER(UsbBus)),
    ('dirname', C.c_char * PATH_MAX),
    ('devices', UsbDeviceP),
    ('location', C.c_ulong),
    ('root_dev', UsbDeviceP),
]

UsbBusP = C.POINTER(UsbBus)


class Libusb0:
    def __init__(self, path=None):
        self.path = path or self._find()
        if not self.path:
            raise OSError('libusb0_device.dll / libusb0_dji.dll not found')
        self.dll = C.WinDLL(self.path)
        self._proto()

    @staticmethod
    def _find():
        for p in DEFAULT_DLLS:
            if os.path.exists(p):
                return p
        return None

    def _proto(self):
        d = self.dll
        d.usb_init.argtypes = [C.c_void_p]
        d.usb_init.restype = None
        d.usb_find_busses.restype = C.c_int
        d.usb_find_devices.restype = C.c_int
        d.usb_get_busses.restype = UsbBusP
        d.usb_open.argtypes = [UsbDeviceP]
        d.usb_open.restype = C.c_void_p
        d.usb_close.argtypes = [C.c_void_p]
        d.usb_close.restype = C.c_int
        d.usb_set_configuration.argtypes = [C.c_void_p, C.c_int]
        d.usb_set_configuration.restype = C.c_int
        d.usb_claim_interface.argtypes = [C.c_void_p, C.c_int]
        d.usb_claim_interface.restype = C.c_int
        d.usb_release_interface.argtypes = [C.c_void_p, C.c_int]
        d.usb_release_interface.restype = C.c_int
        d.usb_bulk_write.argtypes = [C.c_void_p, C.c_int, C.c_char_p,
                                     C.c_int, C.c_int]
        d.usb_bulk_write.restype = C.c_int
        d.usb_bulk_read.argtypes = [C.c_void_p, C.c_int, C.c_char_p,
                                    C.c_int, C.c_int]
        d.usb_bulk_read.restype = C.c_int
        d.usb_strerror.restype = C.c_char_p
        d.usb_get_descriptor.argtypes = [C.c_void_p, C.c_ubyte, C.c_ubyte,
                                         C.c_void_p, C.c_int]
        d.usb_get_descriptor.restype = C.c_int
        d.usb_get_string_simple.argtypes = [C.c_void_p, C.c_int, C.c_char_p,
                                            C.c_size_t]
        d.usb_get_string_simple.restype = C.c_int

    def err(self, rc):
        try:
            return self.dll.usb_strerror().decode('latin-1')
        except Exception:
            return 'error %d' % rc

    def scan(self):
        """Every device libusb0 can see, as dicts."""
        self.dll.usb_init(None)
        self.dll.usb_find_busses()
        self.dll.usb_find_devices()
        out = []
        bus = self.dll.usb_get_busses()
        while bus:
            b = bus.contents
            dev = b.devices
            while dev:
                d = dev.contents
                desc = d.descriptor
                out.append(dict(
                    dev=dev,
                    busname=b.dirname.decode('latin-1', 'replace'),
                    filename=d.filename.decode('latin-1', 'replace'),
                    devnum=d.devnum,
                    vid=desc.idVendor, pid=desc.idProduct,
                    bcd=desc.bcdDevice,
                    cfgcount=desc.bNumConfigurations,
                    sane=(desc.bLength == 18 and desc.bDescriptorType == 1),
                ))
                dev = d.next
            bus = b.next
        return out

    def open(self, dev):
        h = self.dll.usb_open(dev)
        if not h:
            raise OSError('usb_open failed: %s' % self.err(0))
        return h

    def claim(self, h, iface):
        d = self.dll
        rc = d.usb_set_configuration(h, 1)
        if rc < 0:
            raise OSError('set_configuration: %s' % self.err(rc))
        rc = d.usb_claim_interface(h, iface)
        if rc < 0:
            raise OSError('claim_interface %d: %s' % (iface, self.err(rc)))

    def write(self, h, ep, data, timeout=500):
        rc = self.dll.usb_bulk_write(h, ep, data, len(data), timeout)
        if rc < 0:
            raise OSError('bulk_write 0x%02x: %s' % (ep, self.err(rc)))
        return rc

    def read(self, h, ep, n=512, timeout=200):
        buf = C.create_string_buffer(n)
        rc = self.dll.usb_bulk_read(h, ep, buf, n, timeout)
        if rc < 0:
            return None
        return buf.raw[:rc]

    def close(self, h):
        try:
            self.dll.usb_close(h)
        except Exception:
            pass


def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    lib = Libusb0()
    print('dll:', lib.path)
    devs = lib.scan()
    print('devices:', len(devs))
    for d in devs:
        if d['vid'] == 0x2CA3 or not d['sane']:
            print('  sane=%s %04x:%04x devnum=%d bcd=%04x cfg=%d %s'
                  % (d['sane'], d['vid'], d['pid'], d['devnum'], d['bcd'],
                     d['cfgcount'], d['filename']))


if __name__ == '__main__':
    main()
