# autoreload_runner.py
import os
import sys
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import subprocess

WATCH_EXTS = {".py"}


class RestartHandler(FileSystemEventHandler):
    def __init__(self, restart_cb):
        self.restart_cb = restart_cb

    def on_modified(self, event):
        if event.is_directory:
            return
        _, ext = os.path.splitext(event.src_path)
        if ext in WATCH_EXTS:
            print("File changed:", event.src_path)
            self.restart_cb()


def run_app(argv):
    # Start the app as a subprocess so we can kill/restart it cleanly
    return subprocess.Popen([sys.executable] + argv)


def main(argv):
    proc = run_app(argv)

    def restart():
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        # start a fresh process
        nonlocal_proc = run_app(argv)
        # replace outer proc reference
        globals()["_proc_ref"][0] = nonlocal_proc

    # small trick to mutate proc from inner scope
    globals()["_proc_ref"] = [proc]

    event_handler = RestartHandler(lambda: restart())
    observer = Observer()
    observer.schedule(event_handler, path=".", recursive=True)
    observer.start()
    print("Watching for changes. Press Ctrl-C to exit.")
    try:
        while True:
            time.sleep(1)
            # keep main thread alive
            proc = globals()["_proc_ref"][0]
            if proc.poll() is not None:
                # child exited; restart it automatically
                globals()["_proc_ref"][0] = run_app(argv)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
    # ensure child is terminated
    try:
        globals()["_proc_ref"][0].terminate()
    except Exception:
        pass


if __name__ == "__main__":
    main(sys.argv[1:] or ["ui.py"])
