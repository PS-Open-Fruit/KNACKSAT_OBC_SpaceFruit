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
    parser = argparse.ArgumentParser(description="Scenario 3B: Image Downlink Aggressive Resume")
    parser.add_argument("--gs_port", type=str, default="COM4", help="Serial port for GS.py")
    parser.add_argument("--obc_port", type=str, default="COM5", help="Serial port for OBC.py")
    parser.add_argument("--baud", type=int, default=9600, help="Baud rate")
    parser.add_argument("--kill_interval", type=int, default=15, help="Seconds between GS termination")
    args = parser.parse_args()

    source_file = os.path.join("sd_card", "0.jpg")
    dest_file = os.path.join("downloads", "0.jpg")

    if not os.path.exists(source_file):
        print(f"[ERROR] Source file {source_file} not found.")
        sys.exit(1)

    if os.path.exists(dest_file):
        os.remove(dest_file)

    print(f"\n--- Starting Scenario 3B: Image Downlink Aggressive Resume ---")
    print(f"File: {source_file}, GS Port: {args.gs_port}, OBC Port: {args.obc_port}")
    print(f"Aggressive Kill Interval: {args.kill_interval}s")

    # 1. Start OBC (stays running throughout)
    obc_logs = []
    obc_proc = subprocess.Popen([sys.executable, "-u", "OBC.py", "--port", args.obc_port, "--baud", str(args.baud)], 
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    threading.Thread(target=read_output, args=(obc_proc, "OBC", obc_logs), daemon=True).start()

    time.sleep(2)

    total_size = os.path.getsize(source_file)
    success = False
    iteration = 1
    
    try:
        while not success:
            print(f"\n[ITERATION {iteration}] Starting GS and initiating/resuming download...")
            gs_logs = []
            gs_proc = subprocess.Popen([sys.executable, "-u", "GS.py", "--port", args.gs_port, "--baud", str(args.baud)], 
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            threading.Thread(target=read_output, args=(gs_proc, f"GS_IT{iteration}", gs_logs), daemon=True).start()

            time.sleep(1)
            gs_proc.stdin.write("download 0.jpg\n")
            gs_proc.stdin.flush()

            it_start = time.time()
            it_completed = False
            
            while time.time() - it_start < args.kill_interval:
                # Process logs
                while gs_logs:
                    t, n, line = gs_logs.pop(0)
                    print(f"[{n}] {line}")
                    if "Download Complete!" in line:
                        it_completed = True
                        success = True
                        break
                if it_completed:
                    break
                time.sleep(0.5)

            if success:
                print(f"\n[ITERATION {iteration}] DOWNLOAD COMPLETED SUCCESSFULLY!")
                gs_proc.terminate()
                gs_proc.wait()
                break
            
            # Simulated connection drop
            print(f"\n[ITERATION {iteration}] SIMULATING CONNECTION DROP (Terminating GS after {args.kill_interval}s)...")
            gs_proc.terminate()
            gs_proc.wait()
            
            if os.path.exists(dest_file):
                current_size = os.path.getsize(dest_file)
                print(f"Current progress: {current_size}/{total_size} bytes ({(current_size/total_size)*100:.1f}%)")
            
            iteration += 1
            time.sleep(3) # Small gap before next attempt

        print(f"\n--- Test Results ---")
        if success:
            src_md5 = get_md5(source_file)
            dst_md5 = get_md5(dest_file)
            print(f"Source MD5: {src_md5}")
            print(f"Dest   MD5: {dst_md5}")
            if src_md5 == dst_md5:
                print(f"[SUCCESS] MD5 verification PASSED after {iteration} resume cycles.")
            else:
                print("[FAIL] MD5 verification FAILED. Data corruption detected after multiple resumes.")
        else:
            print("[FAIL] Test failed to complete download.")

    except KeyboardInterrupt:
        print("\n[TEST] Interrupted by user.")
    finally:
        print("[TEST] Cleaning up...")
        if 'gs_proc' in locals() and gs_proc.poll() is None:
            gs_proc.terminate()
            gs_proc.wait()
        obc_proc.terminate()
        obc_proc.wait()

if __name__ == "__main__":
    main()
