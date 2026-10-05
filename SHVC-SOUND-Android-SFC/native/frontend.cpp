#include <jni.h>
#include <android/native_window_jni.h>
#include <android/log.h>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <mutex>
#include <thread>
#include <vector>
#include "libretro.h"

extern "C" unsigned shvc_debug(unsigned);
static std::thread worker;
static std::atomic<bool> running(false);
static std::atomic<unsigned> buttons(0), frames(0), packets(0);
static std::atomic<double> fps(0);
static std::mutex controlMutex, windowMutex, statusMutex;
static ANativeWindow *window=nullptr;
static std::mutex frameMutex;
static std::condition_variable frameReady;
static std::vector<uint16_t> image;
static unsigned imageWidth=0,imageHeight=0;
static uint64_t imageSequence=0;
static std::string directory, status="ROMとESPのIPを指定して開始";
static unsigned pixelFormat=RETRO_PIXEL_FORMAT_0RGB1555;
static void state(const std::string &s) { std::lock_guard<std::mutex> lock(statusMutex);status=s;__android_log_print(ANDROID_LOG_INFO,"SHVC-SFC","%s",s.c_str()); }
static bool environment(unsigned cmd,void *data) {
    switch(cmd) {
        case RETRO_ENVIRONMENT_GET_SYSTEM_DIRECTORY:
        case RETRO_ENVIRONMENT_GET_SAVE_DIRECTORY: *(const char **)data=directory.c_str();return true;
        case RETRO_ENVIRONMENT_SET_PIXEL_FORMAT: pixelFormat=*(unsigned *)data;return pixelFormat==0 || pixelFormat==2;
        case RETRO_ENVIRONMENT_GET_VARIABLE_UPDATE: *(bool *)data=false;return true;
        case RETRO_ENVIRONMENT_GET_INPUT_BITMASKS: return true;
        case RETRO_ENVIRONMENT_SET_VARIABLES:
        case RETRO_ENVIRONMENT_SET_INPUT_DESCRIPTORS:
        case RETRO_ENVIRONMENT_SET_CONTROLLER_INFO:
        case RETRO_ENVIRONMENT_SET_MEMORY_MAPS:
        case RETRO_ENVIRONMENT_SET_SUPPORT_ACHIEVEMENTS: return true;
        case RETRO_ENVIRONMENT_SHUTDOWN: running=false;return true;
        default:return false;
    }
}
static void video(const void *data,unsigned width,unsigned height,size_t pitch) {
    if(!data)return;
    {
        std::lock_guard<std::mutex> lock(frameMutex);image.resize(width*height);
        for(unsigned y=0;y<height;y++) {
            auto src=(const uint16_t *)((const char *)data+y*pitch);
            auto dst=image.data()+y*width;
            if(pixelFormat==2)std::memcpy(dst,src,width*2);
            else for(unsigned x=0;x<width;x++)dst[x]=((src[x]&0x7fe0)<<1)|(src[x]&31);
        }
        imageWidth=width;imageHeight=height;++imageSequence;
    }
    frameReady.notify_one();
}
static void render() {
    uint64_t seen=0;std::vector<uint16_t> pixels;
    while(running) {
        unsigned width,height;
        {
            std::unique_lock<std::mutex> lock(frameMutex);
            frameReady.wait(lock,[&]{return !running || imageSequence!=seen;});
            if(!running)break;
            seen=imageSequence;pixels=image;width=imageWidth;height=imageHeight;
        }
    std::lock_guard<std::mutex> lock(windowMutex);
    if(!window)continue;
    if(ANativeWindow_getWidth(window)!=(int)width || ANativeWindow_getHeight(window)!=(int)height)
        ANativeWindow_setBuffersGeometry(window,width,height,WINDOW_FORMAT_RGB_565);
    ANativeWindow_Buffer target;
    if(ANativeWindow_lock(window,&target,nullptr))continue;
    for(unsigned y=0;y<height;y++) {
        auto dst=(uint16_t *)target.bits+y*target.stride;
        std::memcpy(dst,pixels.data()+y*width,width*2);
    }
    ANativeWindow_unlockAndPost(window);
    }
}
static void audio(int16_t,int16_t){}
static size_t audioBatch(const int16_t *,size_t count){return count;}
static void poll(){}
static int16_t input(unsigned port,unsigned device,unsigned,unsigned id) {
    if(port || device!=RETRO_DEVICE_JOYPAD)return 0;
    unsigned mask=buttons.load();return id==RETRO_DEVICE_ID_JOYPAD_MASK?(int16_t)mask:(id<16 && (mask&(1u<<id))?1:0);
}
static void stop() {
    running=false;
    if(worker.joinable())worker.join();
    buttons=0;
}
static std::string utf(JNIEnv *env,jstring value) { const char *p=env->GetStringUTFChars(value,nullptr);std::string s(p);env->ReleaseStringUTFChars(value,p);return s; }
extern "C" JNIEXPORT void JNICALL Java_com_shvc_sfclive_MainActivity_nativeStart(JNIEnv *env,jobject,jstring romValue,jstring hostValue,jstring dirValue) {
    std::lock_guard<std::mutex> lock(controlMutex);stop();
    std::string rom=utf(env,romValue),host=utf(env,hostValue);directory=utf(env,dirValue);
    setenv("SHVC_APU_PORT",host.c_str(),1);setenv("SHVC_APU_LOG",(directory+"/core.log").c_str(),1);
    running=true;frames=0;packets=0;fps=0;state("SHVCへ接続中…");
    worker=std::thread([rom] {
        std::ifstream file(rom,std::ios::binary);
        std::vector<char> bytes((std::istreambuf_iterator<char>(file)),std::istreambuf_iterator<char>());
        if(bytes.empty()){state("ROMの読み込みに失敗");running=false;return;}
        retro_set_environment(environment);retro_set_video_refresh(video);retro_set_audio_sample(audio);retro_set_audio_sample_batch(audioBatch);retro_set_input_poll(poll);retro_set_input_state(input);retro_init();
        retro_game_info info={rom.c_str(),bytes.data(),bytes.size(),nullptr};
        if(!retro_load_game(&info)){state("ROMを起動できない");retro_deinit();running=false;return;}
        retro_set_controller_port_device(0,RETRO_DEVICE_JOYPAD);
        retro_system_av_info av;retro_get_system_av_info(&av);
        using Clock=std::chrono::steady_clock;
        const auto period=std::chrono::duration_cast<Clock::duration>(std::chrono::duration<double>(1/av.timing.fps));
        auto next=Clock::now(),measure=next;unsigned measured=0;
        std::thread renderer(render);
        state("実音源で実行中");bool failed=false;
        while(running) {
            retro_run();
            if(shvc_debug(7)){failed=true;state("SHVC通信失敗。停止してから再開してください");break;}
            ++frames;++measured;packets=shvc_debug(5);
            auto now=Clock::now();double elapsed=std::chrono::duration<double>(now-measure).count();
            if(elapsed>=2){fps=measured/elapsed;measure=now;measured=0;}
            next+=period;
            if(next<now-period*3)next=now;
            std::this_thread::sleep_until(next);
        }
        running=false;frameReady.notify_one();renderer.join();
        retro_unload_game();retro_deinit();running=false;
        if(!failed)state("停止済み — SHVCへ停止信号を送信");
    });
}
extern "C" JNIEXPORT void JNICALL Java_com_shvc_sfclive_MainActivity_nativeStop(JNIEnv *,jobject) {std::lock_guard<std::mutex> lock(controlMutex);stop();}
extern "C" JNIEXPORT void JNICALL Java_com_shvc_sfclive_MainActivity_nativeButton(JNIEnv *,jobject,jint id,jboolean down) {if(id<0 || id>15)return;if(down)buttons.fetch_or(1u<<id);else buttons.fetch_and(~(1u<<id));}
extern "C" JNIEXPORT void JNICALL Java_com_shvc_sfclive_MainActivity_nativeSurface(JNIEnv *env,jobject,jobject surface) {
    std::lock_guard<std::mutex> lock(windowMutex);if(window)ANativeWindow_release(window);window=surface?ANativeWindow_fromSurface(env,surface):nullptr;
}
extern "C" JNIEXPORT jstring JNICALL Java_com_shvc_sfclive_MainActivity_nativeStatus(JNIEnv *env,jobject) {
    std::lock_guard<std::mutex> lock(statusMutex);char tail[160];std::snprintf(tail,sizeof(tail),"  | %.1f fps  | %u frames  | %u ACK packets",fps.load(),frames.load(),packets.load());return env->NewStringUTF((status+tail).c_str());
}
