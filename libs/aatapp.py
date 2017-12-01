class AATApp(object):
    INTENT_PREFIX = "am broadcast -a"
    HTC_INTENT_PREFIX = "audio.htc.com.intent."

    @staticmethod
    def trigger_ssr(device):
        device.shell("asound -crashdsp")

    @staticmethod
    def playback_nonoffload(device, filename="440Hz.wav"):
        cmd = " ".join([AATApp.INTENT_PREFIX, AATApp.HTC_INTENT_PREFIX + "playback.nonoffload", "--es", "file", filename])
        device.shell(cmd)

    @staticmethod
    def playback_offload(device, filename="440Hz.mp3"):
        cmd = " ".join([AATApp.INTENT_PREFIX, AATApp.HTC_INTENT_PREFIX + "playback.offload", "--es", "file", filename])
        device.shell(cmd)

    @staticmethod
    def playback_stop(device):
        cmd = " ".join([AATApp.INTENT_PREFIX, AATApp.HTC_INTENT_PREFIX + "playback.stop"])
        device.shell(cmd)

    @staticmethod
    def record_start(device):
        cmd = " ".join([AATApp.INTENT_PREFIX, AATApp.HTC_INTENT_PREFIX + "record.start", "--ei", "spt_xmax", "1000"])
        device.shell(cmd)

    @staticmethod
    def record_stop(device):
        cmd = " ".join([AATApp.INTENT_PREFIX, AATApp.HTC_INTENT_PREFIX + "record.stop"])
        device.shell(cmd)

    @staticmethod
    def voip_start(device):
        cmd = " ".join([AATApp.INTENT_PREFIX, AATApp.HTC_INTENT_PREFIX + "voip.start", "--ei", "spt_xmax", "1000"])
        device.shell(cmd)

    @staticmethod
    def voip_stop(device):
        cmd = " ".join([AATApp.INTENT_PREFIX, AATApp.HTC_INTENT_PREFIX + "voip.stop"])
        device.shell(cmd)

    @staticmethod
    def voip_use_speaker(device, use=True):
        cmd = " ".join([AATApp.INTENT_PREFIX, AATApp.HTC_INTENT_PREFIX + "voip.switch.speaker", "--ez", "use", str(1 if use else 0)])
        device.shell(cmd)

    @staticmethod
    def voip_use_receiver(device):
        AATApp.voip_use_speaker(device, use=False)

    @staticmethod
    def voip_mute_output(device):
        cmd = " ".join([AATApp.INTENT_PREFIX, AATApp.HTC_INTENT_PREFIX + "voip.mute.output"])
        device.shell(cmd)