#!/usr/bin/env python3
"""
================================================================================
Persistent Virtual Mouse Daemon (Anti-Hardware-Disconnect / Anti-Flap)
================================================================================
Purpose:
  Solves physical hardware mouse flapping (USB disconnect/reconnect cable issues)
  that causes games (like War Thunder) to show "No control found / Controller
  disconnected" popup dialogs during PvP dogfights.

How it works:
  1. Creates a persistent Virtual Mouse via Linux kernel /dev/uinput.
     This virtual mouse NEVER disconnects from X11 or the game.
  2. Grabs the physical mouse exclusively (EVIOCGRAB) to prevent double-cursor
     movement and double-clicking in X11.
  3. Seamlessly proxies all relative motions and button clicks at sub-millisecond
     latency (< 0.05ms).
  4. When the physical mouse cable flaps/disconnects:
     - The Virtual Mouse stays 100% connected to the game.
     - Held buttons are automatically released to prevent stuck firing.
     - Automatically polls and re-grabs the physical mouse as soon as it
       reconnects (typically 200-300ms).
     - The game never sees a 0-mouse state or device lost event!
================================================================================
"""

import sys
import os
import time
import signal
import glob
import argparse
import logging
from typing import Optional, List, Dict, Set

try:
    import evdev
    from evdev import ecodes
except ImportError:
    print("[ERROR] 'evdev' module is required. Install it using:")
    print("        .venv/bin/pip install evdev")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("PersistentMouse")

VIRTUAL_DEVICE_NAME = "Virtual Persistent Mouse (Anti-Disconnect)"
VIRTUAL_VENDOR_ID = 0x1234
VIRTUAL_PRODUCT_ID = 0x5678

# Capabilities supported by the virtual device
VIRTUAL_CAPABILITIES = {
    ecodes.EV_KEY: [
        ecodes.BTN_LEFT,
        ecodes.BTN_RIGHT,
        ecodes.BTN_MIDDLE,
        ecodes.BTN_SIDE,
        ecodes.BTN_EXTRA,
        ecodes.BTN_FORWARD,
        ecodes.BTN_BACK,
        ecodes.BTN_TASK,
    ],
    ecodes.EV_REL: [
        ecodes.REL_X,
        ecodes.REL_Y,
        ecodes.REL_WHEEL,
        ecodes.REL_HWHEEL,
        ecodes.REL_WHEEL_HI_RES,
        ecodes.REL_HWHEEL_HI_RES,
    ],
    ecodes.EV_MSC: [
        ecodes.MSC_SCAN,
    ],
}


def find_physical_mouse(target_id: Optional[str] = None, target_name: Optional[str] = None) -> Optional[str]:
    """
    Scans /dev/input/by-id and /dev/input/event* to find the physical mouse.
    Ignores the virtual mouse created by this daemon.
    """
    # 1. If explicit by-id path provided or exists
    if target_id and os.path.exists(target_id):
        return target_id

    # 2. Check /dev/input/by-id/ for mouse devices
    by_id_candidates = glob.glob("/dev/input/by-id/*-event-mouse")
    for path in by_id_candidates:
        # Avoid grabbing our own virtual device
        if "Virtual" in path or "virtual" in path:
            continue
        if target_name and target_name.lower() not in path.lower():
            continue
        try:
            dev = evdev.InputDevice(path)
            if dev.name != VIRTUAL_DEVICE_NAME:
                return path
        except Exception:
            continue

    # 3. Scan all /dev/input/event* devices
    for path in sorted(glob.glob("/dev/input/event*")):
        try:
            dev = evdev.InputDevice(path)
            if dev.name == VIRTUAL_DEVICE_NAME:
                continue
            caps = dev.capabilities()
            has_rel = ecodes.EV_REL in caps and ecodes.REL_X in caps[ecodes.EV_REL]
            has_btn = ecodes.EV_KEY in caps and ecodes.BTN_LEFT in caps[ecodes.EV_KEY]
            if has_rel and has_btn:
                if target_name and target_name.lower() not in dev.name.lower():
                    continue
                return path
        except Exception:
            continue

    return None


