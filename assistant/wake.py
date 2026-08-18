import time

import numpy as np
import sounddevice as sd
from openwakeword.model import Model

SAMPLE_RATE = 16000
CHUNK = 1280


def listen(
    wake_threshold: float,
    confirm_window: float,
    on_wake,
    cooldown: float = 10.0,
) -> None:
    model = Model(wakeword_models=["hey jarvis"])
    key = "hey jarvis"
    last_hit = 0.0
    recording = {"active": False, "buffers": [], "started": 0.0}

    def callback(indata, frames, time_info, status):
        audio = np.squeeze(indata).copy()
        now = time.monotonic()
        if recording["active"]:
            recording["buffers"].append(audio)
            if now - recording["started"] >= confirm_window:
                clip = np.concatenate(recording["buffers"])
                recording["active"] = False
                recording["buffers"] = []
                print("wake: captured confirmation clip", flush=True)
                on_wake(clip)
            return
        scores = model.predict(audio)
        score = float(scores.get(key, 0.0))
        if score > wake_threshold and now - last_hit > cooldown:
            last_hit = now
            print(f"wake: '{key}' detected (score={score:.2f})", flush=True)
            recording["active"] = True
            recording["started"] = now
            recording["buffers"] = [audio]

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16",
        blocksize=CHUNK,
        callback=callback,
    ):
        print("wake: listening for 'hey jarvis'", flush=True)
        while True:
            sd.sleep(1000)