#!/usr/bin/env python3
"""
Alcmaeon Lite -- launcher / first-run setup
===========================================

Double-click a launcher and this file does the rest. On the first run it
builds a private virtual environment next to the app and installs numpy,
matplotlib and pyserial into it, showing a small progress window while it
works. Every run after that starts straight into the app.

Nothing is installed system-wide and nothing is left behind outside this
folder: delete `.venv/` and it is as if it never ran.

Manual use, if you ever want it:
    python bootstrap.py              set up if needed, then launch
    python bootstrap.py --repair     rebuild the environment from scratch
    python bootstrap.py --build      build a standalone executable
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import traceback
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
VENV_DIR = APP_DIR / ".venv"
REQUIREMENTS = APP_DIR / "requirements.txt"
VENDOR_DIR = APP_DIR / "vendor"          # optional offline wheelhouse
READY_MARKER = VENV_DIR / ".alcmaeon-ready"
ENTRY_POINT = APP_DIR / "run_alcmaeon.py"

# import name -> pip name
REQUIRED = {"numpy": "numpy", "matplotlib": "matplotlib", "serial": "pyserial"}

WINDOWS = os.name == "nt"

# Matches the app's own theme so setup doesn't look like a different program.
BG = "#1f2023"
SURFACE = "#2a2b2f"
TEXT = "#e3e5e8"
MUTED = "#8a9098"
BLUE = "#6E9BC5"
WARN = "#c87a68"


# ---------------------------------------------------------------------------
# Environment probing
# ---------------------------------------------------------------------------

def missing_packages(python: str | None = None) -> list[str]:
    """Which requirements are not importable by `python` (default: this one)."""
    if python is None:
        gone = []
        for module in REQUIRED:
            try:
                __import__(module)
            except ImportError:
                gone.append(module)
        return gone

    code = ("import importlib.util,sys;"
            "print(','.join(m for m in sys.argv[1:] "
            "if importlib.util.find_spec(m) is None))")
    try:
        out = subprocess.run([python, "-c", code, *REQUIRED],
                             capture_output=True, text=True, timeout=90)
        return [m for m in out.stdout.strip().split(",") if m]
    except Exception:
        return list(REQUIRED)


def venv_python_candidates(windowed: bool = False) -> list[Path]:
    """Every name the interpreter might have inside our venv."""
    if WINDOWS:
        names = ["pythonw.exe", "python.exe"] if windowed else ["python.exe"]
        names.append("python3.exe")
        return [VENV_DIR / "Scripts" / n for n in names]
    return [VENV_DIR / "bin" / n for n in ("python", "python3")]


def venv_python(windowed: bool = False) -> Path:
    """The interpreter inside our venv -- first one that exists."""
    candidates = venv_python_candidates(windowed)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def interpreter_works(python) -> bool:
    """Can this file actually be executed as Python?

    A venv can be left behind that looks complete but cannot run: copied
    between machines or operating systems, interrupted midway, or with its
    base interpreter upgraded or uninstalled underneath it. Executing it then
    fails with "Exec format error" or similar, so check before relying on it.
    """
    try:
        done = subprocess.run([str(python), "-c", "import sys"],
                              capture_output=True, timeout=60)
        return done.returncode == 0
    except OSError:
        return False          # not executable on this machine at all
    except Exception:
        return False


def usable_venv_python(windowed: bool = False) -> Path | None:
    """A venv interpreter that exists AND runs, or None if it is broken."""
    for candidate in venv_python_candidates(windowed):
        if candidate.exists() and interpreter_works(candidate):
            return candidate
    return None


def describe_venv() -> str:
    """A short diagnostic of what is in .venv, for the failure log."""
    lines = []
    for candidate in venv_python_candidates():
        if candidate.is_symlink():
            target = os.readlink(candidate)
            ok = "ok" if candidate.exists() else "TARGET MISSING"
            lines.append(f"{candidate.name} -> {target} ({ok})")
        elif candidate.exists():
            lines.append(f"{candidate.name}: {candidate.stat().st_size} bytes")
        else:
            lines.append(f"{candidate.name}: missing")
    return "; ".join(lines)


def pip_works(python) -> bool:
    """True if `python -m pip` runs. A venv without ensurepip has no pip."""
    try:
        done = subprocess.run([str(python), "-m", "pip", "--version"],
                              capture_output=True, timeout=90)
        return done.returncode == 0
    except Exception:
        return False


def apt_hint() -> str:
    """The exact package Debian/Ubuntu split out of the standard library."""
    return f"sudo apt install python3.{sys.version_info.minor}-venv python3-tk"


def has_tkinter() -> bool:
    try:
        import tkinter  # noqa: F401
        return True
    except ImportError:
        return False


def offline_args() -> list[str]:
    """Use the bundled wheelhouse if one was shipped alongside the app."""
    if VENDOR_DIR.is_dir() and any(VENDOR_DIR.iterdir()):
        return ["--no-index", "--find-links", str(VENDOR_DIR)]
    return []


# ---------------------------------------------------------------------------
# Launching
# ---------------------------------------------------------------------------

def launch(python: Path | str | None = None) -> None:
    """Start the app, replacing this process where the OS allows it."""
    if python is None:
        sys.path.insert(0, str(APP_DIR))
        from alcmaeon.app import main
        main()
        return

    python = str(python)
    if WINDOWS:
        # pythonw keeps the console window from flashing up
        subprocess.Popen([python, str(ENTRY_POINT)], cwd=str(APP_DIR))
        sys.exit(0)
    try:
        os.execv(python, [python, str(ENTRY_POINT)])
    except OSError:
        # Replacing this process failed; run it as a child instead.
        process = subprocess.Popen([python, str(ENTRY_POINT)], cwd=str(APP_DIR))
        sys.exit(process.wait())


# ---------------------------------------------------------------------------
# Setup, with a progress window when tkinter is available
# ---------------------------------------------------------------------------

class SetupWindow:
    """Minimal dark progress window shown during first-run installation."""

    def __init__(self, title: str = "alcmaeon"):
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.root = tk.Tk()
        self.root.title(title)
        self.root.configure(bg=BG)
        self.root.geometry("520x300")
        self.root.resizable(False, False)

        tk.Label(self.root, text="alcmaeon", bg=BG, fg=TEXT,
                 font=("TkFixedFont", 16)).pack(anchor="w", padx=22, pady=(20, 0))
        self.status = tk.Label(self.root, text="preparing\u2026", bg=BG, fg=BLUE,
                               font=("TkFixedFont", 9), anchor="w")
        self.status.pack(fill="x", padx=22, pady=(6, 10))

        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("A.Horizontal.TProgressbar", background=BLUE,
                        troughcolor=SURFACE, bordercolor=SURFACE,
                        lightcolor=BLUE, darkcolor=BLUE)
        self.bar = ttk.Progressbar(self.root, mode="indeterminate",
                                   style="A.Horizontal.TProgressbar")
        self.bar.pack(fill="x", padx=22)
        self.bar.start(14)

        self.log = tk.Text(self.root, bg=SURFACE, fg=MUTED, bd=0,
                           font=("TkFixedFont", 8), height=9, wrap="none",
                           highlightthickness=0, padx=10, pady=8)
        self.log.pack(fill="both", expand=True, padx=22, pady=(14, 18))
        self.log.configure(state="disabled")

        self.root.protocol("WM_DELETE_WINDOW", lambda: None)
        self.failed = False

    def say(self, text: str) -> None:
        self.status.configure(text=text)

    def write(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def fail(self, message: str) -> None:
        self.failed = True
        self.bar.stop()
        self.bar.pack_forget()                  # a stalled bar reads as "still working"
        self.root.geometry("560x420")           # room for the log plus the button
        self.status.configure(text=message, fg=WARN)
        self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)
        button = self.tk.Button(self.root, text="close", command=self.root.destroy,
                                bg=SURFACE, fg=TEXT, bd=0, relief="flat",
                                activebackground=BG, activeforeground=BLUE,
                                highlightthickness=0, cursor="hand2",
                                font=("TkFixedFont", 9), padx=16, pady=5)
        button.pack(pady=(0, 16))
        self.log.see("end")

    def run(self, worker) -> None:
        """Run `worker(self)` on a thread, pumping the UI meanwhile."""
        def report(message: str, detail: str) -> None:
            self.write("")
            self.write(message)
            if detail:
                for row in detail.strip().splitlines()[-6:]:
                    self.write(row)
            self.fail("setup failed \u2014 see the log above")

        def target():
            try:
                worker(self)
            except Exception as exc:                     # noqa: BLE001
                # Bind the text now: `exc` is unbound once the except block
                # ends (Python 3.x deletes it), so a callback that reads it
                # later would raise NameError and hide the real problem.
                message = str(exc) or exc.__class__.__name__
                detail = "" if isinstance(exc, RuntimeError) else \
                    traceback.format_exc()
                self.root.after(0, report, message, detail)
            else:
                if not self.failed:
                    self.root.after(0, self.root.destroy)

        threading.Thread(target=target, daemon=True).start()
        self.root.mainloop()


class ConsoleWindow:
    """Fallback when tkinter is unavailable -- same interface, prints instead."""

    failed = False

    def say(self, text: str) -> None:
        print(f"[alcmaeon] {text}")

    def write(self, text: str) -> None:
        print("   " + text.rstrip())

    def fail(self, message: str) -> None:
        self.failed = True
        print(f"[alcmaeon] {message}")

    def run(self, worker) -> None:
        try:
            worker(self)
        except Exception as exc:                         # noqa: BLE001
            message = str(exc) or exc.__class__.__name__
            if not isinstance(exc, RuntimeError):
                traceback.print_exc()
            self.fail(message)


def stream(command: list[str], ui) -> int:
    """Run a subprocess, echoing its output into the setup window."""
    ui.write("$ " + " ".join(Path(c).name if os.sep in c else c for c in command))
    creationflags = 0x08000000 if WINDOWS else 0        # CREATE_NO_WINDOW
    process = subprocess.Popen(command, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True,
                               cwd=str(APP_DIR), creationflags=creationflags)
    for raw in process.stdout:                          # type: ignore[union-attr]
        line = raw.rstrip()
        if line:
            ui.write(line)
    return process.wait()


# Set by do_setup() so main() knows which interpreter to start afterwards.
SETUP_MODE: list[str] = []


def try_venv(ui) -> bool:
    """Build a private venv. Returns False if this Python cannot make one.

    Debian and Ubuntu remove `ensurepip` from the standard library and ship it
    as a separate python3-venv package, so venv creation fails there on a
    stock install. That is not an error worth stopping for -- we fall back.
    """
    import shutil

    try:
        if not VENV_DIR.exists():
            ui.say("creating a private python environment\u2026")
            ui.write(f"target: {VENV_DIR}")
            import venv
            venv.EnvBuilder(with_pip=True, clear=False).create(str(VENV_DIR))
    except Exception as exc:                                  # noqa: BLE001
        ui.write(f"virtual environment unavailable: {exc}")
        shutil.rmtree(VENV_DIR, ignore_errors=True)
        return False

    python = venv_python()
    if not python.exists() or not interpreter_works(python):
        ui.write(f"the virtual environment cannot be run: {describe_venv()}")
        shutil.rmtree(VENV_DIR, ignore_errors=True)
        return False
    if not pip_works(python):
        ui.write("the virtual environment came out without pip "
                 "(python3-venv is not installed)")
        shutil.rmtree(VENV_DIR, ignore_errors=True)
        return False

    ui.say("installing numpy, matplotlib and pyserial\u2026")
    command = [str(python), "-m", "pip", "install", "--disable-pip-version-check",
               "-r", str(REQUIREMENTS), *offline_args()]
    if stream(command, ui) != 0:
        return False

    gone = missing_packages(str(python))
    if gone:
        ui.write("still missing after install: " + ", ".join(gone))
        return False

    READY_MARKER.write_text("ok\n", encoding="utf-8")
    return True


def try_user_install(ui) -> bool:
    """Install into the user's own site-packages -- no venv, no sudo."""
    if not pip_works(sys.executable):
        ui.write("this python has no pip either")
        return False

    ui.say("installing into your user folder instead\u2026")
    command = [sys.executable, "-m", "pip", "install", "--user",
               "--disable-pip-version-check", "-r", str(REQUIREMENTS),
               *offline_args()]
    code = stream(command, ui)
    if code != 0:
        # Newer Debian/Ubuntu mark the system Python "externally managed"
        # (PEP 668) and refuse --user without this flag. It still only
        # touches the current user's home directory.
        ui.write("retrying for an externally managed python\u2026")
        code = stream(command + ["--break-system-packages"], ui)
    if code != 0:
        return False

    return not missing_packages(sys.executable)


