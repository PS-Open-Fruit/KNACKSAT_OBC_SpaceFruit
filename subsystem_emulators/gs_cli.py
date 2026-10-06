import socket
import threading
import json
import sys
import argparse
import time

def print_prompt():
    print("GS> ", end="", flush=True)

def print_beacon(data):
    if not data:
        print("\033[91mNo beacon data available.\033[0m")
        return
        
    print("\n\033[1;36m" + "="*40 + "\033[0m")
    print("\033[1;36m--- EPS SENSOR DATA ---\033[0m")
    for idx, vi in enumerate(data.get("eps", {}).get("vi_sensors", [])):
        print(f"\033[92mVI Sensor {idx}\033[0m   | \033[93mV: {vi['voltage']} mV, I: {vi['current']} mA, Ch: {vi['channel']}, State: {vi['data_state']}\033[0m")
    
    for idx, out in enumerate(data.get("eps", {}).get("output_sensors", [])):
        print(f"\033[92mOut Sensor {idx}\033[0m  | \033[93mV: {out['voltage']} mV, I: {out['current']} mA, Ch: {out['channel']}, State: {out['data_state']}\033[0m")

    for idx, out_state in enumerate(data.get("eps", {}).get("output_states", [])):
        print(f"\033[92mOut State {idx}\033[0m   | \033[93mStatus: {out_state['status']}, Ch: {out_state['channel']}, State: {out_state['data_state']}\033[0m")

    for idx, temp in enumerate(data.get("eps", {}).get("battery_temps", [])):
        print(f"\033[92mBatt Temp {idx}\033[0m   | \033[93mTemp: {temp['temperature']:.2f} °C, Ch: {temp['channel']}, State: {temp['data_state']}\033[0m")

    print("\n\033[1;36m--- RTC DATETIME ---\033[0m")
    r = data.get("rtc", {})
    if r:
        print(f"\033[97m20{r['year']:02d}-{r['month']:02d}-{r['day']:02d} {r['hour']:02d}:{r['min']:02d}:{r['sec']:02d} (WDay: {r['wday']})\033[0m")

    print("\n\033[1;36m--- TMP1075 SENSOR ---\033[0m")
    print(f"\033[97mRaw Temp Value: {data.get('tmp1075', {}).get('raw_temp', 'N/A')}\033[0m")
    print("\033[1;36m" + "="*40 + "\033[0m\n")

