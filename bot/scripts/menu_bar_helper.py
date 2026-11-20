"""Tiny menu-bar host outside Tk; NSStatusItem menus are unreliable in Tk."""
from __future__ import annotations
import json
import os
import socket
import sys

from AppKit import (NSApplication, NSImage, NSMenu, NSMenuItem, NSSquareStatusItemLength,
                    NSStatusBar)
from Foundation import NSObject, NSTimer

SOCKET = sys.argv[1] if len(sys.argv) > 1 else ''
ICON = sys.argv[2] if len(sys.argv) > 2 else ''
PARENT = os.getppid()


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


class Actions(NSObject):
    def show_(self, sender):
        call('show_window')

    def start_(self, sender):
        call('start_bot')

    def stop_(self, sender):
        call('stop_bot')

    def quit_(self, sender):
        call('quit_app')
        NSApplication.sharedApplication().terminate_(None)

    def tick_(self, timer):
        if os.getppid() != PARENT:
            NSApplication.sharedApplication().terminate_(None)


def main():
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
    menu = NSMenu.alloc().initWithTitle_('什亭之匣')
    label = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_('什亭之匣', '', '')
    label.setEnabled_(False)
    menu.addItem_(label)
    menu.addItem_(NSMenuItem.separatorItem())
    for title, action in (('显示窗口', 'show_'), ('启动机器人', 'start_'),
                          ('停止机器人', 'stop_')):
        row = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, '')
        row.setTarget_(actions)
        menu.addItem_(row)
    menu.addItem_(NSMenuItem.separatorItem())
    quit_row = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_('退出软件', 'quit_', '')
    quit_row.setTarget_(actions)
    menu.addItem_(quit_row)
    item.setMenu_(menu)
    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        2.0, actions, 'tick:', None, True)
    print('READY', flush=True)
    app.run()


if __name__ == '__main__':
    main()
