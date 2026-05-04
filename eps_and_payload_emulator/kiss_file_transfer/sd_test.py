import io
import board
import busio
import digitalio
import adafruit_sdcard
from pyfatfs.PyFatFS import PyFatFS

class SDBlockAdapter(io.RawIOBase):
    def __init__(self, sdcard):
        self.sd = sdcard
        self._offset = 0
        # Calculate total size in bytes once during init
        self._total_size = self.sd.count() * 512 

    def seek(self, offset, whence=io.SEEK_SET):
        if whence == io.SEEK_SET:
            self._offset = offset
        elif whence == io.SEEK_CUR:
            self._offset += offset
        elif whence == io.SEEK_END:
            self._offset = self._total_size + offset
        return self._offset

    def tell(self):
        return self._offset

    def read(self, size=-1):
        if size == -1:
            size = 512
            
        data = bytearray()
        remaining = size
        current_offset = self._offset
        
        while remaining > 0:
            block_num = current_offset // 512
            block_offset = current_offset % 512
            block = bytearray(512)
            
            # Read physical block
            self.sd.readblocks(block_num, block)
            
            to_take = min(remaining, 512 - block_offset)
            data.extend(block[block_offset:block_offset + to_take])
            
            current_offset += to_take
            remaining -= to_take
            
        self._offset = current_offset
        return bytes(data)

    def write(self, b):
        data = bytes(b) if not isinstance(b, bytes) else b
        data_len = len(data)
        current_offset = self._offset
        written = 0
        
        while written < data_len:
            block_num = current_offset // 512
            block_offset = current_offset % 512
            block = bytearray(512)
            
            # Read-Modify-Write required for unaligned writes
            self.sd.readblocks(block_num, block)
            
            to_write = min(data_len - written, 512 - block_offset)
            block[block_offset:block_offset + to_write] = data[written:written + to_write]
            
            # Write physical block back
            self.sd.writeblocks(block_num, block)
            
            current_offset += to_write
            written += to_write
            
        self._offset = current_offset
        return written

# Initialize hardware
spi = busio.SPI(board.SCK, MOSI=board.MOSI, MISO=board.MISO)
cs = digitalio.DigitalInOut(board.D8)
sd_hardware = adafruit_sdcard.SDCard(spi, cs)

# Wrap the hardware in your adapter
drive_adapter = SDBlockAdapter(sd_hardware)

# --- MOUNTING WORKAROUND ---
# Because PyFatFS expects a filename string and uses standard Python open(),
# we bypass the standard init by instantiating it with no args (or a dummy), 
# then manually overriding its internal filesystem 'device' with our adapter.

fs = PyFatFS.__new__(PyFatFS) 
fs.fs = fs.FAT_CLASS(drive_adapter) 
fs.fs.parse()

# Now you can interact with files ON the SD card
print(fs.listdir("/"))