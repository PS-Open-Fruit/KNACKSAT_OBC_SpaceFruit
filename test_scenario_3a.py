import subprocess
import time
import sys
import threading
import argparse
import os
import hashlib

def read_output(process, name, logger):
    """Utility to read and print subprocess output."""
    for line in iter(process.stdout.readline, ""):
        line = line.strip()
        if line:
            logger.append((time.time(), name, line))
    process.stdout.close()

def get_md5(fname):
    hash_md5 = hashlib.md5()
    with open(fname, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def main():
    parser = argparse.ArgumentParser(description="Scenario 3A: Image Downlink Success")
    parser.add_argument("--gs_port", type=str, default="COM4", help="Serial port for GS.py")
    parser.add_argument("--obc_port", type=str, default="COM5", help="Serial port for OBC.py")
    parser.add_argument("--baud", type=int, default=9600, help="Baud rate")
    args = parser.parse_args()

    source_file = os.path.join("sd_card", "0.jpg")
    dest_file = os.path.join("downloads", "0.jpg")

    if not os.path.exists(source_file):
        print(f"[ERROR] Source file {source_file} not found. Please ensure it exists.")
        sys.exit(1)

    if os.path.exists(dest_file):
        os.remove(dest_file)

    print(f"\n--- Starting Scenario 3A: Image Downlink Success ---")
    print(f"File: {source_file}, GS Port: {args.gs_port}, OBC Port: {args.obc_port}")

    logs = []

    # 1. Start OBC Emulator
    obc_cmd = [sys.executable, "-u", "OBC.py", "--port", args.obc_port, "--baud", str(args.baud)]
    obc_proc = subprocess.Popen(obc_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    threading.Thread(target=read_output, args=(obc_proc, "OBC", logs), daemon=True).start()

    # 2. Start Ground Station
    gs_cmd = [sys.executable, "-u", "GS.py", "--port", args.gs_port, "--baud", str(args.baud)]
    gs_proc = subprocess.Popen(gs_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    threading.Thread(target=read_output, args=(gs_proc, "GS", logs), daemon=True).start()

    time.sleep(2) # Wait for startup

    print("[TEST] Sending 'download 0.jpg' command to GS...")
    gs_proc.stdin.write("download 0.jpg\n")
    gs_proc.stdin.flush()
    
    start_time = time.time()
    success = False
    timeout = 240 # 4 minutes

    try:
        while time.time() - start_time < timeout:
            while logs:
                t, name, line = logs.pop(0)
                print(f"[{name}] {line}")
                if "Download Complete!" in line and "0.jpg" in line:
                    success = True
                    break
            
            if success:
                break
            time.sleep(0.5)

        elapsed = time.time() - start_time
        print(f"\n--- Test Results ---")
        if success:
            print(f"[SUCCESS] Download reported complete in {elapsed:.2f}s.")
            if os.path.exists(dest_file):
                src_md5 = get_md5(source_file)
                dst_md5 = get_md5(dest_file)
                print(f"Source MD5: {src_md5}")
                print(f"Dest   MD5: {dst_md5}")
                if src_md5 == dst_md5:
                    print("[SUCCESS] MD5 verification PASSED.")
                else:
                    print("[FAIL] MD5 verification FAILED. Data corruption detected.")
            else:
                print("[FAIL] Downloaded file not found in 'downloads/'.")
        else:
            print(f"[FAIL] Download timed out after {timeout}s.")

    finally:
        print("[TEST] Cleaning up processes...")
        obc_proc.terminate()
        gs_proc.terminate()
        obc_proc.wait()
        gs_proc.wait()

if __name__ == "__main__":
    main()
