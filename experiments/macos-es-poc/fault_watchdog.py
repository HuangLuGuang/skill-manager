#!/usr/bin/env python3
import os
import signal
import sys
import time


def send(groups, signal_number):
    for group in groups:
        try:
            os.killpg(group, signal_number)
        except ProcessLookupError:
            pass


def main():
    delay, grace, *groups = sys.argv[1:]
    groups = [int(group) for group in groups]
    time.sleep(float(delay))
    send(groups, signal.SIGTERM if float(grace) else signal.SIGKILL)
    if float(grace):
        time.sleep(float(grace))
        send(groups, signal.SIGKILL)


if __name__ == "__main__":
    main()
