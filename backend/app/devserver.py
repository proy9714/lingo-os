"""Development API server with auto-reload that is safe on Windows.

On Windows, uvicorn's reloader stops its worker by sending Ctrl+C to the whole
console. Under `npm run dev` that console is shared with Vite, so every backend
edit used to stop the web server too. Here uvicorn runs on its own hidden console
(CREATE_NO_WINDOW), and its output is passed through to this terminal.

Run with: uv run --project backend python -m app.devserver
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
CREATE_NO_WINDOW = 0x08000000


def main() -> int:
    command = [
        sys.executable, "-m", "uvicorn", "app.main:create_app", "--factory",
        "--reload", "--reload-dir", str(APP_DIR), "--port", "8787",
    ]
    flags = CREATE_NO_WINDOW if sys.platform == "win32" else 0
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        cwd=APP_DIR.parent,
        creationflags=flags,
    )
    try:
        assert process.stdout is not None
        for line in iter(process.stdout.readline, b""):
            sys.stdout.buffer.write(line)
            sys.stdout.flush()
        return process.wait()
    except KeyboardInterrupt:
        return 0
    finally:
        if process.poll() is None:
            if sys.platform == "win32":  # take the reloader and its worker down together
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True)
            else:
                process.terminate()


if __name__ == "__main__":
    sys.exit(main())
