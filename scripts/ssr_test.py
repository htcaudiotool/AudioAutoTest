from com.dtmilano.android.viewclient import ViewClient
import os
import subprocess
import time
import datetime

import sys
sys.path.append(os.path.dirname(os.path.realpath(__file__)) + "/../")

from libs import ROOT_DIR, SEP, STDNUL
from libs.adbutils import Adb
from libs.audiofunction import AudioFunction, ToneDetector, DetectionStateListener
from libs.logger import Logger
from libs.aatapp import AATApp
from libs.trials import Trial, TrialHelper

TAG = "ssr_test.py"

DEVICE_MUSIC_DIR = "sdcard/Music/"
OUT_FREQ = 440
BATCH_SIZE = 5
PARTIAL_RAMDUMP_ENABLED = False

FILE_NAMES = [
    "440Hz_wav.wav",
    "440Hz_mp3.mp3"
]

def push_files(serialno):
    for file_to_pushed in FILE_NAMES:
        out, _ = subprocess.Popen(["find", ROOT_DIR, "-name", file_to_pushed], stdout=subprocess.PIPE).communicate()
        file_path = out.splitlines()[0] if out else None
        if file_path:
            os.system("adb -s {} push {} {} > {}".format(serialno, file_path, DEVICE_MUSIC_DIR, STDNUL))
        else:
            raise ValueError("Cannot find the file \"{}\", please place it under the project tree.".format(file_to_pushed))

def log(msg):
    Logger.log(TAG, msg)

import StringIO as sio
def wake_device(device, serialno):
    if device.isScreenOn():
        return

    device.wake()
    vc = ViewClient(device, serialno, autodump=False)
    try:
        vc.dump(sleep=0)
        so = sio.StringIO()
        vc.traverse(stream=so)

        if "lockscreen" in so.getvalue():
            device.unlock()
    except:
        pass

def handle_ssr_ui():
    elapsed = SSRDumpListener.wait_for_dialog(timeout=60)
    log("SSR dialog shows: {} (elapsed {} ms)".format(SSRDumpListener.WORK_THREAD.state, elapsed))
    if elapsed > 0:
        SSRDumpListener.dismiss_dialog()
        log("dismiss SSR dialog")

def run(num_iter=1):
    AudioFunction.init()
    Logger.init(Logger.Mode.BOTH_FILE_AND_STDOUT)
    Adb.init()

    os.system("mkdir -p {}{}ssr_report > {}".format(ROOT_DIR, SEP, STDNUL))
    t = datetime.datetime.now()
    filename = "report_{}{:02d}{:02d}_{:02d}{:02d}{:02d}.json".format(t.year, t.month, t.day, t.hour, t.minute, t.second)

    device, serialno = ViewClient.connectToDeviceOrExit(serialno=None)
    push_files(serialno)
    wake_device(device, serialno)
    SSRDumpListener.init(device, serialno)

    # keymap reference:
    #   https://github.com/dtmilano/AndroidViewClient/blob/master/src/com/dtmilano/android/adb/androidkeymap.py
    device.press("HOME")
    time.sleep(1)
    AATApp.launch_app(device)
    time.sleep(1)

    trials = []
    batch_count = 1
    while num_iter > 0:
        log("-------- batch_run #{} --------".format(batch_count))
        AATApp.print_log(device, severity="i", tag=TAG, log="-------- batch_run #{} --------".format(batch_count))
        trials_batch = []
        trials_batch += playback_task_run(device, num_iter=min([num_iter, BATCH_SIZE]))
        trials_batch += record_task_run(device, serialno, num_iter=min([num_iter, BATCH_SIZE]))
        trials_batch += voip_task_run(device, serialno, num_iter=min([num_iter, BATCH_SIZE]))

        map(lambda trial: trial.put_extra(name="batch_id", value=batch_count), trials_batch)
        trials += trials_batch
        with open("{}{}ssr_report{}{}".format(ROOT_DIR, SEP, SEP, filename), "w") as f:
            f.write(TrialHelper.to_json(trials))

        for taskname, tasktrials in TrialHelper.categorize_in(trials, lambda t: t.ds["task"]).items():
            valid_trials = zip(tasktrials, TrialHelper.pass_fail_list(tasktrials, lambda t: t.ds["status"] == "valid"))
            valid_trials = [trial for trial, isvalid in valid_trials if isvalid]
            num_valid = len(valid_trials)
            num_pass = len(filter(lambda x: x, TrialHelper.pass_fail_list(valid_trials)))
            log("task[{}] valid trials: {}/{}, pass trials: {}/{}".format(taskname, num_valid, len(tasktrials), num_pass, num_valid))

        num_iter -= BATCH_SIZE
        batch_count += 1

    AudioFunction.finalize()
    Logger.finalize()
    SSRDumpListener.finalize()


