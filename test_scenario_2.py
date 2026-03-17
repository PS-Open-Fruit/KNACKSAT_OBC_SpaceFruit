import subprocess
import time
import sys
import threading
import argparse
import os
import re

def read_output(process, name, logger):
    """Utility to read and print subprocess output."""
    for line in iter(process.stdout.readline, ""):
        line = line.strip()
        if line:
            logger.append((time.time(), name, line))
            # print(f"[{name}] {line}")
    process.stdout.close()

def main():
    parser = argparse.ArgumentParser(description="Scenario 2: Passive Link Monitoring")
    parser.add_argument("--gs_port", type=str, default="COM4", help="Serial port for GS.py")
    parser.add_argument("--obc_port", type=str, default="COM5", help="Serial port for OBC.py")
    parser.add_argument("--baud", type=int, default=9600, help="Baud rate")
    parser.add_argument("--interval", type=float, default=30.0, help="Beacon interval to test")
    args = parser.parse_args()

    print(f"\n--- Starting Scenario 2: Passive Link Monitoring ---")
    print(f"GS Port: {args.gs_port}, OBC Port: {args.obc_port}, Interval: {args.interval}s")

    logs = []

    # 1. Start OBC Emulator with beacons enabled
    obc_cmd = [sys.executable, "-u", "OBC.py", "--port", args.obc_port, "--baud", str(args.baud), "--beacon", "--interval", str(args.interval)]
    obc_proc = subprocess.Popen(obc_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    threading.Thread(target=read_output, args=(obc_proc, "OBC", logs), daemon=True).start()

    # 2. Start Ground Station
    gs_cmd = [sys.executable, "-u", "GS.py", "--port", args.gs_port, "--baud", str(args.baud)]
    gs_proc = subprocess.Popen(gs_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    threading.Thread(target=read_output, args=(gs_proc, "GS", logs), daemon=True).start()

    print(f"[TEST] Waiting for beacons (test duration: {args.interval * 4}s)...")
    
    beacon_times = []
    start_test = time.time()
    test_duration = args.interval * 4 + 10 # capture ~4 cycles
    
    try:
        while time.time() - start_test < test_duration:
            # Check logs for beacons
            while logs:
                t, name, line = logs.pop(0)
                if name == "GS" and "--- EPS SENSOR DATA ---" in line:
                    print(f"[PASSIVE MONITOR] Received Beacon at {time.ctime(t)}")
                    beacon_times.append(t)
                
                # Print output to console for visibility
                print(f"[{name}] {line}")
            
            time.sleep(1)
            
            if len(beacon_times) >= 4:
                break

        print("\n--- Test Results ---")
        if len(beacon_times) < 2:
            print(f"[FAIL] Only received {len(beacon_times)} beacons. Need at least 2 for interval check.")
        else:
            intervals = []
            for i in range(1, len(beacon_times)):
                diff = beacon_times[i] - beacon_times[i-1]
                intervals.append(diff)
                print(f"Beacon Interval {i}: {diff:.2f}s")
            
            all_pass = True
            for i, val in enumerate(intervals):
                if not (args.interval - 1.0 <= val <= args.interval + 1.0):
                    print(f"[FAIL] Interval {i+1} ({val:.2f}s) outside tolerance ({args.interval} +/- 1.0s)")
                    all_pass = False
            
            if all_pass:
                print(f"[SUCCESS] Beacon timing is consistent at {args.interval}s.")
            else:
                print(f"[FAIL] Beacon timing is inconsistent.")

    except KeyboardInterrupt:
        print("\n[TEST] Interrupted by user.")
    finally:
        print("[TEST] Cleaning up processes...")
        obc_proc.terminate()
        gs_proc.terminate()
        obc_proc.wait()
        gs_proc.wait()

if __name__ == "__main__":
    main()
