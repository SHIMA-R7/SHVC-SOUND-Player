package com.shvc.sounddeck

import androidx.compose.animation.core.*
import androidx.compose.foundation.*
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.LibraryMusic
import androidx.compose.material.icons.automirrored.rounded.VolumeOff
import androidx.compose.material.icons.automirrored.rounded.VolumeUp
import androidx.compose.material.icons.rounded.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.onClick
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlin.math.sin

private val Night=Color(0xFF090B12)
private val Panel=Color(0xFF141927)
private val Line=Color(0xFF293044)
private val Ink=Color(0xFFF5F4EF)
private val Dim=Color(0xFF9DA8BD)
private val Mint=Color(0xFF55F0D6)
private val Lilac=Color(0xFFB099FF)
private val Coral=Color(0xFFFFA185)

@Composable fun DeckTheme(content: @Composable ()->Unit) {
    MaterialTheme(colorScheme=darkColorScheme(primary=Mint,secondary=Lilac,background=Night,surface=Panel,
        onPrimary=Night,onSurface=Ink,onBackground=Ink,outline=Line),content=content)
}
@Composable private fun Caption(text: String,color: Color=Dim) {
    Text(text,color=color,fontSize=10.sp,fontWeight=FontWeight.Bold,letterSpacing=1.7.sp,fontFamily=FontFamily.Monospace)
}
@Composable private fun Tile(modifier: Modifier=Modifier,content: @Composable ColumnScope.()->Unit) {
    Column(modifier.fillMaxWidth().clip(RoundedCornerShape(22.dp)).background(Panel).border(1.dp,Line,RoundedCornerShape(22.dp)).padding(18.dp),content=content)
}
@OptIn(ExperimentalMaterial3Api::class)
@Composable fun SoundDeck(model: DeckViewModel,scan: ()->Unit,pick: ()->Unit) {
    val ui by model.ui.collectAsStateWithLifecycle()
    val link by model.ble.link.collectAsStateWithLifecycle()
    val device by model.ble.status.collectAsStateWithLifecycle()
    var tab by rememberSaveable { mutableIntStateOf(0) }
    var showDevices by remember { mutableStateOf(false) }
    val view=LocalView.current
    DisposableEffect(ui.busy) { view.keepScreenOn=ui.busy; onDispose { view.keepScreenOn=false } }
    Scaffold(containerColor=Night,bottomBar={
        Row(Modifier.fillMaxWidth().background(Night).navigationBarsPadding().padding(horizontal=20.dp,vertical=10.dp),horizontalArrangement=Arrangement.SpaceEvenly) {
            listOf("DECK" to Icons.Rounded.LibraryMusic,"MIDI" to Icons.Rounded.Piano,"SETUP" to Icons.Rounded.Tune).forEachIndexed { index,(title,icon) ->
                val active=tab==index
                Column(Modifier.weight(1f).clip(RoundedCornerShape(15.dp)).background(if(active) Mint.copy(alpha=.08f) else Color.Transparent)
                    .clickable { tab=index }.padding(vertical=10.dp),horizontalAlignment=Alignment.CenterHorizontally) {
                    Icon(icon,title,tint=if(active) Mint else Dim,modifier=Modifier.size(22.dp)); Spacer(Modifier.height(5.dp)); Caption(title,if(active) Mint else Dim)
                }
            }
        }
    }) { padding ->
        LazyColumn(Modifier.fillMaxSize().padding(padding),contentPadding=PaddingValues(start=20.dp,end=20.dp,top=15.dp,bottom=24.dp),verticalArrangement=Arrangement.spacedBy(18.dp)) {
            item {
                Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.SpaceBetween) {
                    Column { Caption("SHVC-SOUND / ESP32",Mint); Text("Sound Deck",fontSize=30.sp,fontWeight=FontWeight.ExtraBold,letterSpacing=(-1).sp,color=Ink) }
                    Surface(shape=RoundedCornerShape(14.dp),color=if(link.ready) Mint.copy(alpha=.1f) else Panel,
                        modifier=Modifier.clickable(enabled=!ui.busy) { showDevices=true; if(!link.ready) scan() }) {
                        Row(Modifier.padding(12.dp),verticalAlignment=Alignment.CenterVertically) {
                            Icon(Icons.Rounded.Bluetooth,if(link.ready) "接続済み" else "Bluetooth接続",tint=if(link.ready) Mint else Dim,modifier=Modifier.size(17.dp))
                            Spacer(Modifier.width(5.dp)); Text(if(link.ready) "LINKED" else "CONNECT",color=if(link.ready) Mint else Dim,fontSize=10.sp,fontWeight=FontWeight.Bold)
                        }
                    }
                }
            }
            if(ui.error!=null || ui.retryName!=null) item {
                Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(Coral.copy(alpha=.1f)).padding(14.dp),verticalAlignment=Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(ui.error ?: "転送に失敗した曲をやり直せます",color=Coral,fontSize=12.sp)
                        if(ui.retryName!=null) TextButton(onClick=model::retryFailedTransfer,enabled=!ui.busy && !ui.playlistActive) {
                            Text("再転送 · ${ui.retryName}",color=Mint)
                        }
                    }; IconButton(onClick=model::clearError,modifier=Modifier.size(28.dp)) { Icon(Icons.Rounded.Close,"閉じる",tint=Coral) }
                }
            }
            if(ui.busy) item {
                Tile {
                    Row(verticalAlignment=Alignment.CenterVertically) {
                        CircularProgressIndicator(Modifier.size(18.dp),color=Mint,strokeWidth=2.dp)
                        Spacer(Modifier.width(12.dp)); Text(ui.stage,color=Ink,fontSize=13.sp,modifier=Modifier.weight(1f))
                        if(ui.cancellable) TextButton(onClick=model::cancelTransfer) { Text("中止") }
                    }
                    TransferProgress(ui.progress)
                }
            }
            when(tab) {
                0 -> {
                    item { NowPlaying(ui,device,link.ready) }
                    item {
                        Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(10.dp)) {
                            Button(onClick=model::play,enabled=link.ready && !ui.busy,shape=RoundedCornerShape(18.dp),modifier=Modifier.weight(1f).height(56.dp)) {
                                Icon(Icons.Rounded.PlayArrow,null); Spacer(Modifier.width(5.dp)); Text("PLAY",fontWeight=FontWeight.ExtraBold,letterSpacing=1.sp)
                            }
                            OutlinedButton(onClick=model::stop,enabled=link.ready && (!ui.busy || ui.playlistActive || ui.streaming),shape=RoundedCornerShape(18.dp),modifier=Modifier.size(56.dp),contentPadding=PaddingValues(0.dp)) { Icon(Icons.Rounded.Stop,"停止") }
                            OutlinedButton(onClick={model.mute(!(device?.muted ?: false))},enabled=link.ready && !ui.busy,shape=RoundedCornerShape(18.dp),modifier=Modifier.size(56.dp),contentPadding=PaddingValues(0.dp)) {
                                Icon(if(device?.muted==true) Icons.AutoMirrored.Rounded.VolumeOff else Icons.AutoMirrored.Rounded.VolumeUp,"ミュート",tint=if(device?.muted==true) Coral else Mint)
                            }
                        }
                    }
                    item {
                        Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween,verticalAlignment=Alignment.CenterVertically) {
                            Column { Caption("YOUR COLLECTION"); Text("ライブラリ",color=Ink,fontSize=20.sp,fontWeight=FontWeight.Bold) }
                            OutlinedButton(onClick=pick,enabled=!ui.busy,shape=RoundedCornerShape(12.dp),contentPadding=PaddingValues(horizontal=12.dp,vertical=4.dp)) { Icon(Icons.Rounded.Add,null,Modifier.size(16.dp)); Text("追加",fontSize=12.sp) }
                        }
                    }
                    item { PlaylistPanel(model,ui,link.ready) }
                    if(ui.library.isEmpty()) item {
                        Tile {
                            Icon(Icons.Rounded.AudioFile,null,tint=Lilac,modifier=Modifier.size(35.dp)); Spacer(Modifier.height(12.dp))
                            Text("曲を連れてこよう。",fontSize=18.sp,fontWeight=FontWeight.Bold,color=Ink)
                            Text("SPC・MIDIは音源へ保存して再生。\nWAVはスマホ接続でストリーミング。",fontSize=12.sp,color=Dim,modifier=Modifier.padding(top=8.dp),lineHeight=19.sp)
                            TextButton(onClick=pick,enabled=!ui.busy) { Text("ファイルを選ぶ →") }
                        }
                    }
                    items(ui.library,key={it.uri}) { song ->
                        SongRow(song,song.uri==ui.selected,!ui.busy) { model.select(song.uri) }
                    }
                    if(ui.library.isNotEmpty()) item {
                        Column {
                            if(ui.library.firstOrNull { it.uri==ui.selected }?.kind=="WAV") {
                                Caption("WAV FORMAT",Coral)
                                listOf(16000 to 1,16000 to 2,32000 to 1,32000 to 2).chunked(2).forEach { row ->
                                    Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(8.dp)) {
                                        row.forEach { (rate,channels) ->
                                            FilterChip(selected=ui.wavRate==rate && ui.wavChannels==channels,
                                                onClick={model.wavFormat(rate,channels)},enabled=!ui.busy,
                                                label={Text("${rate/1000} kHz ${if(channels==2) "STEREO" else "MONO"}",fontSize=12.sp)},modifier=Modifier.weight(1f))
                                        }
                                    }
                                }
                                Text("再生中はスマホの接続を維持してください",color=Dim,fontSize=11.sp)
                                Spacer(Modifier.height(12.dp))
                            }
                            Button(onClick=model::transferSelected,enabled=link.ready && !ui.busy && ui.selected!=null,shape=RoundedCornerShape(16.dp),modifier=Modifier.fillMaxWidth().height(52.dp)) {
                                Icon(Icons.Rounded.Upload,null); Spacer(Modifier.width(8.dp)); Text(if(ui.library.firstOrNull { it.uri==ui.selected }?.kind=="WAV") "WAVストリーミング" else "転送して再生",fontWeight=FontWeight.Bold)
                            }
                            Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween,verticalAlignment=Alignment.CenterVertically) {
                                Text("SPCは音源への転送進捗を表示",color=Dim,fontSize=11.sp)
                                TextButton(onClick=model::removeSelected,enabled=!ui.busy) { Text("一覧から削除",fontSize=11.sp,color=Dim) }
                            }
                        }
                    }
                }
                1 -> {
                    item { MidiPanel(model,device,link.ready && !ui.busy) }
                }
                else -> {
                    item { SettingsPanel(model,device,link,ui.busy) }
                }
            }
            item { Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.Center) { Caption("8 VOICES · REAL SILICON · NO EMULATION",Dim.copy(alpha=.55f)) } }
        }
    }
    if(showDevices) {
        ModalBottomSheet(onDismissRequest={showDevices=false; model.ble.stopScan()},containerColor=Panel) {
            Column(Modifier.fillMaxWidth().padding(horizontal=24.dp).padding(bottom=30.dp),verticalArrangement=Arrangement.spacedBy(14.dp)) {
                Caption("WIRELESS CONNECTION",Mint); Text("音源を選ぶ",fontSize=25.sp,fontWeight=FontWeight.Bold,color=Ink)
                if(link.ready) {
                    Text("SHVC-SOUND Player · 接続済み",color=Mint)
                    OutlinedButton(onClick={model.disconnect(); showDevices=false},modifier=Modifier.fillMaxWidth()) { Text("切断") }
                } else {
                    if(link.scanning) Row(verticalAlignment=Alignment.CenterVertically) { CircularProgressIndicator(Modifier.size(17.dp),strokeWidth=2.dp); Spacer(Modifier.width(12.dp)); Text("近くのSHVC-SOUNDを検索中",color=Dim,fontSize=13.sp) }
                    link.devices.forEach { deck ->
                        Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(Night).clickable(enabled=!ui.busy) {
                            model.connect(deck.address); showDevices=false
                        }.padding(17.dp),verticalAlignment=Alignment.CenterVertically) {
                            Icon(Icons.Rounded.DeveloperBoard,null,tint=Mint); Spacer(Modifier.width(15.dp))
                            Column(Modifier.weight(1f)) { Text(deck.name,color=Ink,fontWeight=FontWeight.Bold); Text(deck.address,fontFamily=FontFamily.Monospace,fontSize=11.sp,color=Dim) }
                            Icon(Icons.Rounded.ChevronRight,null,tint=Mint)
                        }
                    }
                    if(!link.scanning && link.devices.isEmpty()) Text("音源の電源とBluetoothを確認してください。Windows側の操作画面は切断してから接続します。",color=Dim,fontSize=13.sp)
                    OutlinedButton(onClick=scan,enabled=!link.scanning,modifier=Modifier.fillMaxWidth()) { Text("もう一度探す") }
                }
            }
        }
    }
}

