#!/usr/bin/env python3
"""
Raspberry Pi VR Subsystem - Ground-Driven Sliding Window Protocol
Based on RF-Benchmark ground-driven architecture
"""
import os
import sys
import time
import struct
import subprocess
import serial

# Add Shared library path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
try:
    from Shared.Python.kiss_protocol import KISSProtocol
except ImportError:
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
    from Shared.Python.kiss_protocol import KISSProtocol

# Protocol Commands
CMD_PING = 0x10
CMD_STATUS = 0x11
CMD_CAPTURE = 0x12
CMD_FILE_INFO = 0x14
CMD_REQUEST = 0x15
CMD_REQUEST_ACK = 0x16
CMD_SYNC = 0x17
CMD_BURST = 0x18
CMD_REPORT = 0x19
CMD_FINAL = 0x1A
CMD_DATA = 0x00

# Configuration
DEFAULT_MTU = 256
DEFAULT_WINDOW = 12
DEFAULT_MAX_ROUNDS = 100
CHUNK_SIZE = DEFAULT_MTU - 14  # Payload capacity per chunk

# ==========================================
# Hardware Access
# ==========================================

def get_rpi_temp():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            return float(f.read()) / 1000.0
    except:
        return 25.0

def get_cpu_load():
    try:
        return os.getloadavg()[0] * 10.0
    except:
        return 10.0

def get_free_ram():
    try:
        with open('/proc/meminfo', 'r') as f:
            for line in f:
                if 'MemAvailable' in line:
                    return int(line.split()[1]) // 1024
    except:
        return 256

def get_disk_free():
    try:
        s = os.statvfs('/')
        return (s.f_bavail * s.f_frsize) // (1024 * 1024)
    except:
        return 0

def get_uptime():
    try:
        with open('/proc/uptime', 'r') as f:
            return int(float(f.read().split()[0]))
    except:
        return 0

def get_throttled():
    try:
        output = subprocess.check_output(["vcgencmd", "get_throttled"]).decode()
        return int(output.split('=')[1], 0)
    except:
        return 0

# ==========================================
# SSDV Utilities
# ==========================================

def ensure_baseline_jpeg(input_file, output_file):
    try:
        cmd = ["convert", input_file, "-strip", "-interlace", "None", 
               "-type", "TrueColor", "-sampling-factor", "2x2", output_file]
        print(f"   ⚙️ Converting to Baseline JPEG: {' '.join(cmd)}")
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as e:
        print(f"   ⚠️ ImageMagick failed: {e}")
        if input_file != output_file:
            try:
                with open(input_file, 'rb') as f_in, open(output_file, 'wb') as f_out:
                    f_out.write(f_in.read())
            except:
                pass
        return False

def encode_ssdv(input_image, output_bin, callsign="KNCK", img_id=1):
    try:
        cmd = ["ssdv", "-e", "-c", callsign, "-i", str(img_id), input_image, output_bin]
        print(f"   🎞️ Encoding SSDV: {' '.join(cmd)}")
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        if os.path.exists(output_bin):
            return os.path.getsize(output_bin)
    except Exception as e:
        print(f"   ⚠️ SSDV Encoding Failed: {e}")
    
    return 0

def sha1_file(filepath):
    import hashlib
    sha1 = hashlib.sha1()
    with open(filepath, 'rb') as f:
        while chunk := f.read(8192):
            sha1.update(chunk)
    return sha1.hexdigest()

# ==========================================
# Image Capture
# ==========================================

def capture_image(img_id):
    filename = f"mission_img_{img_id:04d}.jpg"
    ssdv_file = f"mission_img_{img_id:04d}.bin"
    
    cmd = [
        "rpicam-still", 
        "-o", filename, 
        "-t", "500",
        "--width", "1280",   
        "--height", "960",
        "--nopreview"
    ]
    
    try:
        print(f"   📸 Capturing: {filename}...")
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, 
                      stderr=subprocess.DEVNULL, timeout=5)
        
        if os.path.exists(filename):
            # Convert to baseline
            ensure_baseline_jpeg(filename, filename)
            
            # Encode to SSDV
            ssdv_size = encode_ssdv(filename, ssdv_file, callsign="KNCK", img_id=img_id)
            
            if ssdv_size > 0:
                print(f"   ✅ SSDV Ready: {ssdv_file} ({ssdv_size} bytes)")
                return ssdv_file, ssdv_size
    except subprocess.TimeoutExpired:
        print("   ❌ Camera Timed Out!")
    except Exception as e:
        print(f"   ❌ Camera Error: {e}")
    
    return None, 0

