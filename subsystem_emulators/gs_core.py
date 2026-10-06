import serial
import struct
import os
import time
import threading
import queue
import sys
import json
import socket
import argparse

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from Shared.Python.beacon_helper import *
from Shared.Python.kiss_protocol import KISSProtocol

DOWNLOADS_DIR = "downloads"
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

_PORTS = {
    'darwin': '/dev/cu.usbserial-A10OMHTZ',
    'win32':  'COM4',
    'linux':  '/dev/ttyUSB0',
}
DEFAULT_PORT = _PORTS.get(sys.platform, _PORTS['win32'])
DEFAULT_BAUD = 9600
DEFAULT_TCP_PORT = 58258

command_queue = queue.Queue()
connected_clients = []
clients_lock = threading.Lock()
latest_beacon_data = None
current_download_file = None

def colorize_raw_frame(frame: bytes) -> str:
    if len(frame) < 12: return frame.hex(' ').upper()
    parts = [
        f"\033[90m{frame[0:1].hex().upper()}\033[0m", # FEND
        f"\033[95m{frame[1:2].hex().upper()}\033[0m", # CMD
        f"\033[94m{frame[2:3].hex().upper()}\033[0m", # SeqNum
        f"\033[93m{frame[3:4].hex().upper()}\033[0m", # PayloadID
        f"\033[96m{frame[4:5].hex().upper()}\033[0m", # PID
        f"\033[92m{frame[5:7].hex(' ').upper()}\033[0m", # DataLen
    ]
    data_len = len(frame) - 12
    if data_len > 0:
        parts.append(f"\033[97m{frame[7:7+data_len].hex(' ').upper()}\033[0m") # Data
    parts.append(f"\033[91m{frame[-5:-1].hex(' ').upper()}\033[0m") # CRC
    parts.append(f"\033[90m{frame[-1:].hex().upper()}\033[0m") # FEND
    return " ".join(parts)

def build_custom_payload(payload_id: int, pid: int, seq_num: int, data: bytes) -> bytes:
    data_len = len(data)
    header = struct.pack('>BBBH', seq_num, payload_id, pid, data_len)
    content = header + data
    crc = KISSProtocol.calculate_crc(content)
    return content + struct.pack('>I', crc)

def parse_custom_payload(payload_bytes: bytes):
    if len(payload_bytes) < 9: 
        return None
    content = payload_bytes[:-4]
    received_crc = struct.unpack('>I', payload_bytes[-4:])[0]
    calculated_crc = KISSProtocol.calculate_crc(content)
    if received_crc != calculated_crc:
        return None
    seq_num, payload_id, pid, data_len = struct.unpack('>BBBH', content[:5])
    data = content[5:5+data_len]
    return payload_id, pid, seq_num, data

def broadcast_to_cli(msg_dict):
    """Sends JSON encoded message to all connected TCP CLI clients."""
    try:
        msg_bytes = (json.dumps(msg_dict) + "\n").encode('utf-8')
        with clients_lock:
            for c in connected_clients[:]:
                try:
                    c.sendall(msg_bytes)
                except Exception:
                    connected_clients.remove(c)
    except Exception as e:
        print(f"Broadcast error: {e}")