def playback_task_run(device, num_iter=1):
    log("playback_task_run++")

    trials = []

    stm = DetectionStateListener()

    log("ToneDetector.start_listen(target_freq={})".format(OUT_FREQ))
    ToneDetector.start_listen(target_freq=OUT_FREQ, cb=lambda event: stm.tone_detected_event_cb(event))

    funcs = {
        "nonoffload": AATApp.playback_nonoffload,
        "offload"   : AATApp.playback_offload
    }

    files = {
        "nonoffload": "440Hz_wav.wav",
        "offload"   : "440Hz_mp3.mp3"
    }

    for i in range(num_iter):
        log("-------- playback_task #{} --------".format(i+1))
        for name, func in funcs.items():
            trial = Trial(taskname="playback_{}".format(name), pass_check=lambda t: t.ds["extra"]["elapsed"] > 0)
            trial.put_extra(name="iter_id", value=i+1)

            AATApp.print_log(device, severity="i", tag=TAG, log="playback_{}_task #{}".format(name, i+1))

            log("dev_playback_{}_start".format(name))
            time.sleep(1)
            stm.reset()
            log("reset DetectionStateChangeListener")
            func(device, filename=files[name])

            if stm.wait_for_event(DetectionStateListener.Event.ACTIVE, timeout=5) < 0:
                log("the tone was not detected, abort the iteration this time...")
                AATApp.playback_stop(device)
                trial.invalidate(errormsg="early return, possible reason: rx no sound")
                trials.append(trial)
                continue
            time.sleep(1)

            log("trigger_ssr()")
            AATApp.trigger_ssr(device)

            if PARTIAL_RAMDUMP_ENABLED:
                handle_ssr_ui()

            log("Waiting for SSR recovery")
            elapsed = stm.wait_for_event(DetectionStateListener.Event.RISING_EDGE, timeout=10)
            log("elapsed: {} ms".format(elapsed))

            if PARTIAL_RAMDUMP_ENABLED:
                log("Waiting for the partial ramdump completed")
                handle_ssr_ui()

            if elapsed >= 0 and not PARTIAL_RAMDUMP_ENABLED:
                time.sleep(10 - elapsed/1000.0)

            trial.put_extra(name="elapsed", value=elapsed)
            trials.append(trial)

            log("dev_playback_stop")
            AATApp.playback_stop(device)
            stm.wait_for_event(DetectionStateListener.Event.INACTIVE, timeout=5)

    log("-------- playback_task done --------")
    log("ToneDetector.stop_listen()")
    ToneDetector.stop_listen()

    log("playback_task_run--")
    return trials