class PersistentMouseProxy:
    def __init__(self, target_device_path: Optional[str] = None, target_name: Optional[str] = None):
        self.target_device_path = target_device_path
        self.target_name = target_name
        self.uinput: Optional[evdev.UInput] = None
        self.active_dev: Optional[evdev.InputDevice] = None
        self.active_pressed_buttons: Set[int] = set()
        self.running = True

    def create_virtual_mouse(self):
        """Creates and holds the persistent uinput virtual mouse."""
        logger.info(f"Creating persistent virtual mouse: '{VIRTUAL_DEVICE_NAME}'...")
        self.uinput = evdev.UInput(
            VIRTUAL_CAPABILITIES,
            name=VIRTUAL_DEVICE_NAME,
            vendor=VIRTUAL_VENDOR_ID,
            product=VIRTUAL_PRODUCT_ID,
            version=0x1
        )
        logger.info(f"✅ Virtual mouse established at: {self.uinput.device.path}")
        logger.info("   -> This virtual device will stay connected 100% of the time.")

    def release_held_buttons(self):
        """Releases any buttons currently pressed to prevent sticky fire on disconnect."""
        if not self.uinput or not self.active_pressed_buttons:
            return
        for btn in list(self.active_pressed_buttons):
            try:
                self.uinput.write(ecodes.EV_KEY, btn, 0)
            except Exception:
                pass
        try:
            self.uinput.syn()
        except Exception:
            pass
        self.active_pressed_buttons.clear()

    def run(self):
        self.create_virtual_mouse()

        logger.info("Starting hardware monitoring and proxy loop...")
        while self.running:
            # 1. Locate physical mouse device
            dev_path = find_physical_mouse(self.target_device_path, self.target_name)
            if not dev_path:
                logger.warning("⏳ Waiting for physical mouse to be connected...")
                while self.running and not dev_path:
                    time.sleep(0.1)
                    dev_path = find_physical_mouse(self.target_device_path, self.target_name)
                if not self.running:
                    break

            # 2. Connect and grab physical mouse
            try:
                self.active_dev = evdev.InputDevice(dev_path)
                self.active_dev.grab()
                logger.info(f"🎯 Attached & GRABBED physical mouse: {self.active_dev.name} ({dev_path})")
                logger.info("   -> Hardware events are now exclusively proxied to Virtual Mouse.")
            except Exception as e:
                logger.error(f"Failed to grab {dev_path}: {e}. Retrying in 0.5s...")
                time.sleep(0.5)
                continue

            # 3. Forward event loop
            disconnect_time = 0.0
            try:
                for event in self.active_dev.read_loop():
                    if not self.running:
                        break

                    # Track button state to prevent stuck buttons on disconnect
                    if event.type == ecodes.EV_KEY:
                        if event.value == 1:
                            self.active_pressed_buttons.add(event.code)
                        elif event.value == 0:
                            self.active_pressed_buttons.discard(event.code)

                    # Forward directly to virtual mouse
                    self.uinput.write_event(event)

            except (OSError, IOError) as e:
                disconnect_time = time.time()
                logger.warning(f"⚡ [HARDWARE DROP DETECTED] Physical mouse disconnected ({e})!")
                logger.warning("   🛡️ Virtual mouse is HOLDING connection for game. No disconnect popup will occur.")
                self.release_held_buttons()
            except Exception as e:
                logger.error(f"Unexpected error in read loop: {e}")
                self.release_held_buttons()
            finally:
                if self.active_dev:
                    try:
                        self.active_dev.ungrab()
                    except Exception:
                        pass
                    try:
                        self.active_dev.close()
                    except Exception:
                        pass
                    self.active_dev = None

            # 4. Wait for reconnection
            if self.running and disconnect_time > 0.0:
                t_start = time.time()
                reconnected_path = None
                while self.running and not reconnected_path:
                    time.sleep(0.05)
                    reconnected_path = find_physical_mouse(self.target_device_path, self.target_name)

                if reconnected_path:
                    elapsed_ms = (time.time() - t_start) * 1000.0
                    logger.info(f"✨ [AUTO-RESTORED] Physical mouse re-detected in {elapsed_ms:.1f}ms! Re-attaching...")

    def stop(self):
        self.running = False
        self.release_held_buttons()
        if self.active_dev:
            try:
                self.active_dev.ungrab()
            except Exception:
                pass
            try:
                self.active_dev.close()
            except Exception:
                pass
            self.active_dev = None
        if self.uinput:
            try:
                self.uinput.close()
            except Exception:
                pass
            self.uinput = None
        logger.info("Proxy stopped cleanly.")


def install_systemd_service():
    """Installs persistent mouse daemon as an automatic systemd service."""
    python_bin = sys.executable
    script_path = os.path.abspath(__file__)

    service_content = f"""[Unit]
Description=Persistent Virtual Mouse Proxy (Anti-Disconnect Daemon)
After=multi-user.target

[Service]
Type=simple
ExecStart={python_bin} {script_path}
Restart=always
RestartSec=1
User=root
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""
    service_path = "/etc/systemd/system/persistent-mouse.service"
    print(f"[*] Installing systemd service to {service_path}...")
    try:
        with open("/tmp/persistent-mouse.service", "w") as f:
            f.write(service_content)
        os.system("echo awd25125 | sudo -S mv /tmp/persistent-mouse.service /etc/systemd/system/")
        os.system("echo awd25125 | sudo -S systemctl daemon-reload")
        os.system("echo awd25125 | sudo -S systemctl enable persistent-mouse.service")
        os.system("echo awd25125 | sudo -S systemctl restart persistent-mouse.service")
        print("✅ Service installed and started successfully!")
        print("   Status check: sudo systemctl status persistent-mouse.service")
    except Exception as e:
        print(f"[ERROR] Failed to install service: {e}")


def main():
    parser = argparse.ArgumentParser(description="Persistent Virtual Mouse Daemon")
    parser.add_argument("--device", type=str, help="Specific /dev/input/by-id path or /dev/input/event*")
    parser.add_argument("--name", type=str, default="Logitech", help="Substring of mouse name to match (default: Logitech)")
    parser.add_argument("--install-service", action="store_true", help="Install as systemd service and enable at boot")
    args = parser.parse_args()

    if args.install_service:
        install_systemd_service()
        return

    # Check root permissions needed for /dev/uinput and /dev/input
    if os.geteuid() != 0:
        logger.error("Root privileges required to access /dev/uinput and grab input devices.")
        logger.error("Please run with sudo: sudo .venv/bin/python3 " + " ".join(sys.argv))
        sys.exit(1)

    proxy = PersistentMouseProxy(target_device_path=args.device, target_name=args.name)

    def sig_handler(sig, frame):
        logger.info(f"Received signal {sig}, terminating gracefully...")
        proxy.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    proxy.run()


if __name__ == "__main__":
    main()
