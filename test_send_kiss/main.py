import serial
import time
import struct
import sys
import os
import threading

# Import KISS Protocol from Shared/Python
current_dir = os.path.dirname(os.path.abspath(__file__))
shared_path = os.path.join(os.path.dirname(os.path.dirname(current_dir)), 'OBC_SpaceFruit', 'Shared', 'Python')
# Ensure correct path (adjusting for potential CWD differences)
# If script is in d:\github\OBC_SpaceFruit\test_send_kiss\main.py
# Shared is in d:\github\OBC_SpaceFruit\Shared\Python
shared_path = os.path.abspath(os.path.join(current_dir, '..', 'Shared', 'Python'))

if shared_path not in sys.path:
    sys.path.append(shared_path)

try:
    from kiss_protocol import KISSProtocol
except ImportError:
    print("Error: Could not import KISSProtocol. Check path.")
    sys.exit(1)

# Configuration
SERIAL_PORT = 'COM5' 
BAUD_RATE = 209700

# Global State
rx_buffer = bytearray()
image_chunks = {}
current_filename = ""
available_files = [] # List of filenames from List response
last_chunk_time = 0
running = True

def send_command_12(ser):
    print("Sending Command 0x12...")
    cmd = 0x12
    # CRC calculated on [0x12]
    crc = KISSProtocol.calculate_crc(bytes([cmd]))
    print(f"CMD: {hex(cmd)}, CRC: {hex(crc)}")
    
    # Payload is just the CRC (Command is added by wrap_frame)
    payload_crc = struct.pack('<I', crc)
    
    # wrap_frame(payload, command) -> FEND [0x12] [CRC] FEND
    frame = KISSProtocol.wrap_frame(payload_crc, cmd)
    print(f"Sending Packet: {frame.hex().upper()}")
    
    ser.write(frame)

def send_command_start_file(ser, filename="01261311.jpg"):
    print(f"Sending Command Start File (0x00 0x13) + File: {filename}...")
    cmd = 0x00
    sub_cmd = 0x13
    
    # Encode and pad/truncate to exactly 12 bytes
    fname_bytes = filename.encode('utf-8')
    if len(fname_bytes) > 12:
        fname_bytes = fname_bytes[:12]
    elif len(fname_bytes) < 12:
        fname_bytes = fname_bytes + b'\x00' * (12 - len(fname_bytes))
    
    # CRC calculated on [0x00, 0x13] + [Filename 12 bytes]
    crc_data = bytes([cmd, sub_cmd]) + fname_bytes
    crc = KISSProtocol.calculate_crc(crc_data)
    print(f"CMD: {hex(cmd)} {hex(sub_cmd)}, File: {filename}, CRC: {hex(crc)}")
    
    # Payload is [0x13] + [Filename] + [CRC]
    payload = bytes([sub_cmd]) + fname_bytes + struct.pack('<I', crc)
    
    # wrap_frame -> FEND [0x00] [0x13] [Filename] [CRC] FEND
    frame = KISSProtocol.wrap_frame(payload, cmd)
    print(f"Sending Packet: {frame.hex().upper()}")
    
    ser.write(frame)

def send_command_list_files(ser):
    print("Sending Command List Files (0x00 0x10)...")
    cmd = 0x00
    sub_cmd = 0x10
    
    # CRC calculated on [0x00, 0x10]
    crc_data = bytes([cmd, sub_cmd])
    crc = KISSProtocol.calculate_crc(crc_data)
    print(f"CMD: {hex(cmd)} {hex(sub_cmd)}, CRC: {hex(crc)}")
    
    # Payload is [0x10] + [CRC]
    payload = bytes([sub_cmd]) + struct.pack('<I', crc)
    
    frame = KISSProtocol.wrap_frame(payload, cmd)
    print(f"Sending Packet: {frame.hex().upper()}")
    ser.write(frame)

def save_image():
    global image_chunks, current_filename
    if not image_chunks: return
    
    filename = f"received_{current_filename}" if current_filename else f"received_image_{int(time.time())}.jpg"
    print(f"\n[INFO] Saving {len(image_chunks)} chunks to {filename}...")
    
    sorted_ids = sorted(image_chunks.keys())
    
    with open(filename, "wb") as f:
        for cid in sorted_ids:
            f.write(image_chunks[cid])
            
    print(f"[SUCCESS] Saved {filename} ({os.path.getsize(filename)} bytes)\n")
    image_chunks.clear()

