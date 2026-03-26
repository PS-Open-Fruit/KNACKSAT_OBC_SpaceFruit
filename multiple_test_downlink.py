import subprocess
import os
import random
import sys
import argparse
import time

# ANSI Color Codes for the runner
CLR_CYAN = "\033[96m"
CLR_GREEN = "\033[92m"
CLR_RESET = "\033[0m"

def main():
    parser = argparse.ArgumentParser(description="Wrapper to run Scenario 3B multiple times with random kill intervals.")
    parser.add_argument("--runs", type=int, default=5, help="Number of stress test iterations to run.")
    parser.add_argument("--min_kill", type=int, default=5, help="Minimum kill interval (seconds).")
    parser.add_argument("--max_kill", type=int, default=25, help="Maximum kill interval (seconds).")
    parser.add_argument("--script", type=str, default="test_resume_downlink.py", help="Name of the target script to run.")
    args = parser.parse_args()

    output_dir = "downlink_stress_tests"
    
    # Create the output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    print(f"{CLR_CYAN}[RUNNER] Output directory set to: ./{output_dir}/{CLR_RESET}")

    if not os.path.exists(args.script):
        print(f"Error: Could not find '{args.script}'. Please ensure it is in the same directory.")
        sys.exit(1)

    for i in range(1, args.runs + 1):
        print(f"\n{CLR_CYAN}{'='*50}{CLR_RESET}")
        print(f"{CLR_CYAN}[RUNNER] Starting Master Test Run {i} of {args.runs}{CLR_RESET}")
        print(f"{CLR_CYAN}{'='*50}{CLR_RESET}")

        # Generate random kill interval
        kill_interval = random.randint(args.min_kill, args.max_kill)
        
        # Generate incremented file names
        csv_filename = os.path.join(output_dir, f"run{i}_telemetry.csv")
        kills_csv_filename = os.path.join(output_dir, f"run{i}_kills.csv")

        # Build the command to call the target script
        cmd = [
            sys.executable, "-u", args.script,
            "--kill_interval", str(kill_interval),
            "--csv", csv_filename,
            "--kills_csv", kills_csv_filename
        ]

        print(f"{CLR_CYAN}[RUNNER] Selected kill_interval: {kill_interval}s{CLR_RESET}")
        print(f"{CLR_CYAN}[RUNNER] Telemetry CSV: {csv_filename}{CLR_RESET}")
        print(f"{CLR_CYAN}[RUNNER] Kills CSV: {kills_csv_filename}{CLR_RESET}")
        print(f"{CLR_CYAN}[RUNNER] Executing subprocess...{CLR_RESET}\n")

        time.sleep(1) # Brief pause for readability

        # Run the script and wait for it to finish
        try:
            subprocess.run(cmd, check=True)
            print(f"\n{CLR_GREEN}[RUNNER] Master Test Run {i} completed successfully.{CLR_RESET}")
        except subprocess.CalledProcessError as e:
            print(f"\n[RUNNER] Master Test Run {i} failed with return code {e.returncode}.")
        except KeyboardInterrupt:
            print("\n[RUNNER] Interrupted by user. Exiting test suite.")
            sys.exit(0)
            
        time.sleep(2) # Give the OS a moment to clean up file handles before the next run

    print(f"\n{CLR_CYAN}[RUNNER] All {args.runs} stress tests finished! Check the '{output_dir}' folder for results.{CLR_RESET}")

if __name__ == "__main__":
    main()