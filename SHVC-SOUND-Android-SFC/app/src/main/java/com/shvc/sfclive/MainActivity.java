package com.shvc.sfclive;

import android.app.Activity;
import android.os.Bundle;
import android.os.Handler;
import android.content.Intent;
import android.graphics.Color;
import android.view.*;
import android.widget.*;
import java.io.*;
import java.util.concurrent.Executors;
import java.util.concurrent.ExecutorService;

public final class MainActivity extends Activity implements SurfaceHolder.Callback {
    static { System.loadLibrary("shvc_core"); System.loadLibrary("shvc_frontend"); }
    private native void nativeStart(String rom, String host, String directory);
    private native void nativeStop();
    private native void nativeSurface(Surface surface);
    private native void nativeButton(int id, boolean down);
    private native String nativeStatus();
    private final Handler handler = new Handler();
    private final ExecutorService tasks = Executors.newSingleThreadExecutor();
    private TextView status;
    private EditText host;
    private boolean autoStart;
    private android.net.wifi.WifiManager.WifiLock wifiLock;
    private File rom;
    private final Runnable refresh = new Runnable() {
        public void run() { status.setText(nativeStatus()); handler.postDelayed(this, 500); }
    };
    private int dp(int value) { return (int)(value * getResources().getDisplayMetrics().density + .5f); }
    private Button button(String title) {
        Button b = new Button(this); b.setText(title); b.setTextColor(Color.WHITE);
        b.setTextSize(13); b.setBackgroundTintList(android.content.res.ColorStateList.valueOf(0xff24364b));
        b.setMinWidth(0); b.setMinimumWidth(0); b.setPadding(0,0,0,0); return b;
    }
    private void key(LinearLayout row, String title, int id) {
        Button b = button(title); row.addView(b, new LinearLayout.LayoutParams(dp(54), dp(47)));
        b.setOnTouchListener((v,e)-> {
            if(e.getActionMasked()==MotionEvent.ACTION_DOWN) { nativeButton(id,true); b.setAlpha(.55f); return true; }
            if(e.getActionMasked()==MotionEvent.ACTION_UP || e.getActionMasked()==MotionEvent.ACTION_CANCEL) {
                nativeButton(id,false); b.setAlpha(1); v.performClick(); return true;
            } return true;
        });
    }
    private LinearLayout column() { LinearLayout l=new LinearLayout(this); l.setOrientation(LinearLayout.VERTICAL); return l; }
    private LinearLayout row() { LinearLayout l=new LinearLayout(this); l.setGravity(Gravity.CENTER); return l; }
    @Override public void onCreate(Bundle b) {
        super.onCreate(b); getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        android.net.wifi.WifiManager wifi=(android.net.wifi.WifiManager)getApplicationContext().getSystemService(WIFI_SERVICE);
        if(wifi!=null) wifiLock=wifi.createWifiLock(android.os.Build.VERSION.SDK_INT>=29?android.net.wifi.WifiManager.WIFI_MODE_FULL_LOW_LATENCY:android.net.wifi.WifiManager.WIFI_MODE_FULL_HIGH_PERF,"SHVC-SFC-live");
        rom = new File(getFilesDir(),"game.sfc");
        LinearLayout root=column(); root.setBackgroundColor(0xff0c1420); root.setPadding(dp(12),dp(10),dp(12),dp(8));
        LinearLayout top=row(); TextView title=new TextView(this); title.setText("SHVC SFC LIVE"); title.setTextColor(0xff66ead4); title.setTextSize(18);
        top.addView(title,new LinearLayout.LayoutParams(0,dp(44),1));
        host=new EditText(this); host.setSingleLine(true); host.setTextSize(14); host.setTextColor(Color.WHITE); host.setHint("ESP IP");
        String saved=getPreferences(0).getString("host", ""); String extra=getIntent().getStringExtra("shvc_host"); host.setText(extra==null?saved:extra);
        top.addView(host,new LinearLayout.LayoutParams(dp(170),dp(44)));
        Button choose=button("ROM選択"),play=button("開始"),stop=button("停止");
        top.addView(choose,new LinearLayout.LayoutParams(dp(82),dp(44))); top.addView(play,new LinearLayout.LayoutParams(dp(66),dp(44))); top.addView(stop,new LinearLayout.LayoutParams(dp(66),dp(44))); root.addView(top);
        choose.setOnClickListener(v->{ Intent i=new Intent(Intent.ACTION_OPEN_DOCUMENT); i.addCategory(Intent.CATEGORY_OPENABLE); i.setType("*/*"); startActivityForResult(i,1); });
        play.setOnClickListener(v->start()); stop.setOnClickListener(v->tasks.execute(this::nativeStop));
        LinearLayout middle=row();
        LinearLayout left=column(); LinearLayout l1=row(),l2=row(),l3=row(); key(l1,"L",10);key(l1,"↑",4);key(l2,"←",6);key(l2,"↓",5);key(l2,"→",7); key(l3,"SELECT",2);key(l3,"START",3); left.addView(l1);left.addView(l2);left.addView(l3);middle.addView(left);
        FrameLayout frame=new FrameLayout(this);
        SurfaceView screen=new SurfaceView(this); screen.getHolder().addCallback(this);
        frame.addView(screen,new FrameLayout.LayoutParams(-1,-1,Gravity.CENTER));
        frame.addOnLayoutChangeListener((v,a,c,d,e,f,g,h,i)-> { int w=d-a,ht=e-c; int sw=Math.min(w,ht*4/3),sh=sw*3/4; FrameLayout.LayoutParams p=(FrameLayout.LayoutParams)screen.getLayoutParams(); if(p.width!=sw || p.height!=sh) { p.width=sw;p.height=sh;screen.setLayoutParams(p); } });
        middle.addView(frame,new LinearLayout.LayoutParams(0,-1,1));
        LinearLayout right=column(); LinearLayout r1=row(),r2=row(),r3=row();key(r1,"X",9);key(r1,"R",11);key(r2,"Y",1);key(r2,"A",8);key(r3,"B",0);right.addView(r1);right.addView(r2);right.addView(r3);middle.addView(right);
        root.addView(middle,new LinearLayout.LayoutParams(-1,0,1));
        status=new TextView(this);status.setTextColor(0xffaebdce);status.setTextSize(13);root.addView(status);setContentView(root);
        root.setOnApplyWindowInsetsListener((v,insets)-> {
            if(android.os.Build.VERSION.SDK_INT>=30) {
                android.graphics.Insets bars=insets.getInsets(WindowInsets.Type.systemBars());
                v.setPadding(bars.left+dp(8),bars.top+dp(4),bars.right+dp(8),bars.bottom+dp(4));
            } else v.setPadding(insets.getSystemWindowInsetLeft()+dp(8),insets.getSystemWindowInsetTop()+dp(4),insets.getSystemWindowInsetRight()+dp(8),insets.getSystemWindowInsetBottom()+dp(4));
            return insets;
        });
        autoStart=getIntent().getBooleanExtra("auto_start",false);
    }
    private void start() {
        if(!rom.exists()) { status.setText("ROMを選択してください"); return; }
        String ip=host.getText().toString().trim(); if(ip.isEmpty()){status.setText("ESPのIPアドレスを入力してください");return;}
        getPreferences(0).edit().putString("host",ip).apply(); tasks.execute(()->nativeStart(rom.getAbsolutePath(),ip,getFilesDir().getAbsolutePath()));
    }
    @Override public void onResume(){super.onResume();if(wifiLock!=null&&!wifiLock.isHeld())wifiLock.acquire();handler.post(refresh);if(autoStart){autoStart=false;start();}}
    @Override public void onPause(){handler.removeCallbacks(refresh);tasks.execute(this::nativeStop);if(wifiLock!=null&&wifiLock.isHeld())wifiLock.release();super.onPause();}
    @Override public void onDestroy(){tasks.execute(this::nativeStop);tasks.shutdown();super.onDestroy();}
    public void surfaceCreated(SurfaceHolder h){nativeSurface(h.getSurface());}
    public void surfaceChanged(SurfaceHolder h,int f,int w,int height){nativeSurface(h.getSurface());}
    public void surfaceDestroyed(SurfaceHolder h){nativeSurface(null);}
    @Override public void onActivityResult(int request,int result,Intent data){super.onActivityResult(request,result,data);if(request==1&&result==RESULT_OK&&data!=null){
        tasks.execute(()-> { try(InputStream in=getContentResolver().openInputStream(data.getData());OutputStream out=new FileOutputStream(rom)) {byte[] buffer=new byte[65536];int n;while((n=in.read(buffer))!=-1)out.write(buffer,0,n);handler.post(()->status.setText("ROMを読み込んだ。開始できます"));}catch(Exception ex){handler.post(()->status.setText(ex.toString()));} });
    }}
}
