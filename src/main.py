import threading
import time
from queue import Queue

import keyboard

from src.config.config import Config
from src.keyboard_controller.hotkey_listener import HotkeyListener
from src.keyboard_controller.pressed_events_handler import clear_pressed_events
from src.os_controller.notifications import send_notification_in_thread
from src.os_controller.tray_icon import TrayIcon
from src.ui.overlay_window import OverlayWindow
from src.ui.update_window import UpdateWindow
from src.util.lockfile_handler import check_lockfile, remove_lockfile


class CatLockCore:
    def __init__(self) -> None:
        self.hotkey_thread = None
        self.show_overlay_queue = Queue()
        self.config = Config()
        self.root = None
        self.hotkey_lock = threading.Lock()
        self.listen_for_hotkey = True
        self.program_running = True
        self.blocked_keys = set()
        self.changing_hotkey_queue = Queue()
        self.last_activity_time = time.monotonic()
        self.activity_hook = keyboard.hook(self._record_activity, suppress=False)
        self.start_hotkey_listener()
        self.clear_pressed_events_thread = threading.Thread(target=clear_pressed_events, daemon=True)
        self.clear_pressed_events_thread.start()
        self.tray_icon_thread = threading.Thread(target=self.create_tray_icon, daemon=True)
        self.tray_icon_thread.start()

    def create_tray_icon(self) -> None:
        TrayIcon(main=self).open()

    def start_hotkey_listener(self) -> None:
        HotkeyListener(self).start_hotkey_listener_thread()

    def lock_keyboard(self) -> None:
        self.blocked_keys.clear()
        for i in range(150):
            keyboard.block_key(i)
            self.blocked_keys.add(i)
        send_notification_in_thread(self.config.notifications_enabled)

    def unlock_keyboard(self, event=None) -> None:
        for key in self.blocked_keys:
            keyboard.unblock_key(key)
        self.blocked_keys.clear()
        if self.root:
            self.root.destroy()
        keyboard.stash_state()
        self.last_activity_time = time.monotonic()

    def send_hotkey_signal(self) -> None:
        self.show_overlay_queue.put(True)

    def quit_program(self, icon, item) -> None:
        remove_lockfile()
        self.program_running = False
        self.unlock_keyboard()
        icon.stop()

    def _record_activity(self, event) -> None:
        self.last_activity_time = time.monotonic()

    def _auto_lock_due(self) -> bool:
        if not getattr(self.config, "auto_lock_enabled", False):
            return False
        idle_minutes = getattr(self.config, "auto_lock_idle_minutes", 5)
        if idle_minutes < 1:
            idle_minutes = 1
        idle_seconds = idle_minutes * 60
        return time.monotonic() - self.last_activity_time >= idle_seconds

    def _is_locked(self) -> bool:
        return self.root is not None and self.root.winfo_exists()

    def start(self) -> None:
        check_lockfile()
        UpdateWindow(self).prompt_update()
        # hack to prevent right ctrl sticking
        keyboard.remap_key('right ctrl', 'left ctrl')

        if not self.config.user_guide_shown:
            from src.ui.user_guide_window import UserGuideWindow
            UserGuideWindow(self).open()

        while self.program_running:
            if self._auto_lock_due() and not self._is_locked():
                self.send_hotkey_signal()
            if not self.show_overlay_queue.empty():
                self.show_overlay_queue.get(block=False)
                overlay = OverlayWindow(main=self)
                keyboard.stash_state()
                overlay.open()
            time.sleep(.1)


if __name__ == "__main__":
    core = CatLockCore()
    core.start()