def record_task_run(device, serialno, num_iter=1):
    log("record_task_run++")

    trials = []

    log("dev_record_start")
    AATApp.record_start(device)
    time.sleep(2)

    stm = DetectionStateListener()

    log("ToneDetector.start_listen(serialno={}, target_freq={})".format(serialno, OUT_FREQ))
    ToneDetector.start_listen(serialno=serialno, target_freq=OUT_FREQ, cb=lambda event: stm.tone_detected_event_cb(event))
    log("AudioFunction.play_sound(out_freq={})".format(OUT_FREQ))
    AudioFunction.play_sound(out_freq=OUT_FREQ)

    time.sleep(3)
    for i in range(num_iter):
        log("-------- record_task #{} --------".format(i+1))

        trial = Trial(taskname="record", pass_check=lambda t: t.ds["extra"]["elapsed"] > 0)
        trial.put_extra(name="iter_id", value=i+1)

        AATApp.print_log(device, severity="i", tag=TAG, log="record_task #{}".format(i+1))

        ToneDetector.WORK_THREAD.clear_dump()
        stm.reset()
        if stm.wait_for_event(DetectionStateListener.Event.ACTIVE, timeout=5) < 0:
            log("the tone was not detected, abort the iteration this time...")
            log("ToneDetectorForDeviceThread.adb-read-prop-max-elapsed: {} ms".format( \
                ToneDetector.WORK_THREAD.extra["adb-read-prop-max-elapsed"]))
            log("ToneDetectorForDeviceThread.freq-cb-max-elapsed: {} ms".format( \
                ToneDetector.WORK_THREAD.extra["freq-cb-max-elapsed"]))
            trial.invalidate(errormsg="early return, possible reason: tx no sound")
            trials.append(trial)

            now = "_".join("{}".format(datetime.datetime.now()).split())
            log("dump the recorded pcm to \"sdcard/PyAAT/dump_{}\"".format(now))
            AATApp.record_dump(device, "sdcard/PyAAT/dump_{}".format(now))
            continue

        log("trigger_ssr()")
        AATApp.trigger_ssr(device)

        if PARTIAL_RAMDUMP_ENABLED:
            handle_ssr_ui()

        log("Waiting for SSR recovery")
        elapsed = stm.wait_for_event(DetectionStateListener.Event.RISING_EDGE, timeout=10)
        if elapsed < 0:
            log("Timeout in waiting for rising event, possibly caused by missing event not being caught")
            log("Waiting for the tone being detected")
            if stm.wait_for_event(DetectionStateListener.Event.ACTIVE, timeout=5) < 0:
                log("The tone is not detected")
            else:
                log("The tone is detected, please also check the device log for confirming if it is a false alarm")

            log("start dumping the process during capturing the frequency...")
            ToneDetector.WORK_THREAD.dump()

        log("elapsed: {} ms".format(elapsed))

        if elapsed < 0:
            now = "_".join("{}".format(datetime.datetime.now()).split())
            log("dump the recorded pcm to \"sdcard/PyAAT/dump_{}\"".format(now))
            AATApp.record_dump(device, "sdcard/PyAAT/dump_{}".format(now))

        log("ToneDetectorForDeviceThread.adb-read-prop-max-elapsed: {} ms".format( \
            ToneDetector.WORK_THREAD.extra["adb-read-prop-max-elapsed"]))
        log("ToneDetectorForDeviceThread.freq-cb-max-elapsed: {} ms".format( \
            ToneDetector.WORK_THREAD.extra["freq-cb-max-elapsed"]))

        if PARTIAL_RAMDUMP_ENABLED:
            log("Waiting for the partial ramdump completed")
            handle_ssr_ui()

        if elapsed >= 0 and not PARTIAL_RAMDUMP_ENABLED:
            time.sleep(10 - elapsed/1000.0)

        trial.put_extra(name="elapsed", value=elapsed)
        trials.append(trial)

    log("-------- record_task done --------")
    log("AudioFunction.stop_audio()")
    AudioFunction.stop_audio()

    log("dev_record_stop")
    AATApp.record_stop(device)
    time.sleep(5)
    log("ToneDetector.stop_listen()")
    ToneDetector.stop_listen()

    log("record_task_run--")
    return trials