@Composable internal fun ColumnScope.TransferProgress(progress: Float?) {
    // Draw and semantics callbacks can outlive the composition that created them.
    // Capture this frame's value, instead of reading a changing nullable UI state.
    val value=progress?.coerceIn(0f,1f)
    Spacer(Modifier.height(12.dp))
    if(value!=null) {
        LinearProgressIndicator(progress={value},modifier=Modifier.fillMaxWidth())
        Text("${(value*100).toInt()}%",fontSize=12.sp,color=Mint,
            modifier=Modifier.align(Alignment.End).padding(top=5.dp))
    } else LinearProgressIndicator(modifier=Modifier.fillMaxWidth())
}

@Composable private fun NowPlaying(ui: DeckUi,status: DeviceStatus?,connected: Boolean) {
    val playing=connected && status?.mode in listOf(1,2,3)
    val transition=rememberInfiniteTransition(label="chip pulse")
    val phase by transition.animateFloat(0f,6.283f,infiniteRepeatable(tween(2800,easing=LinearEasing)),label="phase")
    Box(Modifier.fillMaxWidth().height(218.dp).clip(RoundedCornerShape(25.dp)).background(Brush.linearGradient(listOf(Color(0xFF19243A),Color(0xFF201B34),Panel)))
        .border(1.dp,Color(0xFF34415B),RoundedCornerShape(25.dp))) {
        Canvas(Modifier.fillMaxSize()) {
            for(x in 0..12) drawLine(Color.White.copy(alpha=.025f),Offset(x*size.width/12,0f),Offset(x*size.width/12,size.height))
            for(y in 0..7) drawLine(Color.White.copy(alpha=.025f),Offset(0f,y*size.height/7),Offset(size.width,y*size.height/7))
        }
        Row(Modifier.fillMaxSize().padding(21.dp),verticalAlignment=Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Caption(if(playing) "ON THE DECK" else "READY WHEN YOU ARE",Mint)
                Spacer(Modifier.height(16.dp))
                Text(if(status?.mode==2 || status?.mode==3) "MIDI Session" else ui.playing?.title ?: if(connected) "ESP32の保存曲" else "本物の音源を、\n手のひらから。",
                    color=Ink,fontSize=23.sp,fontWeight=FontWeight.ExtraBold,maxLines=2,overflow=TextOverflow.Ellipsis,lineHeight=29.sp)
                Spacer(Modifier.height(7.dp))
                Text(ui.playing?.detail?.ifBlank { "SPC700 + S-DSP" } ?: "SPC700 + S-DSP",fontSize=11.sp,color=Dim,maxLines=1,overflow=TextOverflow.Ellipsis)
                Spacer(Modifier.height(18.dp))
                Row(verticalAlignment=Alignment.CenterVertically) {
                    Box(Modifier.size(6.dp).background(if(playing) Mint else Dim,CircleShape)); Spacer(Modifier.width(7.dp))
                    Caption(if(connected) status?.modeName ?: "CONNECTED" else "OFFLINE",if(playing) Mint else Dim)
                }
            }
            Canvas(Modifier.size(105.dp).padding(5.dp)) {
                val center=Offset(size.width/2,size.height/2)
                drawCircle(Mint.copy(alpha=.045f),size.width*.49f,center)
                drawCircle(Lilac.copy(alpha=.25f),size.width*.47f,center,style=Stroke(1.5f))
                val body=size.width*.57f; val start=(size.width-body)/2
                drawRoundRect(Color(0xFF0C1220),Offset(start,start),Size(body,body),androidx.compose.ui.geometry.CornerRadius(8f,8f))
                drawRoundRect(Mint.copy(alpha=.7f),Offset(start,start),Size(body,body),androidx.compose.ui.geometry.CornerRadius(8f,8f),style=Stroke(2f))
                repeat(4) { i ->
                    val p=start+body*(i+1)/5
                    drawLine(Lilac,Offset(p,start-9f),Offset(p,start-2f),strokeWidth=3f,cap=StrokeCap.Round)
                    drawLine(Lilac,Offset(p,start+body+2f),Offset(p,start+body+9f),strokeWidth=3f,cap=StrokeCap.Round)
                    drawLine(Lilac,Offset(start-9f,p),Offset(start-2f,p),strokeWidth=3f,cap=StrokeCap.Round)
                    drawLine(Lilac,Offset(start+body+2f,p),Offset(start+body+9f,p),strokeWidth=3f,cap=StrokeCap.Round)
                }
                repeat(5) { i ->
                    val height=body*(if(playing) .22f+.32f*absSin(phase+i) else .22f+.08f*(i%3))
                    val x=start+body*(i+1)/6
                    drawLine(if(i==4) Lilac else Mint,Offset(x,center.y-height/2),Offset(x,center.y+height/2),strokeWidth=4f,cap=StrokeCap.Round)
                }
            }
        }
    }
}
private fun absSin(x: Float)=kotlin.math.abs(sin(x))