def process_frame(frame):
    global current_filename, last_chunk_time, image_chunks, available_files
    
    result = KISSProtocol.unwrap_frame(frame)
    if not result: return
    
    cmd, payload = result
    
    # Debug Print
    if cmd != 0x00:
        print(f"[KISS CMD {hex(cmd)}] Payload: {payload.hex().upper()}")
    
    # Image Chunk Handling (CMD=0x00, SubCMD=0x13)
    if cmd == 0x00 and len(payload) > 17 and payload[0] == 0x13:
        try:
            chunk_id = struct.unpack('<I', payload[1:5])[0]
            fname = payload[5:17].decode('utf-8', errors='ignore').strip('\x00')
            
            data_len = len(payload) - 17 - 4
            data = payload[17:17+data_len]
            
            if current_filename != fname and fname:
                if image_chunks: 
                     save_image()
                current_filename = fname
                print(f"\n[START] Receving File: {fname}")

            image_chunks[chunk_id] = data
            last_chunk_time = time.time()
            
            if chunk_id % 10 == 0:
                sys.stdout.write(f"\rRx Chunk: {chunk_id}, Bytes: {len(data)}   ")
                sys.stdout.flush()

        except Exception as e:
            print(f"\nError parsing chunk: {e}")

    # List Files Response (CMD=0x00, SubCMD=0x11)
    elif cmd == 0x00 and len(payload) > 5 and payload[0] == 0x11:
        print("\n--- File List ---")
        available_files = [] # Clear previous list
        try:
            # Payload: [0x11] [File1:16] ... [FileN:16] [CRC:4]
            data = payload[1:-4]
            num_files = len(data) // 16
            
            print(f"{'#':<4} {'Filename':<15} {'Size (Bytes)':<12}")
            print("-" * 35)
            
            for i in range(num_files):
                entry = data[i*16 : (i+1)*16]
                if len(entry) < 16: break
                
                fname = entry[:12].decode('utf-8', errors='ignore').strip('\x00')
                fsize = struct.unpack('<I', entry[12:16])[0]
                
                available_files.append(fname)
                print(f"{i+1:<4} {fname:<15} {fsize:<12}")
                
            print("-" * 35 + "\n")
            
        except Exception as e:
            print(f"Error parsing file list: {e}")
    
    # ... (Other logic) ...

    elif cmd == 0x00:
        # Other Data
        try:
            ascii_str = payload.decode('ascii', errors='ignore')
            if len(ascii_str) > 0 and ascii_str[0] not in ['\x11', '\x13']:
                 print(f"[STM32 MSG]: {ascii_str}")
        except:
            print(f"[STM32 DATA]: {payload.hex().upper()}")

def serial_listener(ser):
    global rx_buffer, last_chunk_time, running
    
    while running:
        try:
            if ser.in_waiting:
                chunk = ser.read(ser.in_waiting)
                rx_buffer.extend(chunk)
                
                # Process Frames
                while KISSProtocol.FEND in rx_buffer:
                    try:
                        fend_idx = rx_buffer.index(KISSProtocol.FEND)
                    except ValueError:
                        break
                        
                    if fend_idx == 0:
                        try:
                             next_fend = rx_buffer.index(KISSProtocol.FEND, 1)
                             frame = rx_buffer[0:next_fend+1]
                             process_frame(frame)
                             del rx_buffer[0:next_fend] 
                        except ValueError:
                            break
                    else:
                        del rx_buffer[0:fend_idx]
            
            # Check Timeout (Auto-save)
            if image_chunks and (time.time() - last_chunk_time > 2.0):
                save_image()
            
            time.sleep(0.005)
        except Exception as e:
            print(f"Serial Error: {e}")
            break

def main():
    global running, available_files
    try:
        port = SERIAL_PORT
        ser = serial.Serial(port, BAUD_RATE, timeout=0.01)
        print(f"Opened {port} at {BAUD_RATE}")
        
        # Start Serial Thread
        t = threading.Thread(target=serial_listener, args=(ser,), daemon=True)
        t.start()
        
        while True:
            print("\nCommands:")
            print("1. Send C0 12 xx xx xx xx C0 (Forward to USB)")
            print("2. Send 0x00 0x13 (Start File Transfer - Default)")
            print("3. Send 0x00 0x10 (List Files & Select)")
            print("q. Quit")
            
            choice = input("Enter choice: ").strip()
            
            if choice == '1':
                send_command_12(ser)
            elif choice == '2':
                send_command_start_file(ser)
            elif choice == '3':
                available_files = [] # Clear
                send_command_list_files(ser)
                print("Waiting for file list...")
                
                # Wait for up to 3 seconds for response
                msg_received = False
                for _ in range(30):
                    if available_files:
                        msg_received = True
                        break
                    time.sleep(0.1)
                
                if msg_received:
                    # Give a moment for printing to finish
                    time.sleep(0.5) 
                    
                    # Prompt for selection immediately
                    while True:
                        sel = input(f"Enter File # to download (1-{len(available_files)}, q to cancel): ").strip()
                        if sel.lower() == 'q':
                            break
                        try:
                            idx = int(sel)
                            if 1 <= idx <= len(available_files):
                                target = available_files[idx-1]
                                send_command_start_file(ser, target)
                                break
                            else:
                                print("Invalid number.")
                        except ValueError:
                            print("Invalid input.")
                else:
                    print("No response or empty list.")

            elif choice.lower() == 'q':
                running = False
                break
                
    except Exception as e:
        print(f"Error: {e}")
        print(f"Ensure '{SERIAL_PORT}' is correct and not in use.")

if __name__ == "__main__":
    main()