def voip_task_run(device, serialno, num_iter=1):
    log("voip_task_run++")

    trials = []

    # AATApp.voip_use_speaker(device)
    time.sleep(2)

    stm = DetectionStateListener()

    log("ToneDetector.start_listen(target_freq={})".format(serialno, OUT_FREQ))
    ToneDetector.start_listen(target_freq=OUT_FREQ, cb=lambda event: stm.tone_detected_event_cb(event))

    AATApp.voip_start(device)
    for i in range(num_iter):
        log("-------- dev_voip_rx_task #{} --------".format(i+1))

        trial = Trial(taskname="voip_rx", pass_check=lambda t: t.ds["extra"]["elapsed"] > 0)
        trial.put_extra(name="iter_id", value=i+1)

        AATApp.print_log(device, severity="i", tag=TAG, log="voip_rx_task #{}".format(i+1))

        time.sleep(1)
        stm.reset()

        if stm.wait_for_event(DetectionStateListener.Event.ACTIVE, timeout=5) < 0:
            log("the tone was not detected, abort the iteration this time...")
            trial.invalidate(errormsg="early return, possible reason: rx no sound")
            trials.append(trial)
            continue
        time.sleep(1)

        log("trigger_ssr()")
        AATApp.trigger_ssr(device)

        if PARTIAL_RAMDUMP_ENABLED:
            handle_ssr_ui()

        log("Waiting for SSR recovery")
        elapsed = stm.wait_for_event(DetectionStateListener.Event.RISING_EDGE, timeout=10)
        log("elapsed: {} ms".format(elapsed))

        if PARTIAL_RAMDUMP_ENABLED:
            log("Waiting for the partial ramdump completed")
            handle_ssr_ui()

        if elapsed >= 0 and not PARTIAL_RAMDUMP_ENABLED:
            time.sleep(10 - elapsed/1000.0)

        trial.put_extra(name="elapsed", value=elapsed)
        trials.append(trial)

    log("-------- dev_voip_rx_task done --------")
    log("ToneDetector.stop_listen()")
    ToneDetector.stop_listen()

    stm = DetectionStateListener()

    time.sleep(2)
    AATApp.voip_mute_output(device)
    time.sleep(10)
    log("ToneDetector.start_listen(serialno={}, target_freq={})".format(serialno, None))
    ToneDetector.start_listen(serialno=serialno, target_freq=None, cb=lambda event: stm.tone_detected_event_cb(event))

    for i in range(num_iter):
        log("-------- dev_voip_tx_task #{} --------".format(i+1))

        trial = Trial(taskname="voip_tx", pass_check=lambda t: t.ds["extra"]["elapsed"] > 0)
        trial.put_extra(name="iter_id", value=i+1)

        AATApp.print_log(device, severity="i", tag=TAG, log="voip_tx_task #{}".format(i+1))

        time.sleep(2)

        log("AudioFunction.play_sound(out_freq={})".format(OUT_FREQ))
        AudioFunction.play_sound(out_freq=OUT_FREQ)

        stm.reset()
        if stm.wait_for_event(DetectionStateListener.Event.ACTIVE, timeout=5) < 0:
            log("the tone was not detected, abort the iteration this time...")
            trial.invalidate(errormsg="early return, possible reason: tx no sound")
            trials.append(trial)
            continue
        time.sleep(2)

        log("trigger_ssr()")
        AATApp.trigger_ssr(device)

        if PARTIAL_RAMDUMP_ENABLED:
            handle_ssr_ui()

        log("Waiting for SSR recovery")
        elapsed = stm.wait_for_event(DetectionStateListener.Event.RISING_EDGE, timeout=10)
        log("elapsed: {} ms".format(elapsed))

        if PARTIAL_RAMDUMP_ENABLED:
            log("Waiting for the partial ramdump completed")
            handle_ssr_ui()

        if elapsed >= 0 and not PARTIAL_RAMDUMP_ENABLED:
            time.sleep(10 - elapsed/1000.0)

        trial.put_extra(name="elapsed", value=elapsed)
        trials.append(trial)

        log("AudioFunction.stop_audio()")
        AudioFunction.stop_audio()

    log("-------- dev_voip_tx_task done --------")
    log("dev_voip_stop")
    AATApp.voip_stop(device)
    time.sleep(5)
    log("ToneDetector.stop_listen()")
    ToneDetector.stop_listen()

    log("voip_task_run--")
    return trials


