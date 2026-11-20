"""Single frozen executable: installer assistant, bot, and isolated codecs."""
from pathlib import Path
import json,os,sys
APP=Path(sys.executable).resolve().parents[2] if getattr(sys,'frozen',False) else None
BUNDLE=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
PRODUCT_FILE=BUNDLE/'installer_payload/product.json'
SDK_ONLY=PRODUCT_FILE.is_file() and json.loads(PRODUCT_FILE.read_text()).get('product')=='sdk'
if APP:os.environ.setdefault('WEMAC_SDK_ROOT',str(APP.parent/'sdk'))

def setup():
    import queue,threading,tkinter as tk
    from tkinter import ttk,filedialog,messagebox
    from installer_core import install
    root=tk.Tk();root.title('Wemac-auto SDK 安装与配置' if SDK_ONLY else 'Aronabot-MacOS 安装与配置');root.geometry('740x440')
    root.minsize(700,410)
    box=ttk.Frame(root,padding=24);box.pack(fill='both',expand=True)
    ttk.Label(box,text='Wemac-auto SDK · 一键安装' if SDK_ONLY else 'Aronabot-MacOS · 一键安装',font=('',22,'bold')).pack(anchor='w')
    ttk.Label(box,text='Apple Silicon · 微信 4.2.0（270348）\n复制为独立微信并重签名，保留原版和现有账号。',wraplength=660).pack(anchor='w',pady=12)
    src=tk.StringVar(value='/Applications/WeChat.app');dest=tk.StringVar(value=str(Path.home()/'Applications/Wemac-auto'))
    def field(label,var,browse):
        row=ttk.Frame(box);row.pack(fill='x',pady=6)
        ttk.Label(row,text=label,width=12).pack(side='left');ttk.Entry(row,textvariable=var).pack(side='left',fill='x',expand=True)
        ttk.Button(row,text='选择…',command=browse).pack(side='left',padx=8)
    def choose_source():
        value=filedialog.askopenfilename(title='选择原版 WeChat.app',initialdir='/Applications',filetypes=[('macOS 应用','*.app')])
        if value:src.set(value)
    def choose_dest():
        value=filedialog.askdirectory(title='选择安装目录的上级文件夹（会新建 Wemac-auto）')
        if value:dest.set(str(Path(value)/'Wemac-auto'))
    field('原版微信',src,choose_source);field('安装目录',dest,choose_dest)
    online=(BUNDLE/'installer_payload/online-models.json').is_file()
    note=('安装 SDK、独立命令行环境和原生组件，不下载机器人语音模型。' if SDK_ONLY else ('需联网自动下载语音模型，显示下载进度并校验文件。' if online else '角色公开模型与离线环境会自动安装。'))
    ttk.Label(box,text='不含账号、聊天记录、API Key 或私人录音。\n'+note+('' if SDK_ONLY else '参考录音需自行配置。'),wraplength=660).pack(anchor='w',pady=12)
    progress=ttk.Progressbar(box,maximum=100);progress.pack(fill='x',pady=8)
    status=tk.StringVar(value='准备就绪。请确保目标目录可写，独立微信尚未安装。');ttk.Label(box,textvariable=status,wraplength=660).pack(anchor='w')
    messages=queue.Queue();busy=False
    def start():
        nonlocal busy
        if busy:return
        busy=True;button.configure(state='disabled');source=src.get();destination=dest.get()
        def worker():
            try:
                path=install(source,destination,APP,BUNDLE/'installer_payload',Path.home()/'Library/Application Support/WemacAuto/Arona',lambda n,s:messages.put(('progress',n,s)))
                messages.put(('done',str(path)))
            except Exception as e:messages.put(('error',str(e)))
        threading.Thread(target=worker,daemon=True).start()
    button=ttk.Button(box,text='开始安装：复制、重签名并配置',command=start);button.pack(anchor='e',pady=14)
    def poll():
        nonlocal busy
        try:
            while True:
                msg=messages.get_nowait()
                if msg[0]=='progress':progress['value']=msg[1];status.set(msg[2])
                elif msg[0]=='done':
                    busy=False;status.set('安装完成：'+msg[1]);messagebox.showinfo('安装完成',
                        'SDK 与独立微信已安装。\n请登录 WeChat-Wemac，使用安装目录内的 bin/wechat-aumac 调用接口。' if SDK_ONLY else
                        '机器人和独立微信已安装。\n请从安装目录打开 WeChat-Wemac 登录，再打开 Wemac-auto 配置模型。')
                else:
                    busy=False;button.configure(state='normal');status.set('安装未完成，已有账号和原版保持不变。');messagebox.showerror('安装未完成',msg[1])
        except queue.Empty:pass
        root.after(100,poll)
    def close():
        if busy:messagebox.showinfo('正在安装','请等待当前复制或签名结束，以免留下不完整安装。')
        else:root.destroy()
    root.protocol('WM_DELETE_WINDOW',close);poll();root.mainloop()

if __name__=='__main__':
    if '--sdk-cli' in sys.argv:
        from wechat_aumac.cli import main
        sys.exit(main(sys.argv[sys.argv.index('--sdk-cli')+1:]))
    if '--package-check' in sys.argv:
        import tkinter,frida,PIL,numpy,miniaudio,keyring,AppKit,zstandard
        from wechat_aumac.native.session import NativeSession
        from app.ui.main_window import MainWindow
        from importlib.resources import files
        for name in ['agent.js','database_agent.js','resource_agent.js','sns_upload_agent.js','cdn_download_agent.js']:
            assert files('wechat_aumac.native').joinpath(name).is_file(), 'Missing native resource: '+name
        assert (BUNDLE/'assets/app_icon.png').is_file()
        assert (BUNDLE/'installer_payload/native-profile.json').is_file()
        print(json.dumps({'standalone':True,'architecture':'arm64','dependencies':'ok','personal_data':False}));sys.exit(0)
    if '--wxgf-worker' in sys.argv:
        from wechat_aumac.native.wxgf import _worker
        print(json.dumps(_worker(json.loads(sys.stdin.read()))));sys.exit(0)
    if '--incoming-document-worker' in sys.argv:
        from app.incoming_documents import worker_main
        worker_main();sys.exit(0)
    if '--incoming-video-worker' in sys.argv:
        from app.incoming_video import _worker
        print(json.dumps(_worker(json.load(sys.stdin))));sys.exit(0)
    if '--web-render-worker' in sys.argv:
        from app.web_media import render_worker
        render_worker(sys.argv[-1]);sys.exit(0)
    if '--menu-bar-helper' in sys.argv:
        from app.menu_bar_helper import main as menu_bar_helper
        index=sys.argv.index('--menu-bar-helper')
        sys.exit(menu_bar_helper(sys.argv[index+1],sys.argv[index+2]))
    if '--setup' in sys.argv or (APP and '安装助手' in APP.name):setup()
    elif SDK_ONLY:
        import tkinter as tk
        from tkinter import messagebox
        root=tk.Tk();root.withdraw()
        messagebox.showinfo('Wemac-auto SDK', 'SDK 已安装。\n命令行入口：'+str(APP.parent/'bin/wechat-aumac')+'\n函数库源码：'+str(APP.parent/'sdk/src')+'\n请先登录同目录的 WeChat-Wemac。')
        root.destroy()
    else:
        import run
        sys.exit(run.main())