@Composable private fun SongRow(song: LibrarySong,selected: Boolean,enabled: Boolean,select: ()->Unit) {
    val color=when(song.kind) { "MIDI"->Lilac; "WAV"->Coral; else->Mint }
    Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(if(selected) Mint.copy(alpha=.06f) else Panel)
        .border(1.dp,if(selected) Mint.copy(alpha=.45f) else Line,RoundedCornerShape(16.dp)).clickable(enabled=enabled,onClick=select).padding(14.dp),verticalAlignment=Alignment.CenterVertically) {
        Box(Modifier.size(42.dp).clip(RoundedCornerShape(12.dp)).background(color.copy(alpha=.12f)),contentAlignment=Alignment.Center) {
            Icon(if(song.kind=="MIDI") Icons.Rounded.Piano else Icons.Rounded.MusicNote,null,tint=color,modifier=Modifier.size(22.dp))
        }
        Spacer(Modifier.width(12.dp)); Column(Modifier.weight(1f)) {
            Text(song.name.substringBeforeLast('.'),color=Ink,fontWeight=FontWeight.SemiBold,fontSize=14.sp,maxLines=1,overflow=TextOverflow.Ellipsis)
            Spacer(Modifier.height(4.dp)); Caption(song.kind,color)
        }
        if(selected) Icon(Icons.Rounded.CheckCircle,"選択中",tint=Mint,modifier=Modifier.size(18.dp))
    }
}

