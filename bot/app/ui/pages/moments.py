"""Explicit native Moments publishing and exact-post commenting."""
import hashlib,json,queue,threading,time,tkinter as tk
from pathlib import Path
from tkinter import filedialog,ttk
from .base import BasePage
from ..theme import C,font,px
from ..widgets import RoundedButton
from ...paths import DATA

class MomentsPage(BasePage):
    key='moments';title='朋友圈';subtitle='通过微信内部函数发布动态、读取并评论朋友圈'
    def __init__(self,parent,app):
        super().__init__(parent,app)
        self.posts=[];self._busy=False;self._results=queue.Queue();self.image=tk.StringVar()
        body=tk.Frame(self,bg=C['bg']);body.pack(fill='both',expand=True,padx=px(16),pady=px(12))
        tk.Label(body,text='发布内容（当前为公开可见）',bg=C['bg'],fg=C['text'],font=font(11,'bold')).pack(anchor='w')
        self.text=tk.Text(body,height=4,wrap='word',font=font(10));self.text.pack(fill='x',pady=px(6))
        bar=tk.Frame(body,bg=C['bg']);bar.pack(fill='x')
        RoundedButton(bar,text='选择一张配图',command=self.pick_image,width=140).pack(side='left')
        tk.Entry(bar,textvariable=self.image).pack(side='left',fill='x',expand=True,padx=px(8))
        self.publish=RoundedButton(bar,text='发布朋友圈',command=self.send_post,width=140);self.publish.pack(side='right')
        tk.Label(body,text='填写正文后点击发布会立即提交；未确认的提交不会自动重试。',bg=C['bg'],fg=C['muted'],font=font(8)).pack(anchor='w',pady=px(8))
        RoundedButton(body,text='读取最近朋友圈',command=self.refresh_posts,width=160).pack(anchor='w')
        self.list=ttk.Treeview(body,columns=('author','text','time'),show='headings',height=7,selectmode='browse')
        for name,label in [('author','作者'),('text','正文'),('time','发布时间')]:self.list.heading(name,text=label)
        self.list.column('author',width=140,stretch=False);self.list.column('text',width=500);self.list.column('time',width=140,stretch=False)
        self.list.pack(fill='both',expand=True,pady=px(8))
        row=tk.Frame(body,bg=C['bg']);row.pack(fill='x')
        self.comment=tk.Entry(row,font=font(10));self.comment.pack(side='left',fill='x',expand=True)
        self.comment_btn=RoundedButton(row,text='评论选中动态',command=self.send_comment,width=160);self.comment_btn.pack(side='right',padx=px(8))
        self.status=tk.StringVar(value='选择动态后填写评论；读取列表不会发表互动。')
        tk.Label(body,textvariable=self.status,bg=C['bg'],fg=C['text'],font=font(9),wraplength=1000,anchor='w').pack(fill='x',pady=px(8))
        self.after(150,self.poll)
    def pick_image(self):
        value=filedialog.askopenfilename(parent=self,title='选择朋友圈配图',filetypes=[('图片','*.png *.jpg *.jpeg')])
        if value:self.image.set(value)
    def run(self,operation,*,receipt=None):
        if self._busy:return
        self._busy=True;self.status.set('正在通过原生通道处理…')
        def work():
            try:
                with self.service._adapter_lock:
                    adapter=self.service.adapter
                    if not adapter or not adapter.connected:raise RuntimeError('请先启动机器人并连接微信。')
                    ledger=DATA/'moments_manual_receipts.json'
                    records=json.loads(ledger.read_text()) if ledger.exists() else {}
                    if receipt:
                        key=hashlib.sha256(json.dumps(receipt,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
                        if key in records:raise RuntimeError('相同内容已经提交过；为避免重复，未再次发送。请先核对朋友圈。')
                        records[key]={'at':time.time(),'status':'submitted'}
                        temp=ledger.with_suffix('.tmp');temp.write_text(json.dumps(records));temp.replace(ledger)
                    result=operation(adapter)
                    if receipt:
                        records[key]['status']=result.status
                        temp=ledger.with_suffix('.tmp');temp.write_text(json.dumps(records));temp.replace(ledger)
                self._results.put(('ok',result))
            except Exception as exc:self._results.put(('error',str(exc)))
        threading.Thread(target=work,daemon=True).start()
    def refresh_posts(self):self.run(lambda a:a.read_moments(limit=30))
    def send_post(self):
        text=self.text.get('1.0','end').strip();image=self.image.get().strip()
        if not text:self.status.set('请填写朋友圈正文。');return
        if image and not Path(image).is_file():self.status.set('配图不存在，请重新选择。');return
        image_hash=hashlib.sha256(Path(image).read_bytes()).hexdigest() if image else ''
        self.run(lambda a:a.publish_moment(text,image or None),receipt={'kind':'publish','text':text,'image':image_hash})
    def send_comment(self):
        selected=self.list.selection();text=self.comment.get().strip()
        if not selected or not text:self.status.set('请选择一条动态并填写评论。');return
        if len(text)>600:self.status.set('评论请控制在 600 字以内。');return
        post=dict(self.posts[int(selected[0])])
        self.run(lambda a:a.comment_moment(post,text),receipt={'kind':'comment','id':str(post['id']),'owner':post['username'],'text':text})
    def poll(self):
        try:
            while True:
                state,result=self._results.get_nowait();self._busy=False
                if state=='error':self.status.set(result)
                elif isinstance(result,list):
                    self.posts=result;self.list.delete(*self.list.get_children())
                    for i,p in enumerate(result):
                        timestamp=time.strftime('%m-%d %H:%M',time.localtime(int(p.get('create_time') or 0)))
                        self.list.insert('', 'end',iid=str(i),values=(p.get('nickname') or p['username'],p.get('text') or '[媒体动态]',timestamp))
                    self.status.set(f'已读取 {len(result)} 条动态；请选择需要评论的目标。')
                else:self.status.set(result.message or ('已提交，服务器确认成功。' if result.ok else '未确认成功，请核对后再操作。'))
        except queue.Empty:pass
        self.after(150,self.poll)