def receive_thread(client_socket):
    buffer = ""
    try:
        while True:
            data = client_socket.recv(4096)
            if not data:
                print("\n\033[91mConnection to Core lost.\033[0m")
                sys.exit(1)
            buffer += data.decode('utf-8')
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line: continue
                try:
                    msg = json.loads(line)
                    mtype = msg.get("type")
                    
                    # Force a newline over the GS> prompt for async messages
                    print("\r" + " "*50 + "\r", end="")
                    
                    if mtype == "ping":
                        target = msg.get("target")
                        delay = msg.get("delay_ms")
                        print(f"Ping Response from {target} Received! time={delay:.1f}ms")
                    
                    elif mtype == "file_list":
                        files = msg.get("files", [])
                        print(f"Found {len(files)} files:")
                        for f in files:
                            print(f"  - {f}")
                            
                    elif mtype == "file_info":
                        status = msg.get("status")
                        s_str = "OK" if status == 0 else "Error"
                        print(f"File Info -> Status: {s_str} | Size: {msg.get('size')} bytes | Created: {msg.get('timestamp')}")
                        
                    elif mtype == "download_msg":
                        print(f"[Download] {msg.get('message')}")
                        
                    elif mtype == "download_progress":
                        progress = msg.get("progress", 0)
                        speed = msg.get("speed", 0)
                        eta = msg.get("eta", 0)
                        dl = msg.get("downloaded", 0)
                        total = msg.get("total", 0)
                        
                        bar_len = 30
                        filled = int(bar_len * progress)
                        bar = '=' * filled + '-' * (bar_len - filled)
                        speed_str = f"{speed / 1024:.1f} KB/s" if speed >= 1024 else f"{speed:.1f} B/s"
                        
                        print(f"\033[96m[{bar}] {progress*100:.1f}% ({dl}/{total} B) | {speed_str} | ETA: {eta:.1f}s\033[0m")
                        
                    elif mtype == "download_complete":
                        print(f"\033[92mDownload Complete! '{msg.get('filename')}' retrieved in {msg.get('time'):.2f}s\033[0m")
                        
                    elif mtype == "download_error":
                        print(f"\033[91mDownload Error: {msg.get('message')}\033[0m")
                        
                    elif mtype == "beacon_alert":
                        print(f"\033[93m[!] Beacon received at {msg.get('time')}. Type 'beacon' to view.\033[0m")
                        
                    elif mtype == "beacon_data":
                        print_beacon(msg.get("data"))
                        
                    elif mtype == "system_status":
                        data = msg.get("data")
                        if len(data) == 11:
                            (obc_boot, usb_bus, eps_status, p_boot, p_ts, p_up, p_cpu_l, p_cpu_t_milli, p_ram, p_disk, p_cam) = data
                            usb_str = "OK" if usb_bus == 0x00 else "Busy"
                            eps_str = "OK" if eps_status == 0x00 else "No Response"
                            cam_str = {0:"Err", 1:"Ready", 2:"Busy"}.get(p_cam, "Unknown")
                            print(f"System Status -> OBC Boot: {obc_boot} | USB: {usb_str} | EPS: {eps_str}")
                            print(f"                 Payload Boot: {p_boot} | Time: {p_ts} | Up: {p_up}s")
                            print(f"                 CPU: {p_cpu_l}% ({p_cpu_t_milli/1000.0:.3f}C) | RAM: {p_ram}% | Disk: {p_disk}%")
                            print(f"                 CAM: {cam_str}")
                            
                    elif mtype == "vr_status":
                        d = msg.get("data")
                        cam_str = {0:"Err", 1:"Ready", 2:"Busy"}.get(d['cam'], "Unknown")
                        print(f"Pi Status -> Time: {d['time']} | Up: {d['up']}s | CPU: {d['cpu_l']}% ({d['cpu_t']}C) | RAM: {d['ram']}% | Disk: {d['disk']}% | CAM: {cam_str}")
                        
                    elif mtype == "capture":
                        print(f"Capture -> Status: {msg.get('status')} | File: {msg.get('file')}")
                        
                    elif mtype == "copy_sd":
                        status = msg.get('status')
                        s_str = "OK" if status == 0 else "Error"
                        print(f"Copy to SD -> Status: {s_str} ({status})")
                        
                    elif mtype == "vr_shutdown":
                        print(f"VR Shutdown -> {msg.get('status')}")
                        
                    print_prompt()
                except json.JSONDecodeError:
                    print("\n[Error] Failed to parse message from Core")
                    print_prompt()
    except Exception as e:
        print(f"\n[Error] Receive thread error: {e}")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Ground Station CLI")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Core IP address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=58258, help="Core TCP Port (default: 58258)")
    args = parser.parse_args()

    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        client.connect((args.host, args.port))
    except Exception as e:
        print(f"\033[91mFailed to connect to Ground Station Core at {args.host}:{args.port}. Is it running?\033[0m")
        return

    print("\n\033[1;33m--- Ground Station CLI ---\033[0m")
    print("Type 'help' for a list of available commands.")
    
    threading.Thread(target=receive_thread, args=(client,), daemon=True).start()

    while True:
        try:
            print_prompt()
            choice = sys.stdin.readline().strip()
            if not choice:
                continue
            
            parts = choice.split()
            cmd = parts[0].lower()
            
            if cmd == 'help':
                print("Commands:")
                print("  ping <obc|vr>         - Ping subsystem")
                print("  list                  - List files on OBC SD card")
                print("  info <filename>       - Request file info")
                print("  download <filename>   - Download file from OBC")
                print("  status                - Request System Status (via OBC)")
                print("  capture               - Request Image Capture")
                print("  copy                  - Request Copy Image to SD")
                print("  shutdown              - Shutdown the VR Raspberry Pi")
                print("  beacon                - Display latest parsed beacon data")
                print("  exit                  - Exit Ground Station")
            elif cmd == 'ping':
                if len(parts) > 1 and parts[1].lower() in ['obc', 'vr']:
                    client.sendall((json.dumps({"command": "ping", "target": parts[1].lower()}) + "\n").encode())
                else:
                    print("Usage: ping <obc|vr>")
            elif cmd in ['list', 'status', 'capture', 'copy', 'shutdown', 'beacon']:
                client.sendall((json.dumps({"command": cmd}) + "\n").encode())
            elif cmd in ['info', 'download']:
                if len(parts) > 1:
                    client.sendall((json.dumps({"command": cmd, "filename": parts[1]}) + "\n").encode())
                else:
                    print(f"Usage: {cmd} <filename>")
            elif cmd == 'exit':
                print("Exiting...")
                client.close()
                sys.exit(0)
            else:
                print(f"Unknown command: {choice}. Type 'help' for commands.")
        except Exception as e:
            print(f"Input Error: {e}")

if __name__ == '__main__':
    main()