@Composable private fun SliderRow(label: String,value: Float,range: ClosedFloatingPointRange<Float>,enabled: Boolean,onChange: (Float)->Unit,suffix: String="") {
    Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween) {
        Text(label,fontSize=12.sp,color=Dim); Text(if(suffix=="倍") "%.2f倍".format(value) else "${value.toInt()}$suffix",fontSize=12.sp,color=Mint,fontFamily=FontFamily.Monospace)
    }
    Slider(value=value,onValueChange=onChange,valueRange=range,enabled=enabled,modifier=Modifier.height(37.dp))
}

@Composable private fun MidiPanel(model: DeckViewModel,status: DeviceStatus?,enabled: Boolean) {
    var channel by rememberSaveable { mutableIntStateOf(0) }
    var master by rememberSaveable { mutableFloatStateOf(89f) }
    var volume by rememberSaveable { mutableFloatStateOf(100f) }
    var pan by rememberSaveable { mutableFloatStateOf(64f) }
    var expression by rememberSaveable { mutableFloatStateOf(127f) }
    var program by rememberSaveable { mutableFloatStateOf(0f) }
    val live=enabled && status?.mode==2
    Column(verticalArrangement=Arrangement.spacedBy(18.dp)) {
        Column { Caption("PLAY THE HARDWARE",Lilac); Text("指先から、8ボイス。",fontSize=24.sp,fontWeight=FontWeight.Bold,color=Ink) }
        Tile {
            Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween,verticalAlignment=Alignment.CenterVertically) {
                Caption("MIDI LIVE",Lilac)
                TextButton(onClick={channel=(channel+1)%16},enabled=enabled) { Text("CH ${"%02d".format(channel+1)}",fontFamily=FontFamily.Monospace) }
            }
            Text("${if(live) "鍵盤を押して演奏" else "MIDIモードに切り替えて演奏"}",color=Dim,fontSize=12.sp)
            Spacer(Modifier.height(15.dp)); Keyboard(model,live,channel)
            Spacer(Modifier.height(12.dp))
            Button(onClick=model::midiMode,enabled=enabled && status?.mode!=2,modifier=Modifier.fillMaxWidth(),shape=RoundedCornerShape(13.dp)) { Text(if(status?.mode==2) "MIDI LIVE 接続中" else "MIDIモードに切替") }
        }
        Tile {
            Caption("VOICE CONTROL",Lilac); Spacer(Modifier.height(17.dp))
            SliderRow("全体音量",master,0f..127f,enabled,{master=it})
            SliderRow("チャンネル音量",volume,0f..127f,enabled,{volume=it})
            SliderRow("パン · 左 0 / 中央 64 / 右 127",pan,0f..127f,enabled,{pan=it})
            SliderRow("Expression",expression,0f..127f,enabled,{expression=it})
            SliderRow("音色",program,0f..127f,enabled,{program=it})
            Button(onClick={model.parameters(master.toInt(),channel,volume.toInt(),pan.toInt(),program.toInt(),expression.toInt())},enabled=enabled && status?.mode in listOf(2,3),modifier=Modifier.fillMaxWidth(),shape=RoundedCornerShape(13.dp)) { Text("設定を反映") }
        }
    }
}