def do_setup(ui) -> None:
    """Get the libraries in place, whichever way this machine allows."""
    if try_venv(ui):
        SETUP_MODE.append("venv")
        ui.say("done")
        ui.write("setup complete")
        return

    ui.write("")
    if try_user_install(ui):
        SETUP_MODE.append("user")
        ui.say("done")
        ui.write("setup complete (user install)")
        return

    ui.write("")
    ui.write("Could not install the libraries automatically.")
    if sys.platform.startswith("linux"):
        ui.write("")
        ui.write("Debian/Ubuntu split these out of Python. Run this once:")
        ui.write("    " + apt_hint())
        ui.write("then start Alcmaeon Lite again.")
    else:
        ui.write("")
        ui.write("If this machine has no internet access, place wheels for")
        ui.write("numpy, matplotlib and pyserial in a 'vendor' folder next to")
        ui.write("this app and run the launcher again.")
    raise RuntimeError("could not install the required libraries")


def do_build(ui) -> None:
    """Build a standalone executable with PyInstaller."""
    python = venv_python()
    ui.say("installing the build tool\u2026")
    if stream([str(python), "-m", "pip", "install", "--disable-pip-version-check",
               "pyinstaller", *offline_args()], ui) != 0:
        raise RuntimeError("could not install pyinstaller")

    ui.say("building the standalone app (this takes a few minutes)\u2026")
    spec = APP_DIR / "packaging" / "alcmaeon.spec"
    if stream([str(python), "-m", "PyInstaller", "--noconfirm",
               "--distpath", str(APP_DIR / "dist"),
               "--workpath", str(APP_DIR / "build"), str(spec)], ui) != 0:
        raise RuntimeError("the build failed")

    ui.say("built")
    ui.write(f"find it in: {APP_DIR / 'dist'}")