def handle_client(conn, addr):
    print(f"[TCP] CLI connected from {addr}")
    with clients_lock:
        connected_clients.append(conn)
    buffer = ""
    try:
        while True:
            data = conn.recv(4096)
            if not data:
                break
            buffer += data.decode('utf-8')
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line: continue
                try:
                    msg = json.loads(line)
                    cmd = msg.get("command", "").lower()
                    
                    if cmd == 'ping':
                        target = msg.get("target", "obc")
                        if target == 'obc':
                            command_queue.put(('MANUAL', 0x00, 0x00, "Request Ping (OBC)", b''))
                        else:
                            command_queue.put(('MANUAL', 0x01, 0x00, "Request Ping (VR)", b''))
                    elif cmd == 'list':
                        command_queue.put(('MANUAL', 0x00, 0x01, "Request List files (SD)", b''))
                    elif cmd == 'info':
                        fname = msg.get("filename", "").encode()
                        req_data = struct.pack('>B', len(fname)) + fname
                        command_queue.put(('MANUAL', 0x00, 0x02, "Request File Info (SD)", req_data))
                    elif cmd == 'download':
                        fname = msg.get("filename", "")
                        command_queue.put(('AUTO_DOWNLOAD', 0x00, 0x03, "Request File Data (SD)", fname))
                    elif cmd == 'status':
                        command_queue.put(('MANUAL', 0x00, 0x05, "Request System Status (OBC)", b''))
                    elif cmd == 'capture':
                        command_queue.put(('MANUAL', 0x01, 0x02, "Request Capture (VR)", b''))
                    elif cmd == 'copy':
                        command_queue.put(('MANUAL', 0x01, 0x03, "Request Copy Image to SD (VR)", b''))
                    elif cmd == 'shutdown':
                        command_queue.put(('MANUAL', 0x01, 0x90, "Request VR Shutdown", b''))
                    elif cmd == 'beacon':
                        global latest_beacon_data
                        broadcast_to_cli({
                            "type": "beacon_data",
                            "data": latest_beacon_data
                        })
                    else:
                        print(f"[TCP] Unknown command from CLI: {cmd}")
                except json.JSONDecodeError:
                    print("[TCP] Invalid JSON received")
    except ConnectionResetError:
        pass
    except Exception as e:
        print(f"[TCP] Client error: {e}")
    finally:
        with clients_lock:
            if conn in connected_clients:
                connected_clients.remove(conn)
        conn.close()
        print(f"[TCP] CLI disconnected from {addr}")

def tcp_server_thread(port):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(('127.0.0.1', port))
        server.listen(5)
        print(f"[TCP] Core Server listening on port {port}")
        while True:
            conn, addr = server.accept()
            threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()
    except Exception as e:
        print(f"[TCP] Server failed to start: {e}")