@Composable private fun Keyboard(model: DeckViewModel,enabled: Boolean,channel: Int) {
    val white=listOf(60,62,64,65,67,69,71,72)
    val labels=listOf("C4","D","E","F","G","A","B","C5")
    BoxWithConstraints(Modifier.fillMaxWidth().height(156.dp)) {
        val width=maxWidth/8
        Row(Modifier.fillMaxSize()) {
            white.forEachIndexed { index,note ->
                PianoKey(model,note,channel,enabled,false,labels[index],Modifier.width(width).fillMaxHeight().padding(1.dp))
            }
        }
        listOf(0 to 61,1 to 63,3 to 66,4 to 68,5 to 70).forEach { (after,note) ->
            PianoKey(model,note,channel,enabled,true,"",Modifier.offset(x=width*(after+1)-width*.29f).width(width*.58f).height(98.dp))
        }
    }
}
@Composable private fun PianoKey(model: DeckViewModel,note: Int,channel: Int,enabled: Boolean,black: Boolean,label: String,modifier: Modifier) {
    var pressed by remember { mutableStateOf(false) }
    Box(modifier.clip(RoundedCornerShape(bottomStart=5.dp,bottomEnd=5.dp)).background(if(pressed) Mint else if(black) Color(0xFF080C14) else Color(0xFFEAECE7))
        .border(1.dp,if(black) Line else Color(0xFFBCC5C8),RoundedCornerShape(bottomStart=5.dp,bottomEnd=5.dp))
        .semantics { contentDescription="MIDIノート $note" }
        .pointerInput(enabled,channel,note) {
            if(enabled) detectTapGestures(onPress={
                pressed=true; model.note(note,true,channel)
                try { tryAwaitRelease() } finally { pressed=false; model.note(note,false,channel) }
            })
        },contentAlignment=Alignment.BottomCenter) {
        if(label.isNotEmpty()) Text(label,color=if(pressed) Night else Color(0xFF566170),fontSize=9.sp,fontWeight=FontWeight.Bold,modifier=Modifier.padding(bottom=12.dp))
        if(!enabled) Box(Modifier.fillMaxSize().background(Night.copy(alpha=.24f)))
    }
}

