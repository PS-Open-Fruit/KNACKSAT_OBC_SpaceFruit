import subprocess
import sys

# Start the capture process
gs_proc = subprocess.Popen([sys.executable, "-u", "capturepicture.py"], 
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)