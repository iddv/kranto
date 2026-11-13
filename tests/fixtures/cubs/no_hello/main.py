"""S9: prints a greeting that is not the protocol and sleeps."""
import os
import time

os.write(1, b"hello there\n")
time.sleep(60)
