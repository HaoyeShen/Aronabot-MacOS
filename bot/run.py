"""macOS launcher for the ARONA desktop app and background native bot."""
from __future__ import annotations
import argparse,logging,os,sys,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT.parent/'src'))

def show_fatal(message):
    print(message,file=sys.stderr)

def build_services():
    from app.config_store import ConfigStore, PersonaStore, StickerStore
    from app.memory import MemoryStore
    from app.paths import ensure_dirs
    from app.service import BotService
    from app.training import TrainingStore

    ensure_dirs()
    config = ConfigStore()
    personas = PersonaStore()
    stickers = StickerStore()
    memory = MemoryStore()
    training = TrainingStore()
    return BotService(config, personas, stickers, memory, training)

def run_check() -> int:
    from app.logging_setup import setup_logging

    setup_logging()
    service = build_services()
    try:
        state = service.state()
        print("什亭之匣自动诊断")
        print("=" * 64)
        print(f"模型：{state.get('model')} · 人格：{state.get('persona')}")
        print(f"监听对象：{state.get('target_count')} · 表情包：{state.get('sticker_count')}")
        print("-" * 64)
        result = service.diagnostics(run_model=True, run_chat_test=False)
        for check in result["checks"]:
            mark = {"ok": "[ OK ]", "warn": "[WARN]", "fail": "[FAIL]"}.get(
                check["status"], "[INFO]")
            print(f"{mark} {check['title']}: {check['detail']}")
            if check.get("hint"):
                print(f"       → {check['hint']}")
        print("-" * 64)
        print(f"{result['passed']} 通过 / {result['warnings']} 提示 / {result['failed']} 失败")
        return 0
    finally:
        service.shutdown()

def run_ui_smoke(timeout_ms: int = 1800) -> int:
    from app.config_store import ConfigStore, PersonaStore, StickerStore
    from app.logging_setup import setup_logging
    from app.memory import MemoryStore
    from app.paths import ASSETS
    from app.service import BotService

    setup_logging()
    config = ConfigStore()
    personas = PersonaStore()
    stickers = StickerStore()
    memory = MemoryStore()
    service = BotService(config, personas, stickers, memory)
    import tkinter as tk
    from app.ui.main_window import MainWindow, PAGE_CLASSES

    root = tk.Tk()
    root._arona_no_autostart = True
    icon = tk.PhotoImage(file=str(ASSETS / "app_icon.png"))
    root._arona_icon = icon
    app = MainWindow(root, service, icon)
    pages = list(app.pages.keys())

    def inspect():
        try:
            pages_now = list(app.pages.keys())
            state = service.state()
            if not app.bank.photo('assets/avatar_96.png', (32, 32)):
                raise RuntimeError('Bundled avatar resource is missing')
            if len(service.stickers.enabled()) < 8:
                raise RuntimeError('Bundled default stickers are missing')
            print(f"UI smoke: window={root.winfo_width()}x{root.winfo_height()} "
                  f"page={app._current_page} pages={pages_now} targets={state['target_count']}")
            for key in PAGE_CLASSES:
                app.show_page(key)
                root.update_idletasks()
            print("UI smoke: all pages rendered")
        except Exception:
            traceback.print_exc()
            service.shutdown()
            root.destroy()
            raise SystemExit(1)
        finally:
            try:
                service.shutdown()
                root.destroy()
            except Exception:
                pass

    root.after(timeout_ms, inspect)
    root.mainloop()
    print("UI smoke: done")
    return 0

def run_headless(seconds=0):
    import signal,threading,time,json
    from app.logging_setup import setup_logging
    setup_logging()
    service=build_services();stop=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):
        signal.signal(sig,lambda *_:stop.set())
    try:
        if not service.start():return 1
        print(json.dumps({'running':True,'backend':service.state().get('backend'),
                          'targets':service.state().get('target_count')},ensure_ascii=False),flush=True)
        deadline=time.monotonic()+seconds if seconds>0 else None
        while not stop.wait(.5):
            if deadline is not None and time.monotonic()>=deadline:break
        return 0
    finally:service.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser(description="什亭之匣微信助手")
    parser.add_argument("--check", action="store_true", help="run diagnostics and exit")
    parser.add_argument("--ui-smoke", action="store_true", help="build UI and close")
    parser.add_argument("--headless", action="store_true", help="run the native bot without a window")
    parser.add_argument("--seconds", type=float, default=0, help="optional duration for headless verification")
    args = parser.parse_args()
    if args.headless:
        return run_headless(args.seconds)
    if args.check:
        return run_check()
    if args.ui_smoke:
        return run_ui_smoke()

    from app.desktop_instance import DesktopInstance
    instance=DesktopInstance()
    if not instance.acquire():return 0
    from app.logging_setup import setup_logging

    setup_logging()
    logging.getLogger("arona").info("什亭之匣启动 · macOS · 内部函数 · 后台监听和发送")
    try:
        service = build_services()
    except Exception:
        detail = traceback.format_exc()
        logging.getLogger("arona").critical("初始化失败：%s", detail)
        show_fatal("初始化失败，请查看 logs/arona.log。\n\n" + detail[-1500:])
        return 1

    try:
        import tkinter as tk
        from app.paths import ASSETS
        from app.ui.main_window import MainWindow

        root = tk.Tk()
        icon = tk.PhotoImage(file=str(ASSETS / "app_icon.png"))
        root._arona_icon = icon
        window = MainWindow(root, service, icon)
        from app.menu_bar import MenuBar
        menu_bar=MenuBar(root,window)
        instance.start(root,menu_bar.show)

        def report_callback_exception(exc_type, exc_value, exc_tb):
            detail = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
            logging.getLogger("arona.ui").error("界面异常：%s", detail)
            try:
                from tkinter import messagebox
                messagebox.showerror("什亭之匣界面异常",
                                     "界面发生异常，详细信息已写入 logs/arona.log。\n\n"
                                     + str(exc_value)[:500])
            except Exception:
                pass

        root.report_callback_exception = report_callback_exception
        root.mainloop()
        instance.close()
        return 0
    except Exception:
        detail = traceback.format_exc()
        logging.getLogger("arona").critical("启动 GUI 失败：%s", detail)
        show_fatal("启动界面失败，请查看 logs/arona.log。\n\n" + detail[-1500:])
        try:
            service.shutdown()
        except Exception:
            pass
        return 1

if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--web-render-worker':
        from app.web_media import render_worker
        render_worker(sys.argv[2])
    else:raise SystemExit(main())