import threading, re
class SSRDumpListener(object):
    WORK_THREAD = None
    PERIOD = 0.5
    FILTER = "com.htc.android.ssdtest/com.htc.android.ssdtest.DialogShower"
    MSG_VIEW_ID = "android:id/message"
    BTN_ID = "android:id/button2"
    RAMDUMP_COMPLETED_KEYMSG = "Dump RAM logs completely"

    class SSRDumpListenerThread(threading.Thread):
        class State(object):
            IDLE = "idle"
            BEING_DUMPED = "being dumped"
            DUMPED = "has been dumped"

        def __init__(self, device, serialno):
            super(SSRDumpListener.SSRDumpListenerThread, self).__init__()
            self.daemon = True
            self.stoprequest = threading.Event()
            self.lock = threading.Lock()
            self.device = device
            self.serialno = serialno
            self.vc = ViewClient(device, serialno, autodump=False)
            self.state = SSRDumpListener.SSRDumpListenerThread.State.IDLE

        def join(self, timeout=None):
            self.stoprequest.set()
            super(SSRDumpListener.SSRDumpListenerThread, self).join(timeout)

        def run(self):
            import platform
            if platform.system() == "Windows":
                cmdformat = "powershell.exe \"adb -s {} shell dumpsys window | select-string -pattern \"Window #\""
            else:
                cmdformat = "adb -s {} shell dumpsys window | grep \"Window #\""
            pattern = re.compile("Window{.+?}")
            while not self.stoprequest.isSet():
                try:
                    win_dumpsys, _ = subprocess.Popen(cmdformat.format(self.serialno), \
                        shell=True, stdout=subprocess.PIPE).communicate()

                    win_info_strs = map(lambda s: pattern.search(s.strip()).group(0), win_dumpsys.splitlines())
                    win_info_strs = [s[7:-1] for s in win_info_strs if len(s) > 7]
                    self.win_info = dict( [(ss[2], ss[0]) for ss in map(lambda s: s.split(), win_info_strs)] )
                    if SSRDumpListener.FILTER in self.win_info.keys():
                        self.vc.dump(window=self.win_info[SSRDumpListener.FILTER], sleep=0)
                        views = dict( [(v.getId(), v) for v in self.vc.getViewsById().values() if len(v.getId()) > 0] )

                        if SSRDumpListener.MSG_VIEW_ID in views.keys():
                            msg = views[SSRDumpListener.MSG_VIEW_ID].getText()

                            if SSRDumpListener.RAMDUMP_COMPLETED_KEYMSG in msg:
                                self.state = SSRDumpListener.SSRDumpListenerThread.State.DUMPED
                            else:
                                self.state = SSRDumpListener.SSRDumpListenerThread.State.BEING_DUMPED

                    else:
                        self.state = SSRDumpListener.SSRDumpListenerThread.State.IDLE

                except:
                    pass
                time.sleep(SSRDumpListener.PERIOD)

        def dismiss_dialog(self):
            if self.state == SSRDumpListener.SSRDumpListenerThread.State.IDLE:
                return

            self.vc.dump(window=self.win_info[SSRDumpListener.FILTER], sleep=0)
            views = dict( [(v.getId(), v) for v in self.vc.getViewsById().values() if len(v.getId()) > 0] )

            if SSRDumpListener.BTN_ID in views.keys():
                x, y = views[SSRDumpListener.BTN_ID].getCenter()
                self.device.touch(x, y)

            self.state = SSRDumpListener.SSRDumpListenerThread.State.IDLE

    @staticmethod
    def init(device, serialno):
        if not PARTIAL_RAMDUMP_ENABLED:
            return

        SSRDumpListener.WORK_THREAD = SSRDumpListener.SSRDumpListenerThread(device, serialno)
        SSRDumpListener.WORK_THREAD.start()

    @staticmethod
    def wait_for_dialog(timeout=-1):
        if not PARTIAL_RAMDUMP_ENABLED:
            return

        cnt = 0
        while SSRDumpListener.WORK_THREAD.state == SSRDumpListener.SSRDumpListenerThread.State.IDLE:
            cnt += 1
            if timeout > 0 and cnt >= timeout * 10.0:
                return -1
            time.sleep(0.1)

        return cnt * 100.0

    @staticmethod
    def dismiss_dialog():
        if not PARTIAL_RAMDUMP_ENABLED:
            return

        SSRDumpListener.WORK_THREAD.dismiss_dialog()

    @staticmethod
    def finalize():
        if not PARTIAL_RAMDUMP_ENABLED:
            return

        SSRDumpListener.WORK_THREAD.join()

if __name__ == "__main__":
    num_iter = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    # ViewClient tries to access the system arguments, then it might cause RuntimeError
    if len(sys.argv) > 1: del sys.argv[1:]
    try:
        run(num_iter=num_iter)
    except Exception as e:
        print(e)