@Composable private fun SettingsPanel(model: DeckViewModel,status: DeviceStatus?,link: LinkState,busy: Boolean) {
    val ampUi by model.ui.collectAsState()
    var ampLevel by rememberSaveable { mutableFloatStateOf(160f) }
    LaunchedEffect(ampUi.ampLevel) { ampLevel=ampUi.ampLevel.toFloat() }
    var gain by rememberSaveable { mutableFloatStateOf(1f) }
    LaunchedEffect(status?.gain) { status?.gain?.let { gain=it } }
    val enabled=link.ready && !busy
    Column(verticalArrangement=Arrangement.spacedBy(18.dp)) {
        Column { Caption("MAKE IT YOURS",Mint); Text("音源のセッティング",fontSize=24.sp,fontWeight=FontWeight.Bold,color=Ink) }
        Tile {
            Caption("OUTPUT / AMPLIFIER",Mint); Spacer(Modifier.height(12.dp))
            listOf("外付けアンプ / ジャック出力","TDA7053A / 基板の音量制御","TDA7053専用基板 / 固定ゲイン").forEachIndexed { profile,label ->
                Row(verticalAlignment=Alignment.CenterVertically,modifier=Modifier.fillMaxWidth()) {
                    RadioButton(selected=ampUi.ampProfile==profile,onClick={model.ampProfile(profile)},enabled=enabled && ampUi.ampSupported && !ampUi.playlistActive)
                    Text(label,fontSize=12.sp,color=Ink)
                }
            }
            if(ampUi.ampProfile==1) {
                SliderRow("アンプ音量",ampLevel,0f..255f,enabled,{ampLevel=it})
                Button(onClick={model.ampLevel(ampLevel.toInt())},enabled=enabled && ampUi.ampSupported) { Text("アンプ音量を反映") }
                Text("曲を再開せず音量を変更します。TDA7053AとDC音量回路が接続された出力で有効。",fontSize=11.sp,color=Dim)
            } else Text("現在の出力はアンプ音量・フェード制御に非対応。SPCの再生と再転送は利用できます。",fontSize=11.sp,color=Dim)
            if(!ampUi.ampSupported) Text("この設定にはESPの対応ファームが必要です。",fontSize=11.sp,color=Coral)
            Spacer(Modifier.height(12.dp))
            ToggleRow("切替前にフェードアウト","SPCのフェード時間タグを使用。指定なしは最後の2秒。",ampUi.fadeEnabled,
                !busy && ampUi.ampSupported && ampUi.ampProfile==1,model::playlistFade)
        }
        Tile {
            Caption("SPC / WAV VOLUME",Mint); Spacer(Modifier.height(17.dp))
            SliderRow("音量倍率",gain,0f..4f,enabled && status?.gainSupported==true,{gain=it},"倍")
            Text("変更すると曲の先頭から再開します。\n転送の進捗を表示。0倍はすぐに消音。",fontSize=12.sp,color=Dim,lineHeight=19.sp)
            Spacer(Modifier.height(12.dp))
            Button(onClick={model.gain(gain)},enabled=enabled && status?.gainSupported==true && status.mode in listOf(0,1),modifier=Modifier.fillMaxWidth(),shape=RoundedCornerShape(13.dp)) { Text("音量を反映・再生") }
            Text("元から最大音量の曲は増幅できません。曲側の音量更新で上書きされる場合があります。",fontSize=11.sp,color=Dim,modifier=Modifier.padding(top=10.dp),lineHeight=17.sp)
        }
        Tile {
            Caption("STANDALONE PLAYBACK",Lilac); Spacer(Modifier.height(12.dp))
            ToggleRow("電源投入時に再生","保存曲をPC・スマホなしで再生",status?.boot ?: true,enabled,model::boot)
            HorizontalDivider(color=Line,modifier=Modifier.padding(vertical=10.dp))
            ToggleRow("MIDIファイルをループ","曲の最後からもう一度",status?.loop ?: true,enabled,model::loop)
        }
        Tile {
            Caption("CONNECTED HARDWARE"); Spacer(Modifier.height(12.dp))
            Text(if(link.ready) "SHVC-SOUND Player" else "未接続",color=Ink,fontWeight=FontWeight.Bold)
            Text(status?.modeName ?: "ESP32 / SHVC-SOUND rev0.4",color=Dim,fontSize=12.sp,modifier=Modifier.padding(top=4.dp))
            Text("MIDI欠落 ${status?.dropped ?: 0}",color=Dim,fontSize=12.sp,modifier=Modifier.padding(top=8.dp))
            Row { TextButton(onClick=model::refresh,enabled=enabled) { Text("状態更新") }; TextButton(onClick=model::disconnect,enabled=enabled) { Text("切断",color=Coral) } }
        }
    }
}
@Composable private fun ToggleRow(title: String,detail: String,checked: Boolean,enabled: Boolean,change: (Boolean)->Unit) {
    Row(verticalAlignment=Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) { Text(title,color=Ink,fontSize=14.sp,fontWeight=FontWeight.SemiBold); Text(detail,color=Dim,fontSize=11.sp,modifier=Modifier.padding(top=4.dp)) }
        Switch(checked=checked,onCheckedChange=change,enabled=enabled)
    }
}


