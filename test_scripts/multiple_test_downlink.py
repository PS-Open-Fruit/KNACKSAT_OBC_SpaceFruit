import subprocess
import os
import random
import sys
import argparse
import time
import csv

# ANSI Color Codes for console output
CLR_CYAN = "\033[96m"
CLR_GREEN = "\033[92m"
CLR_RED = "\033[91m"
CLR_RESET = "\033[0m"

def main():
    parser = argparse.ArgumentParser(description="Wrapper to run Scenario 3B and output an MD5 summary to CSV.")
    parser.add_argument("--runs", type=int, default=5, help="Number of stress test iterations to run.")
    parser.add_argument("--min_kill", type=int, default=5, help="Minimum kill interval (seconds).")
    parser.add_argument("--max_kill", type=int, default=25, help="Maximum kill interval (seconds).")
    parser.add_argument("--script", type=str, default="test_resume_downlink.py", help="Name of the target script to run.")
    args = parser.parse_args()

    output_dir = "downlink_stress_tests"
    os.makedirs(output_dir, exist_ok=True)
    
    if not os.path.exists(args.script):
        print(f"Error: Could not find '{args.script}'. Please ensure it is in the same directory.")
        sys.exit(1)

    # Dictionary to store our final results summary
    results_summary = []

    for i in range(1, args.runs + 1):
        print(f"\n{CLR_CYAN}{'='*50}{CLR_RESET}")
        print(f"{CLR_CYAN}[RUNNER] Starting Master Test Run {i} of {args.runs}{CLR_RESET}")
        print(f"{CLR_CYAN}{'='*50}{CLR_RESET}")

        kill_interval = random.randint(args.min_kill, args.max_kill)
        csv_filename = os.path.join(output_dir, f"run{i}_telemetry.csv")
        kills_csv_filename = os.path.join(output_dir, f"run{i}_kills.csv")

        cmd = [
            sys.executable, "-u", args.script,
            "--kill_interval", str(kill_interval),
            "--csv", csv_filename,
            "--kills_csv", kills_csv_filename
        ]

        print(f"{CLR_CYAN}[RUNNER] Selected kill_interval: {kill_interval}s{CLR_RESET}")

        md5_status = "UNKNOWN (Did not finish)"

        try:
            # Use Popen to read the output line-by-line in real-time
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            
            for line in process.stdout:
                line_stripped = line.strip()
                if line_stripped:
                    print(line_stripped) # Print to console
                    
                    # Look for the MD5 result strings in the output
                    if "MD5 verification PASSED" in line_stripped:
                        md5_status = "PASSED"
                    elif "MD5 verification FAILED" in line_stripped:
                        md5_status = "FAILED"
                    elif "Skipping MD5 verification" in line_stripped:
                        md5_status = "SKIPPED (No local file)"

            process.wait()
            
            if process.returncode != 0:
                print(f"\n{CLR_RED}[RUNNER] Master Test Run {i} failed with return code {process.returncode}.{CLR_RESET}")
                md5_status = "CRASHED"
                
        except KeyboardInterrupt:
            print("\n[RUNNER] Interrupted by user. Exiting test suite.")
            break # Exit the loop but still save the summary of runs completed so far
            
        # Store the result for the final summary
        results_summary.append({
            "run": i,
            "kill_interval": kill_interval,
            "md5_status": md5_status
        })

        time.sleep(2) 

    # --- PRINT CONSOLE SUMMARY ---
    print(f"\n\n{CLR_CYAN}=================================================={CLR_RESET}")
    print(f"{CLR_CYAN}            FINAL STRESS TEST SUMMARY             {CLR_RESET}")
    print(f"{CLR_CYAN}=================================================={CLR_RESET}")
    print(f"{'Run #':<10} | {'Kill Interval':<15} | {'MD5 Result'}")
    print("-" * 50)
    
    passes = 0
    for res in results_summary:
        status = res['md5_status']
        color = CLR_GREEN if status == "PASSED" else CLR_RED if "FAIL" in status or "CRASH" in status else CLR_RESET
        print(f"Run {res['run']:<5} | {res['kill_interval']:<13} s | {color}{status}{CLR_RESET}")
        
        if status == "PASSED":
            passes += 1
            
    # Calculate totals
    total_completed = len(results_summary)
    success_rate = (passes / total_completed * 100) if total_completed > 0 else 0
    
    print("-" * 50)
    print(f"Total Runs: {total_completed} | MD5 Passes: {passes} | Success Rate: {success_rate:.1f}%\n")

    # --- SAVE TO CSV FILE ---
    summary_csv_path = os.path.join(output_dir, "md5_summary_report.csv")
    try:
        with open(summary_csv_path, mode="w", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            # Write the header row
            writer.writerow(["Run Number", "Kill Interval (s)", "MD5 Result"])
            
            # Write the data rows
            for res in results_summary:
                writer.writerow([res["run"], res["kill_interval"], res["md5_status"]])
                
        print(f"{CLR_CYAN}[RUNNER] Summary CSV saved to: {summary_csv_path}{CLR_RESET}")
    except Exception as e:
        print(f"{CLR_RED}[ERROR] Failed to save summary CSV file: {e}{CLR_RESET}")

if __name__ == "__main__":
    main()