def main():
    parser = argparse.ArgumentParser(description="Ground Station Core")
    parser.add_argument("--port", type=str, default=DEFAULT_PORT, help=f"Serial port (default: {DEFAULT_PORT})")
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD, help=f"Baud rate (default: {DEFAULT_BAUD})")
    parser.add_argument("--tcp-port", type=int, default=DEFAULT_TCP_PORT, help="TCP Port for CLI (default: 58258)")
    parser.add_argument("--print-raw", action="store_true", help="Print color-coded raw frames to console")
    args = parser.parse_args()

    port = args.port
    baud = args.baud
    tcp_port = args.tcp_port
    print_raw = args.print_raw

    global latest_beacon_data, current_download_file
    
    try:
        ser = serial.Serial(port, baud, timeout=0.1)
    except Exception as e:
        print(f"[GS] Failed to open serial port: {e}")
        return
        
    print(f"[GS] Core Started on {port} at {baud} baud.")
    
    threading.Thread(target=tcp_server_thread, args=(tcp_port,), daemon=True).start()
    
    FEND_BYTE = bytes([KISSProtocol.FEND])
    rx_buffer = bytearray()
    DOWNLINK_WINDOW_SIZE = 5
    packets_received_in_window = 0
    
    dl_active = False
    dl_filename_bytes = b''
    dl_offset = 0
    dl_chunk_size = 350
    dl_total_size = 0
    dl_start_time = 0.0
    dl_session_start_offset = 0
    
    last_request_time = 0.0
    retry_count = 0
    MAX_RETRIES = 5
    ping_send_time = 0.0
    
    print("[GS] Starting RX/TX Loops...")
    
    while True:
        try:
            item = command_queue.get_nowait()
            
            if len(item) == 5 and item[0] == 'AUTO_DOWNLOAD':
                _, target_p_id, target_pid, desc, fname = item
                current_download_file = fname
                dl_filename_bytes = fname.encode()
                dl_offset = 0
                dl_session_start_offset = 0
                dl_active = True
                dl_total_size = 0
                dl_start_time = 0.0
                retry_count = 0
                last_request_time = time.time()
                
                if print_raw: print(f"\n[GS] --- Starting Download for '{fname}' ---")
                req_data = struct.pack('>B', len(dl_filename_bytes)) + dl_filename_bytes
                command_queue.put(('PRE_DOWNLOAD_INFO', 0x00, 0x02, "Auto-Request File Info", req_data))
                continue
                
            elif len(item) == 5 and item[0] in ['MANUAL', 'PRE_DOWNLOAD_INFO']:
                _, target_p_id, target_pid, desc, req_data = item
                if item[0] == 'MANUAL' and print_raw:
                    print(f"\n[GS] Sending: {desc} (PayloadID: 0x{target_p_id:02X}, PID: 0x{target_pid:02X})")
            else:
                target_p_id, target_pid, desc, req_data = item
                if print_raw:
                    print(f"\n[GS] Sending: {desc} (PayloadID: 0x{target_p_id:02X}, PID: 0x{target_pid:02X})")
                
            custom_payload = build_custom_payload(target_p_id, target_pid, 0x00, req_data) 
            req_frame = KISSProtocol.wrap_frame(custom_payload, command=0x00)
            
            if target_pid == 0x00: # Ping
                ping_send_time = time.time()
            
            if print_raw:
                print("  Color Legend: \033[90mFEND\033[0m \033[95mCMD\033[0m \033[94mSEQ\033[0m \033[93mPL_ID\033[0m \033[96mPID\033[0m \033[92mLEN\033[0m \033[97mDATA\033[0m \033[91mCRC\033[0m \033[90mFEND\033[0m")
                print(f"  -> TX Raw Frame: {colorize_raw_frame(req_frame)}")
                
            ser.write(req_frame)
            
            if dl_active:
                last_request_time = time.time()
            
            packets_received_in_window = 0
        except queue.Empty:
            if dl_active and last_request_time > 0 and (time.time() - last_request_time > 2.0):
                if retry_count < MAX_RETRIES:
                    if print_raw: print(f"     \033[93m[GS] Timeout waiting for offset {dl_offset}. Retrying {retry_count + 1}/{MAX_RETRIES}...\033[0m")
                    req_data = struct.pack('>B', len(dl_filename_bytes)) + dl_filename_bytes + struct.pack('>IH', dl_offset, dl_chunk_size)
                    command_queue.put(('MANUAL', 0x00, 0x03, "Auto-Request Chunk Retry", req_data))
                    last_request_time = time.time()
                    retry_count += 1
                else:
                    msg = "Max retries reached. Download aborted."
                    if print_raw: print(f"     \033[91m[GS] {msg}\033[0m")
                    broadcast_to_cli({"type": "download_error", "message": msg})
                    dl_active = False
            pass

        byte = ser.read(1)
        if byte:
            if byte == FEND_BYTE:
                rx_buffer += byte
                if len(rx_buffer) >= 3:
                    unwrapped = KISSProtocol.unwrap_frame(bytes(rx_buffer))
                    if unwrapped:
                        if print_raw: print(f"  <- RX Raw Frame: {colorize_raw_frame(rx_buffer)}")
                        cmd, payload_bytes = unwrapped
                        parsed = parse_custom_payload(payload_bytes)
                        if parsed:
                            p_id, pid, seq, data = parsed
                            
                            if cmd == 0x01:
                                if print_raw: print(f"  <- Received Response [PayloadID: 0x{p_id:02X}, PID: 0x{pid:02X}, Seq: {seq}]")
                                try:
                                    if p_id == 0x00:
                                        if pid == 0x00: # Ping
                                            delay = (time.time() - ping_send_time) * 1000
                                            broadcast_to_cli({"type": "ping", "target": "OBC", "delay_ms": delay})
                                            
                                        elif pid == 0x01: # List Files
                                            num_files = data[0]
                                            files = []
                                            offset = 1
                                            for _ in range(num_files):
                                                name_len = data[offset]
                                                name = data[offset+1 : offset+1+name_len].decode()
                                                files.append(name)
                                                offset += 1 + name_len
                                            broadcast_to_cli({"type": "file_list", "files": files})
                                                
                                        elif pid == 0x02: # File Info
                                            status, size, ts = struct.unpack('>BII', data)
                                            broadcast_to_cli({
                                                "type": "file_info", 
                                                "status": status, 
                                                "size": size, 
                                                "timestamp": ts
                                            })
                                            
                                            if dl_active and dl_total_size == 0:
                                                if status == 0x00:
                                                    dl_total_size = size
                                                    dl_start_time = time.time()
                                                    filepath = os.path.join(DOWNLOADS_DIR, current_download_file)
                                                    if os.path.exists(filepath):
                                                        partial = os.path.getsize(filepath)
                                                        if 0 < partial < size:
                                                            dl_offset = partial
                                                            dl_session_start_offset = partial
                                                            broadcast_to_cli({"type": "download_msg", "message": f"Partial file found ({partial}/{size} B). Resuming..."})
                                                        else:
                                                            dl_offset = 0
                                                            dl_session_start_offset = 0
                                                    else:
                                                        dl_offset = 0
                                                        dl_session_start_offset = 0
                                                        
                                                    req_data = struct.pack('>B', len(dl_filename_bytes)) + dl_filename_bytes + struct.pack('>IH', dl_offset, dl_chunk_size)
                                                    command_queue.put(('MANUAL', 0x00, 0x03, "Auto-Request File Initial", req_data))
                                                else:
                                                    broadcast_to_cli({"type": "download_error", "message": "Target file not found. Auto-download aborted."})
                                                    dl_active = False
                                            
                                        elif pid == 0x03: # File Data
                                            status, offset, dl = struct.unpack('>BIH', data[:7])
                                            chunk = data[7:7+dl]
                                            
                                            if dl_active:
                                                last_request_time = time.time()
                                                
                                            if status == 0x00 and dl > 0:
                                                if offset != dl_offset and dl_active:
                                                    if print_raw: print(f"     \033[93m[GS] Ignored out-of-sync chunk (Expected: {dl_offset}, Got: {offset})\033[0m")
                                                else:
                                                    if current_download_file is not None:
                                                        filepath = os.path.join(DOWNLOADS_DIR, current_download_file)
                                                        mode = 'r+b' if os.path.exists(filepath) and offset > 0 else 'wb'
                                                        try:
                                                            with open(filepath, mode) as f:
                                                                f.seek(offset)
                                                                f.write(chunk)
                                                                
                                                            if dl_total_size > 0:
                                                                progress = min(1.0, (offset + dl) / dl_total_size)
                                                                elapsed = time.time() - dl_start_time
                                                                bytes_this_session = (offset + dl) - dl_session_start_offset
                                                                speed = bytes_this_session / elapsed if elapsed > 0 else 0
                                                                rem_bytes = dl_total_size - (offset + dl)
                                                                eta = rem_bytes / speed if speed > 0 else 0
                                                                
                                                                broadcast_to_cli({
                                                                    "type": "download_progress",
                                                                    "progress": progress,
                                                                    "downloaded": offset + dl,
                                                                    "total": dl_total_size,
                                                                    "speed": speed,
                                                                    "eta": eta
                                                                })
                                                            
                                                            if dl_active and dl == dl_chunk_size:
                                                                dl_offset += dl_chunk_size
                                                                retry_count = 0
                                                                if dl_total_size > 0 and dl_offset >= dl_total_size:
                                                                    elapsed_time = time.time() - dl_start_time
                                                                    broadcast_to_cli({
                                                                        "type": "download_complete",
                                                                        "filename": current_download_file,
                                                                        "time": elapsed_time
                                                                    })
                                                                    dl_active = False
                                                            elif dl_active and dl < dl_chunk_size:
                                                                elapsed_time = time.time() - dl_start_time
                                                                broadcast_to_cli({
                                                                    "type": "download_complete",
                                                                    "filename": current_download_file,
                                                                    "time": elapsed_time
                                                                })
                                                                dl_active = False
                                        
                                                        except Exception as e:
                                                            broadcast_to_cli({"type": "download_error", "message": f"Save Error: {e}"})
                                                            dl_active = False
                                            else:
                                                if dl_active:
                                                    broadcast_to_cli({"type": "download_error", "message": "End of file reached unexpectedly or error occurred."})
                                                    dl_active = False
                                        
                                        elif pid == 0x04: # EPS Beacon
                                            ret_beacon_dict = decode_beacon_packet(data)
                                            if ret_beacon_dict:
                                                latest_beacon_data = ret_beacon_dict
                                                timestamp = time.strftime("%H:%M:%S")
                                                broadcast_to_cli({"type": "beacon_alert", "time": timestamp})

                                        elif pid == 0x05: # System Status
                                            expected_len = struct.calcsize('>IBBIIIBiBBB')
                                            if len(data) != expected_len:
                                                if print_raw: print(f"     \033[93m[GS] System Status length mismatch: got {len(data)}B, expected {expected_len}B\033[0m")
                                            else:
                                                status_data = struct.unpack('>IBBIIIBiBBB', data)
                                                broadcast_to_cli({
                                                    "type": "system_status",
                                                    "data": status_data
                                                })
                                            
                                    elif p_id == 0x01:
                                        if pid == 0x00: # Ping
                                            delay = (time.time() - ping_send_time) * 1000
                                            broadcast_to_cli({"type": "ping", "target": "VR", "delay_ms": delay})
                                            
                                        elif pid == 0x01: # Pi Status
                                            ts, up, cpu_l, cpu_t, ram, disk, cam = struct.unpack('>IIBbBBB3x', data)
                                            broadcast_to_cli({
                                                "type": "vr_status",
                                                "data": {"time": ts, "up": up, "cpu_l": cpu_l, "cpu_t": cpu_t, "ram": ram, "disk": disk, "cam": cam}
                                            })
                                            
                                        elif pid == 0x02: # Capture
                                            status, name_len = struct.unpack('>BB', data[:2])
                                            name = data[2:2+name_len].decode()
                                            broadcast_to_cli({"type": "capture", "status": status, "file": name})

                                        elif pid == 0x03: # Copy Image to SD
                                            status = struct.unpack('>B', data[:1])[0]
                                            broadcast_to_cli({"type": "copy_sd", "status": status})

                                        elif pid == 0x90: # Shutdown VR Pi
                                            broadcast_to_cli({"type": "vr_shutdown", "status": "ACK received"})

                                except Exception as e:
                                    if print_raw: print(f"     \033[91mParse Error:\033[0m {e} (Raw: {data.hex()})")
                                
                                packets_received_in_window += 1
                                
                                if dl_active and packets_received_in_window >= DOWNLINK_WINDOW_SIZE:
                                    packets_received_in_window = 0
                                    req_data = struct.pack('>B', len(dl_filename_bytes)) + dl_filename_bytes + struct.pack('>IH', dl_offset, dl_chunk_size)
                                    if print_raw: print(f"[GS] Window complete. Requesting next window at offset {dl_offset}")
                                    command_queue.put(('MANUAL', 0x00, 0x03, "Auto-Request Next Window", req_data))

                rx_buffer = bytearray(FEND_BYTE)
            else:
                if len(rx_buffer) > 0:
                    rx_buffer += byte

if __name__ == '__main__':
    main()

