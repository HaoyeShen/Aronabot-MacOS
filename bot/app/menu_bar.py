"""Native macOS status item; closing the Tk window keeps the bot running."""
from __future__ import annotations
import logging
from AppKit import (NSApplication, NSImage, NSMenu, NSMenuItem, NSScreen,
                    NSSquareStatusItemLength, NSStatusBar)
from Foundation import NSObject
from .paths import ASSETS
log = logging.getLogger(__name__)


class _MenuActions(NSObject):
    def showWindow_(self, sender): self.controller.show()
    def startBot_(self, sender): self.controller.start()
    def stopBot_(self, sender): self.controller.stop()
    def quitApp_(self, sender): self.controller.quit()


class MenuBar:
    def __init__(self, root, window):
        self.root = root
        self.window = window
        self.service = window.service
        self.closed = False
        self._checks = 0
        self.delegate = _MenuActions.alloc().init()
        self.delegate.controller = self
        self._build_item()
        window.menu_bar = self
        root.createcommand('tk::mac::ReopenApplication', self.show)
        root.createcommand('tk::mac::Quit', self.quit)
        self._refresh()
        # macOS occasionally places a newly created status item off-screen
        # (x = -1) after a restart, especially when the bar is crowded.
        for delay in (800, 2500, 6000):
            self.root.after(delay, self._ensure_visible)

    def _build_item(self):
        self.item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSSquareStatusItemLength)
        self.item.setVisible_(True)
        image = NSImage.alloc().initWithContentsOfFile_(str(ASSETS / 'app_icon.png'))
        if image is not None:
            image.setSize_((18, 18))
            image.setTemplate_(False)
            self.item.button().setImage_(image)
            self.image = image
        else:
            self.item.button().setTitle_('A')
        self.menu = NSMenu.alloc().initWithTitle_('什亭之匣')
        self.label = self._add('什亭之匣 · 已停止', None)
        self.label.setEnabled_(False)
        self.menu.addItem_(NSMenuItem.separatorItem())
        self._add('显示窗口', 'showWindow:')
        self.start_item = self._add('启动机器人', 'startBot:')
        self.stop_item = self._add('停止机器人', 'stopBot:')
        self.menu.addItem_(NSMenuItem.separatorItem())
        self._add('退出软件', 'quitApp:')
        self.item.setMenu_(self.menu)
        self.menu.setAutoenablesItems_(False)

    def _add(self, title, action):
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, '')
        if action:
            item.setTarget_(self.delegate)
        self.menu.addItem_(item)
        return item

    def _placement(self):
        try:
            button = self.item.button()
            window = button.window() if button is not None else None
            frame = window.frame() if window is not None else None
            screen = NSScreen.mainScreen().frame()
            visible = bool(self.item.isVisible())
            ok = (visible and frame is not None and frame.origin.x >= 0
                  and frame.origin.y >= 0 and frame.origin.x < screen.size.width)
            return ok, frame, screen
        except Exception:
            log.exception('读取菜单栏图标位置失败')
            return False, None, None

    def _ensure_visible(self):
        if self.closed:
            return
        ok, frame, screen = self._placement()
        if ok:
            log.info('菜单栏图标已显示 · frame=%s', frame)
            return
        log.warning('菜单栏图标未显示 · frame=%s screen=%s attempt=%d', frame, screen, self._checks)
        if self._checks >= 2:
            log.warning('菜单栏空间可能不足：可关闭其他状态栏图标，或在菜单栏空白处按住 Command 拖动图标')
            return
        self._checks += 1
        NSStatusBar.systemStatusBar().removeStatusItem_(self.item)
        self._build_item()
        self.root.after(1200, self._ensure_visible)

    def _refresh(self):
        if self.closed:
            return
        running = self.service.running
        starting = bool(self.service.state().get('starting'))
        busy = bool(self.window._bot_action_busy)
        status = '连接中' if starting else '运行中' if running else '已停止'
        self.label.setTitle_('什亭之匣 · ' + status)
        self.item.button().setToolTip_('什亭之匣 · ' + status)
        self.start_item.setEnabled_(not running and not busy and not starting)
        self.stop_item.setEnabled_(running and not busy)
        self.root.after(500, self._refresh)

    def show(self):
        if self.closed:
            return
        self.root.deiconify()
        self.root.lift()
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

    def hide(self):
        if not self.closed:
            self.root.withdraw()

    def start(self):
        if not self.service.running and not self.window._bot_action_busy:
            self.window.toggle_bot()

    def stop(self):
        if self.service.running and not self.window._bot_action_busy:
            self.window.toggle_bot()

    def quit(self):
        if self.closed:
            return
        if self.window.quit_app() is False:
            return
        self.closed = True
        NSStatusBar.systemStatusBar().removeStatusItem_(self.item)
