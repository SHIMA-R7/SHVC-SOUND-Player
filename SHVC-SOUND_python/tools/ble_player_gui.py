"""Bluetooth controls for SHVC-SOUND Player (Tkinter + Bleak)."""
import asyncio
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog
from ble_player import Player
from ble_song import prepare_song

class App:
    def __init__(self, root):
        self.root=root
        root.title('SHVC-SOUND Bluetooth Player')
        root.geometry('670x620')
        self.events=queue.Queue()
        self.loop=asyncio.new_event_loop()
        self.worker=threading.Thread(target=self.loop.run_forever,daemon=True)
        self.worker.start()
        self.player=Player()
        self.busy=False
        self.connected=False
        self.controls=[]
        frame=ttk.Frame(root,padding=14); frame.pack(fill='both',expand=True)
        self.status=tk.StringVar(value='未接続')
        ttk.Label(frame,textvariable=self.status).pack(anchor='w')
        row=ttk.Frame(frame); row.pack(fill='x',pady=8)
        self.connect_button=ttk.Button(row,text='Bluetooth接続',command=self.connect)
        self.connect_button.pack(side='left')
        self.disconnect_button=ttk.Button(row,text='切断',command=self.disconnect,state='disabled')
        self.disconnect_button.pack(side='left',padx=5)
        self.button(row,'状態更新',lambda:self.command(1))
        songs=ttk.LabelFrame(frame,text='曲の保存・再生',padding=10); songs.pack(fill='x',pady=6)
        self.path=tk.StringVar()
        ttk.Entry(songs,textvariable=self.path).pack(fill='x')
        row=ttk.Frame(songs); row.pack(fill='x',pady=6)
        ttk.Button(row,text='SPC / MIDIを選ぶ',command=self.select).pack(side='left')
        self.button(row,'送信して再生',self.upload)
        self.button(row,'保存曲を再生',lambda:self.command(2))
        self.button(row,'停止',lambda:self.command(3))
        self.spc_volume=tk.DoubleVar(value=1.0)
        ttk.Label(songs,text='SPC音量倍率（送信時に適用）').pack(anchor='w')
        ttk.Scale(songs,from_=0,to=1,variable=self.spc_volume).pack(fill='x')
        self.progress=ttk.Progressbar(songs,maximum=100); self.progress.pack(fill='x',pady=4)
        row=ttk.Frame(songs); row.pack(fill='x')
        self.muted=tk.BooleanVar()
        self.check(row,'ミュート',self.muted,lambda:self.command(4,bytes([self.muted.get()])))
        self.repeat=tk.BooleanVar(value=True)
        self.check(row,'MIDIファイルをループ',self.repeat,lambda:self.command(8,bytes([self.repeat.get()])))
        self.boot=tk.BooleanVar(value=True)
        self.check(row,'電源投入時に再生',self.boot,lambda:self.command(9,bytes([self.boot.get()])))
        live=ttk.LabelFrame(frame,text='MIDI演奏・パラメータ',padding=10); live.pack(fill='x',pady=6)
        row=ttk.Frame(live); row.pack(fill='x')
        self.button(row,'MIDIモードに切替',lambda:self.command(6))
        self.button(row,'ドを試聴',self.note)
        self.channel=tk.IntVar(value=1)
        ttk.Label(row,text='チャンネル').pack(side='left',padx=6)
        ttk.Spinbox(row,from_=1,to=16,width=4,textvariable=self.channel).pack(side='left')
        row=ttk.Frame(live); row.pack(fill='x',pady=6)
        self.master=tk.IntVar(value=89); self.volume=tk.IntVar(value=100)
        self.pan=tk.IntVar(value=64); self.program=tk.IntVar(value=0)
        for label,var in [('全体音量',self.master),('Ch音量',self.volume),('パン',self.pan),('音色',self.program)]:
            ttk.Label(row,text=label).pack(side='left',padx=3)
            ttk.Spinbox(row,from_=0,to=127,width=4,textvariable=var).pack(side='left')
        row=ttk.Frame(live); row.pack(fill='x',pady=4)
        self.expression=tk.IntVar(value=127); self.bend=tk.IntVar(value=0); self.sustain=tk.BooleanVar()
        ttk.Label(row,text='Expression').pack(side='left')
        ttk.Spinbox(row,from_=0,to=127,width=4,textvariable=self.expression).pack(side='left',padx=4)
        ttk.Label(row,text='Pitch Bend').pack(side='left')
        ttk.Spinbox(row,from_=-8192,to=8191,width=7,textvariable=self.bend).pack(side='left',padx=4)
        ttk.Checkbutton(row,text='サステイン',variable=self.sustain).pack(side='left',padx=4)
        self.button(live,'MIDI設定を反映',self.parameters)
        ttk.Label(live,text='MIDIファイル再生と鍵盤入力は8ボイス。音色番号は0〜127。').pack(anchor='w',pady=3)
        ttk.Label(frame,text='SPCは曲自身のループで再生。音量変更は再送信が必要。').pack(anchor='w')
        self.log=tk.Text(frame,height=5,state='disabled'); self.log.pack(fill='both',expand=True,pady=6)
        root.protocol('WM_DELETE_WINDOW',self.close)
        root.after(100,self.poll)

    def button(self,parent,text,fn):
        b=ttk.Button(parent,text=text,command=fn,state='disabled')
        if isinstance(parent,ttk.LabelFrame): b.pack(anchor='w',pady=3)
        else: b.pack(side='left',padx=3)
        self.controls.append(b)

    def check(self,parent,text,var,fn):
        b=ttk.Checkbutton(parent,text=text,variable=var,command=fn,state='disabled')
        b.pack(side='left',padx=3); self.controls.append(b)

    def submit(self,coroutine):
        if self.busy:
            coroutine.close(); return
        self.busy=True; self.update_buttons()
        future=asyncio.run_coroutine_threadsafe(coroutine,self.loop)
        def done(f):
            try: self.events.put(('done',f.result()))
            except BaseException as e: self.events.put(('error',str(e)))
        future.add_done_callback(done)

    def update_buttons(self):
        for b in self.controls: b.configure(state='normal' if self.connected and not self.busy else 'disabled')
        self.connect_button.configure(state='normal' if not self.connected and not self.busy else 'disabled')
        self.disconnect_button.configure(state='normal' if self.connected and not self.busy else 'disabled')

    def connect(self):
        async def task():
            await self.player.connect(); self.events.put(('connected',True)); return self.player.last_status
        self.submit(task())

    def disconnect(self):
        async def task():
            await self.player.close(); self.events.put(('connected',False)); return '切断'
        self.submit(task())

    def command(self,op,payload=b''):
        self.submit(self.player.command(op,payload))

    def select(self):
        p=filedialog.askopenfilename(filetypes=[('SPC / MIDI','*.spc *.mid *.midi'),('All','*.*')])
        if p: self.path.set(p)

    def upload(self):
        path=self.path.get(); volume=self.spc_volume.get()
        if not path: self.select(); return
        async def task():
            self.events.put(('status','曲データを準備中'))
            data=await asyncio.to_thread(prepare_song,Path(path),volume)
            await self.player.upload(data,lambda d,t:self.events.put(('progress',d*100/t)))
            self.events.put(('status','保存完了。SHVC-SOUNDへ転送中（SPCは約50秒）'))
            return await self.player.command(2)
        self.submit(task())

    def note(self):
        channel=self.channel.get()-1
        async def task():
            if not 0<=channel<16: raise ValueError('チャンネルは1〜16')
            await self.player.command(6)
            try:
                await self.player.midi([0x90|channel,60,100]); await asyncio.sleep(1)
            finally: await self.player.midi([0x80|channel,60,0])
            return '試聴終了'
        self.submit(task())

    def parameters(self):
        channel=self.channel.get()-1
        values=[self.master.get(),self.volume.get(),self.pan.get(),self.program.get()]
        expression=self.expression.get(); bend=self.bend.get(); sustain=self.sustain.get()
        async def task():
            if not 0<=channel<16 or any(not 0<=v<=127 for v in values): raise ValueError('設定範囲を確認')
            if not 0<=expression<=127 or not -8192<=bend<=8191: raise ValueError('設定範囲を確認')
            await self.player.command(5,bytes([values[0]]))
            await self.player.command(7,bytes([channel,7,values[1]]))
            await self.player.command(7,bytes([channel,10,values[2]]))
            await self.player.command(10,bytes([channel,values[3]]))
            await self.player.command(7,bytes([channel,11,expression]))
            await self.player.command(7,bytes([channel,64,127 if sustain else 0]))
            value=bend+8192
            await self.player.midi([0xE0|channel,value&127,value>>7])
            return 'MIDI設定を反映（ファイル内のCC/音色イベントで上書きされる場合あり）'
        self.submit(task())

    def poll(self):
        while True:
            try: kind,value=self.events.get_nowait()
            except queue.Empty: break
            if kind=='connected': self.connected=value
            elif kind=='progress': self.progress['value']=value
            elif kind=='status': self.status.set(value)
            else:
                self.busy=False
                if isinstance(value,dict):
                    self.status.set(f"{value['mode']} / 音量 {value['master']} / MIDI欠落 {value['dropped']}")
                    self.muted.set(value['muted'])
                    self.repeat.set(value['loop']); self.boot.set(value['boot'])
                self.log.configure(state='normal'); self.log.insert('end',str(value)+'\n'); self.log.see('end'); self.log.configure(state='disabled')
        if self.connected and self.player.client and not self.player.client.is_connected:
            self.connected=False; self.status.set('Bluetooth切断')
        self.update_buttons(); self.root.after(100,self.poll)

    def close(self):
        async def task():
            await self.player.close()
        future=asyncio.run_coroutine_threadsafe(task(),self.loop)
        def finish():
            if future.done(): self.loop.call_soon_threadsafe(self.loop.stop); self.root.destroy()
            else: self.root.after(100,finish)
        finish()

if __name__=='__main__':
    root=tk.Tk(); App(root); root.mainloop()
