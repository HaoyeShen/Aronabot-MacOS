"""Menu-bar host outside Tk.

Tk-hosted NSStatusItems are unreliable on recent macOS builds, and a Tk
process cannot safely own an NSMenu for the status item.  This module runs
in its own NSApplication, sends only small commands to the bot's Unix
socket, and never blocks the AppKit main thread on a slow bot request.
"""
from __future__ import annotations

import json
import os
import socket
import threading

from AppKit import (NSApplication, NSImage, NSMenu, NSMenuItem,
                    NSSquareStatusItemLength, NSStatusBar)
from Foundation import NSObject, NSTimer

SOCKET = ''
ICON = ''
PARENT = os.getppid()
MENU_ACTIONS = (('显示窗口', 'show:'), ('启动机器人', 'start:'),
                ('停止机器人', 'stop:'))


def call(command):
    if not SOCKET:
        return {}
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(2)
            client.connect(SOCKET)
            client.sendall((json.dumps({'command': command}) + '\n').encode())
            data = b''
            while b'\n' not in data:
                chunk = client.recv(4096)
                if not chunk:
                    break
                data += chunk
            return json.loads(data.decode('utf-8', 'replace') or '{}')
    except (OSError, ValueError):
        return {}


def dispatch(command):
    """Send a menu command without blocking the AppKit event loop."""
    threading.Thread(target=call, args=(command,), daemon=True).start()


class Actions(NSObject):
    def show_(self, sender):
        dispatch('show_window')

    def start_(self, sender):
        dispatch('start_bot')

    def stop_(self, sender):
        dispatch('stop_bot')

    def quit_(self, sender):
        # Do not terminate here: the main process may veto the exit while a
        # native call is still draining.  The parent watch exits us instead.
        dispatch('quit_app')

    def tick_(self, timer):
        if os.getppid() != PARENT:
            NSApplication.sharedApplication().terminate_(None)


def build_menu(actions):
    menu = NSMenu.alloc().initWithTitle_('什亭之匣')
    label = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_('什亭之匣', '', '')
    label.setEnabled_(False)
    menu.addItem_(label)
    menu.addItem_(NSMenuItem.separatorItem())
    for title, selector in MENU_ACTIONS:
        row = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, selector, '')
        row.setTarget_(actions)
        menu.addItem_(row)
    menu.addItem_(NSMenuItem.separatorItem())
    quit_row = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_('退出软件', 'quit:', '')
    quit_row.setTarget_(actions)
    menu.addItem_(quit_row)
    return menu


def main(socket_path='', icon_path=''):
    global SOCKET, ICON
    SOCKET, ICON = socket_path, icon_path
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(1)
    item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSSquareStatusItemLength)
    image = NSImage.alloc().initWithContentsOfFile_(ICON) if ICON else None
    if image is not None:
        image.setSize_((18, 18))
        image.setTemplate_(False)
        item.button().setImage_(image)
    else:
        item.button().setTitle_('A')
    item.setVisible_(True)
    actions = Actions.alloc().init()
    item.setMenu_(build_menu(actions))
    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        2.0, actions, 'tick:', None, True)
    print('READY', flush=True)
    app.run()