@Composable private fun PlaylistPanel(model: DeckViewModel,ui: DeckUi,connected: Boolean) {
    Tile {
        Caption("PLAYLIST",Mint)
        Text("連続再生",fontSize=20.sp,fontWeight=FontWeight.Bold,color=Ink)
        Text("スマホを接続したまま曲順に再生。曲間に転送時間が入ります。",color=Dim,fontSize=11.sp)
        if(ui.playlistActive) Text("${ui.playlistIndex+1} / ${ui.playlist.size} 曲 · 残り ${ui.remainingSeconds} 秒",color=Mint)
        Row(horizontalArrangement=Arrangement.spacedBy(8.dp)) {
            TextButton(onClick=model::enqueueSelected,enabled=!ui.busy && !ui.playlistActive && ui.selected!=null) { Text("選択曲を追加") }
            if(ui.playlistActive) TextButton(onClick=model::stopPlaylist) { Text("停止") }
            else TextButton(onClick=model::startPlaylist,enabled=connected && !ui.busy && ui.playlist.isNotEmpty()) { Text("連続再生") }
        }
        ui.playlist.forEachIndexed { index,uri ->
            Row(verticalAlignment=Alignment.CenterVertically) {
                Text("${index+1}. ${ui.library.firstOrNull { it.uri==uri }?.name ?: "不明"}",modifier=Modifier.weight(1f),
                    color=if(ui.playlistActive && index==ui.playlistIndex) Mint else Ink,fontSize=12.sp,maxLines=1)
                TextButton(onClick={ model.moveQueue(index,-1) },enabled=!ui.playlistActive && index>0) { Text("↑") }
                TextButton(onClick={ model.moveQueue(index,1) },enabled=!ui.playlistActive && index<ui.playlist.lastIndex) { Text("↓") }
                TextButton(onClick={ model.removeQueue(index) },enabled=!ui.playlistActive) { Text("×") }
            }
        }
        Row(verticalAlignment=Alignment.CenterVertically) {
            Text("曲の時間タグを使う",color=Dim,fontSize=12.sp,modifier=Modifier.weight(1f))
            Switch(checked=ui.useTimeTags,onCheckedChange={ model.playlistSettings(ui.fallbackSeconds,it,ui.playlistRepeat) })
        }
        Text("タグなしの曲 / 手動指定: ${ui.fallbackSeconds} 秒",color=Dim,fontSize=12.sp)
        Slider(value=ui.fallbackSeconds.toFloat().coerceIn(10f,600f),onValueChange={ model.playlistSettings(it.toInt(),ui.useTimeTags,ui.playlistRepeat) },valueRange=10f..600f)
        Row(verticalAlignment=Alignment.CenterVertically) {
            Text("再生リストを繰り返す",color=Dim,fontSize=12.sp,modifier=Modifier.weight(1f))
            Switch(checked=ui.playlistRepeat,onCheckedChange={ model.playlistSettings(ui.fallbackSeconds,ui.useTimeTags,it) })
        }
    }
}