# ==========================================
# Ground-Driven Protocol Handler
# ==========================================

class RPiVRSatellite:
    def __init__(self, port='/dev/ttyACM0', baudrate=115200, 
                 mtu=DEFAULT_MTU, window=DEFAULT_WINDOW, max_rounds=DEFAULT_MAX_ROUNDS):
        self.port = port
        self.baudrate = baudrate
        self.serial_conn = None
        self.running = False
        
        self.mtu = mtu
        self.window_size = window
        self.max_rounds = max_rounds
        self.chunk_size = mtu - 14
        
        self.img_counter = 0
        self.last_captured_file = None
        self.current_data = None
        self.current_filename = None

    def send_msg(self, payload):
        """Send a KISS-framed message with CRC."""
        data_to_crc = bytearray([KISSProtocol.CMD_DATA]) + payload
        crc = KISSProtocol.calculate_crc(data_to_crc)
        
        full_payload = bytearray(payload)
        full_payload.extend(struct.pack('<I', crc))
        
        tx = KISSProtocol.wrap_frame(full_payload)
        self.serial_conn.write(tx)

    def send_file_info(self, filename, data):
        """Send FILE_INFO response."""
        file_sha1 = sha1_file(filename) if os.path.exists(filename) else "0" * 40
        total_chunks = (len(data) + self.chunk_size - 1) // self.chunk_size
        
        # Payload: [CMD] [filename_len:1] [filename] [size:4] [sha1:40] [mtu:2] [chunks:2]
        resp = bytearray([CMD_FILE_INFO])
        filename_bytes = os.path.basename(filename).encode('utf-8')[:64]
        resp.append(len(filename_bytes))
        resp.extend(filename_bytes)
        resp.extend(struct.pack('<I', len(data)))
        resp.extend(file_sha1.encode('ascii'))
        resp.extend(struct.pack('<HH', self.mtu, total_chunks))
        
        self.send_msg(resp)
        print(f"   📋 FILE_INFO: {os.path.basename(filename)}, {len(data)} bytes, {total_chunks} chunks")

    def send_request_ack(self, ok=True, reason=""):
        """Send REQUEST_ACK response."""
        resp = bytearray([CMD_REQUEST_ACK])
        resp.append(1 if ok else 0)
        if not ok:
            reason_bytes = reason.encode('utf-8')[:32]
            resp.append(len(reason_bytes))
            resp.extend(reason_bytes)
        
        self.send_msg(resp)
        print(f"   {'✅' if ok else '❌'} REQUEST_ACK: {ok}")

    def send_sync(self, run_id, total_chunks):
        """Send SYNC message to start transfer."""
        resp = bytearray([CMD_SYNC])
        resp.extend(struct.pack('<HHH', run_id, self.mtu, total_chunks))
        resp.extend(struct.pack('<I', len(self.current_data)))
        
        self.send_msg(resp)
        print(f"   🔄 SYNC: run_id={run_id}, chunks={total_chunks}")

    def send_burst(self, run_id, seqs):
        """Send BURST announcement."""
        resp = bytearray([CMD_BURST])
        resp.extend(struct.pack('<H', run_id))
        resp.append(len(seqs))
        for seq in seqs:
            resp.extend(struct.pack('<H', seq))
        
        self.send_msg(resp)

    def send_data_frame(self, run_id, seq, total_chunks, chunk_data):
        """Send a data frame (fixed MTU)."""
        # Frame: [DATA_CMD] [Magic:2] [RunID:2] [Seq:2] [Total:2] [Len:2] [Payload:N] [CRC:4]
        MAGIC = 0xA55A
        payload_len = len(chunk_data)
        padded_payload = chunk_data + (b'\x00' * (self.chunk_size - payload_len))
        
        frame = bytearray([CMD_DATA])
        frame.extend(struct.pack('>HHHHH', MAGIC, run_id, seq, total_chunks, payload_len))
        frame.extend(padded_payload)
        
        # Calculate frame CRC (over entire frame including KISS command byte)
        data_to_crc = bytearray([KISSProtocol.CMD_DATA]) + frame
        frame_crc = KISSProtocol.calculate_crc(data_to_crc)
        frame.extend(struct.pack('<I', frame_crc))
        
        # KISS wrap and send
        tx = KISSProtocol.wrap_frame(frame)
        self.serial_conn.write(tx)

    def handle_capture(self):
        """Handle CAPTURE command from ground."""
        self.img_counter += 1
        
        captured_file, size = capture_image(self.img_counter)
        
        if captured_file and size > 0:
            self.last_captured_file = captured_file
            self.current_data = open(captured_file, 'rb').read()
            self.current_filename = captured_file
            
            self.send_file_info(captured_file, self.current_data)
        else:
            print("   ❌ Capture failed")

    def handle_request(self, filename):
        """Handle REQUEST command from ground."""
        if self.current_data is None or self.current_filename is None:
            self.send_request_ack(False, "no_file")
            return
        
        if os.path.basename(self.current_filename) != filename:
            self.send_request_ack(False, "not_found")
            return
        
        self.send_request_ack(True)
        
        # Start transfer
        print(f"   🚀 Starting transfer of {filename}")
        self.transmit_file()

    def transmit_file(self):
        """Transmit file using sliding window protocol."""
        import random
        
        data = self.current_data
        total_chunks = (len(data) + self.chunk_size - 1) // self.chunk_size
        chunks = [data[i * self.chunk_size:(i + 1) * self.chunk_size] 
                  for i in range(total_chunks)]
        
        run_id = random.randint(1, 65535)
        
        # Send SYNC
        self.send_sync(run_id, total_chunks)
        time.sleep(0.1)  # Allow ground to process
        
        pending = set(range(total_chunks))
        rounds = 0
        
        print(f"   📡 Transmitting {total_chunks} chunks...")
        
        while pending and rounds < self.max_rounds:
            seqs = sorted(pending)[:self.window_size]
            
            self.send_burst(run_id, seqs)
            time.sleep(0.01)
            
            # Send frames
            for seq in seqs:
                self.send_data_frame(run_id, seq, total_chunks, chunks[seq])
                time.sleep(0.01)  # Small gap
            
            # Wait for REPORT
            report = self.wait_for_message(CMD_REPORT, timeout=5.0)
            rounds += 1
            
            if not report:
                print(f"   ⚠️ Round {rounds}: No REPORT (timeout)")
                continue
            
            # Parse REPORT: [CMD] [run_id:2] [missing_count:1] [missing_ids...]
            if len(report) < 3:
                continue
            
            report_run_id = struct.unpack('<H', report[:2])[0]
            if report_run_id != run_id:
                continue
            
            missing_count = report[2]
            missing = set()
            offset = 3
            for i in range(missing_count):
                if offset + 2 <= len(report):
                    miss_id = struct.unpack('<H', report[offset:offset+2])[0]
                    missing.add(miss_id)
                    offset += 2
            
            pending = missing
            
            received = total_chunks - len(pending)
            progress = (received / total_chunks * 100) if total_chunks > 0 else 0
            print(f"   ⏳ Round {rounds:02d}: {received}/{total_chunks} ({progress:.1f}%) | Missing: {len(pending)}")
            
            if not pending:
                print(f"   ✅ Transfer complete in {rounds} rounds!")
                break
        
        if pending:
            print(f"   ⚠️ Transfer incomplete: {len(pending)} chunks missing after {rounds} rounds")

    def wait_for_message(self, expected_cmd, timeout=5.0):
        """Wait for a specific message type."""
        start = time.time()
        buffer = bytearray()
        
        while (time.time() - start) < timeout:
            if self.serial_conn.in_waiting > 0:
                chunk = self.serial_conn.read(self.serial_conn.in_waiting)
                buffer.extend(chunk)
                
                # Try to extract frame
                while buffer:
                    fend_idx = buffer.find(KISSProtocol.FEND, 1)
                    if fend_idx == -1:
                        break
                    
                    frame = buffer[:fend_idx+1]
                    buffer = buffer[fend_idx+1:]
                    
                    if len(frame) <= 2:
                        continue
                    
                    if frame[0] != KISSProtocol.FEND or frame[-1] != KISSProtocol.FEND:
                        continue
                    
                    result = KISSProtocol.unwrap_frame(frame)
                    if not result:
                        continue
                    
                    kiss_cmd, payload = result
                    
                    if kiss_cmd != KISSProtocol.CMD_DATA or len(payload) < 5:
                        continue
                    
                    # Validate CRC
                    rx_crc = struct.unpack('<I', payload[-4:])[0]
                    data_to_check = bytearray([kiss_cmd]) + payload[:-4]
                    calc_crc = KISSProtocol.calculate_crc(data_to_check)
                    
                    if calc_crc != rx_crc:
                        continue
                    
                    app_cmd = payload[0]
                    app_payload = payload[1:-4]
                    
                    if app_cmd == CMD_PING:
                        self.send_msg(bytearray([CMD_PING, 0x01]))
                        # Reset timeout since we received a ping
                        start = time.time()
                    elif app_cmd == expected_cmd:
                        return app_payload
            
            time.sleep(0.01)
        
        return None

    def handle_status_request(self):
        """Handle status request."""
        cpu = int(get_cpu_load())
        temp = get_rpi_temp()
        ram = get_free_ram()
        disk = get_disk_free()
        uptime = get_uptime()
        throttled = get_throttled()
        
        resp = bytearray([CMD_STATUS])
        resp.extend(struct.pack("<BfHIIH", cpu, temp, ram, disk, uptime, throttled))
        
        self.send_msg(resp)

    def handle_frame(self, frame_bytes):
        """Handle incoming KISS frame."""
        result = KISSProtocol.unwrap_frame(frame_bytes)
        if not result:
            return
        
        kiss_cmd, payload = result
        
        if kiss_cmd != KISSProtocol.CMD_DATA or len(payload) < 5:
            return
        
        # Validate CRC
        rx_crc = struct.unpack('<I', payload[-4:])[0]
        data_to_check = bytearray([kiss_cmd]) + payload[:-4]
        calc_crc = KISSProtocol.calculate_crc(data_to_check)
        
        if calc_crc != rx_crc:
            return
        
        cmd_id = payload[0]
        app_payload = payload[1:-4]
        
        if cmd_id == CMD_PING:
            # Echo back
            self.send_msg(bytearray([CMD_PING, 0x01]))
        
        elif cmd_id == CMD_STATUS:
            self.handle_status_request()
        
        elif cmd_id == CMD_CAPTURE:
            self.handle_capture()
        
        elif cmd_id == CMD_REQUEST:
            # Parse filename
            if len(app_payload) > 0:
                filename_len = app_payload[0]
                if len(app_payload) >= 1 + filename_len:
                    filename = app_payload[1:1+filename_len].decode('utf-8', errors='ignore')
                    self.handle_request(filename)

    def start(self):
        print(f"--- 🍓 Raspberry Pi VR (Ground-Driven) ---")
        print(f"Target Port: {self.port}")
        print(f"MTU: {self.mtu}, Window: {self.window_size}, Max Rounds: {self.max_rounds}")
        
        while True:
            try:
                if not os.path.exists(self.port):
                    print(f"Waiting for device {self.port}...", end='\r')
                    time.sleep(1)
                    continue
                
                self.serial_conn = serial.Serial(self.port, self.baudrate, timeout=0.1)
                self.running = True
                print(f"\n✅ Connected to OBC! Listening...")
                self.listen_loop()
                
            except serial.SerialException as e:
                print(f"❌ Serial Error: {e}")
                time.sleep(1)
            except KeyboardInterrupt:
                print("\nExiting...")
                exit()

    def listen_loop(self):
        buffer = bytearray()
        while self.running:
            try:
                if self.serial_conn.in_waiting > 0:
                    chunk = self.serial_conn.read(self.serial_conn.in_waiting)
                    buffer.extend(chunk)
                    
                    # Extract frames
                    while buffer:
                        fend_idx = buffer.find(KISSProtocol.FEND, 1)
                        if fend_idx == -1:
                            break
                        
                        frame = buffer[:fend_idx+1]
                        buffer = buffer[fend_idx+1:]
                        
                        if len(frame) > 2 and frame[0] == KISSProtocol.FEND and frame[-1] == KISSProtocol.FEND:
                            self.handle_frame(frame)
                    
                    # Prevent buffer overflow
                    if len(buffer) > 4096:
                        buffer = buffer[-2048:]
                        
            except OSError:
                print("\n⚠️ Device Disconnected!")
                self.running = False
                self.serial_conn.close()
                return

if __name__ == "__main__":
    sat = RPiVRSatellite('/dev/ttyACM0', baudrate=115200, 
                          mtu=256, window=12, max_rounds=100)
    sat.start()