# ---------------------------------------------------------------------------

def main() -> None:
    args = set(sys.argv[1:])

    if "--repair" in args and VENV_DIR.exists():
        import shutil
        shutil.rmtree(VENV_DIR, ignore_errors=True)

    if "--build" in args:
        if not READY_MARKER.exists():
            run_setup()
        if not READY_MARKER.exists():
            return
        ui = SetupWindow("alcmaeon \u00b7 build") if has_tkinter() else ConsoleWindow()
        ui.run(do_build)
        return

    # Already runnable as-is? Then just go.
    if not missing_packages():
        launch()
        return

    # A venv only counts if its interpreter actually runs on this machine.
    python = usable_venv_python(windowed=WINDOWS)
    if python is not None:
        launch(python)
        return

    if VENV_DIR.exists():
        import shutil
        shutil.rmtree(VENV_DIR, ignore_errors=True)     # unusable -> rebuild

    mode = run_setup()
    if mode == "venv":
        launch(venv_python(windowed=WINDOWS))
    elif mode == "user":
        launch(sys.executable)      # re-exec so the new user packages import


def run_setup() -> str | None:
    """Run setup; returns "venv", "user", or None if it did not succeed."""
    ui = SetupWindow() if has_tkinter() else ConsoleWindow()
    if isinstance(ui, ConsoleWindow):
        print("[alcmaeon] tkinter is not available for this python install.")
        print("[alcmaeon] on Debian/Ubuntu: " + apt_hint())
    ui.run(do_setup)
    return SETUP_MODE[0] if SETUP_MODE else None


if __name__ == "__main__":
    main()
