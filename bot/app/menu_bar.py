"""Native macOS status item; closing the Tk window keeps the bot running."""
from __future__ import annotations
import logging
from pathlib import Path
from AppKit import NSApplication,NSImage,NSMenu,NSMenuItem,NSStatusBar,NSVariableStatusItemLength
from Foundation import NSObject
import objc
from .paths import ASSETS
log=logging.getLogger(__name__)

class _MenuActions(NSObject):
    def showWindow_(self,sender):self.controller.show()
    def startBot_(self,sender):self.controller.start()
    def stopBot_(self,sender):self.controller.stop()
    def quitApp_(self,sender):self.controller.quit()

class MenuBar:
    def __init__(self,root,window):
        self.root=root;self.window=window;self.service=window.service;self.closed=False
        self.delegate=_MenuActions.alloc().init();self.delegate.controller=self
        self.item=NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        self.image=NSImage.alloc().initWithContentsOfFile_(str(ASSETS/'app_icon.png'))
        self.image.setSize_((22,22));self.image.setTemplate_(False)
        self.item.button().setImage_(self.image)
        self.menu=NSMenu.alloc().initWithTitle_('什亭之匣')
        self.label=self._add('什亭之匣 · 已停止',None);self.label.setEnabled_(False)
        self.menu.addItem_(NSMenuItem.separatorItem())
        self._add('显示窗口','showWindow:')
        self.start_item=self._add('启动机器人','startBot:')
        self.stop_item=self._add('停止机器人','stopBot:')
        self.menu.addItem_(NSMenuItem.separatorItem())
        self._add('退出软件','quitApp:')
        self.item.setMenu_(self.menu)
        self.menu.setAutoenablesItems_(False)
        window.menu_bar=self
        root.createcommand('tk::mac::ReopenApplication',self.show)
        root.createcommand('tk::mac::Quit',self.quit)
        self._refresh()
    def _add(self,title,action):
        item=NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title,action,'')
        if action:item.setTarget_(self.delegate)
        self.menu.addItem_(item);return item
    def _refresh(self):
        if self.closed:return
        running=self.service.running;starting=bool(self.service.state().get('starting'))
        busy=bool(self.window._bot_action_busy)
        status='连接中' if starting else '运行中' if running else '已停止'
        self.label.setTitle_('什亭之匣 · '+status)
        self.item.button().setToolTip_('什亭之匣 · '+status)
        self.start_item.setEnabled_(not running and not busy and not starting)
        self.stop_item.setEnabled_(running and not busy)
        self.root.after(500,self._refresh)
    def show(self):
        if self.closed:return
        self.root.deiconify();self.root.lift()
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    def hide(self):
        if not self.closed:self.root.withdraw()
    def start(self):
        if not self.service.running and not self.window._bot_action_busy:self.window.toggle_bot()
    def stop(self):
        if self.service.running and not self.window._bot_action_busy:self.window.toggle_bot()
    def quit(self):
        if self.closed:return
        if self.window.quit_app() is False:return
        self.closed=True
        NSStatusBar.systemStatusBar().removeStatusItem_(self.item)
