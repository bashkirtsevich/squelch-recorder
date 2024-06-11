import argparse
import io
import math
import typing
import wave
from contextlib import suppress
from datetime import datetime

import pyaudio
import webrtcvad


def dB_to_percent(dB: float) -> float:
    return math.pow(10, dB / 20)


def bytes_to_float(bytes: bytearray) -> float:
    return float(int.from_bytes(bytes, "little", signed=True) / (1 << 15))


def frame_to_wave(frame: bytearray) -> typing.List[float]:
    return [
        bytes_to_float(frame[i:i + 2])
        for i in range(0, len(frame) // 2, 2)
    ]


def squelch(frame: bytearray, threshold: float) -> bool:
    wave = frame_to_wave(frame)
    return max(wave) >= threshold


def log_print(x: typing.Any) -> None:
    print(datetime.now().strftime("[%Y-%m-%d %H:%M:%S]"), x)


def record(
        file_out: io.BufferedWriter,
        rate: int = 8000,
        format=pyaudio.paInt16,
        channels: int = 1,
        frame_duration: int = 30,
        sql_duration: int = 300,
        sql_threshold_db: int = -120,
        vad_level: int = 3,
        use_vad: bool = True,
        input_device_index: int = 0
) -> None:
    sql_threshold_db = min(sql_threshold_db, 0)
    chunk_size = channels * rate * frame_duration // 1000
    sql_threshold = dB_to_percent(sql_threshold_db)

    print(f"File out: {file_out.name}\n"
          f"Rate: {rate}\n"
          f"Channels: {channels}\n"
          f"Frame duration: {frame_duration}ms\n"
          f"SQL duration: {sql_duration}\n"
          f"SQL threshold dB: {sql_threshold_db} ({(sql_threshold * 100):.3f}%)\n"
          f"Chunk size: {chunk_size}b\n\n"
          f"Recording...")

    audio = pyaudio.PyAudio()
    vad = webrtcvad.Vad(vad_level)

    with suppress(KeyboardInterrupt), wave.open(file_out, "wb") as wav_out:
        wav_out.setnchannels(channels)
        wav_out.setsampwidth(audio.get_sample_size(format))
        wav_out.setframerate(rate)

        in_stream = audio.open(
            format=format, channels=channels, rate=rate, frames_per_buffer=chunk_size, input=True,
            input_device_index=input_device_index
        )

        has_voice = False
        sql_open = False
        sql_open_time = 0

        while True:
            frame = in_stream.read(chunk_size)

            if squelch(frame, sql_threshold):
                if not sql_open:
                    log_print("SQL open")
                sql_open = True
                sql_open_time = 0

            if not sql_open:
                continue

            if use_vad and not has_voice and vad.is_speech(frame, rate):
                has_voice = True
                log_print("Voice detected")

            if not use_vad or (use_vad and has_voice):
                wav_out.writeframes(frame)

            if sql_open_time < sql_duration:
                sql_open_time += frame_duration
            else:
                sql_open = False
                has_voice = False
                log_print("SQL closed")


def list_devices() -> None:
    p = pyaudio.PyAudio()
    devices = p.get_device_count()

    print("Device list\n")

    for i in range(devices):
        dev = p.get_device_info_by_index(i)

        if dev.get("maxInputChannels") > 0:
            print(f"[{dev.get('index'):3}] {dev.get('name')} "
                  f"(channels: {dev.get('maxInputChannels')}, sample rate: {dev.get('defaultSampleRate')}Hz)")


if __name__ == '__main__':
    p = argparse.ArgumentParser(description="Python SQL/VAD recorder")

    p.add_argument("-f", "--file", type=argparse.FileType("wb"), help="output file name", required=True)
    p.add_argument("-i", "--input_device", type=int, help="input device index", required=False, default=None)
    p.add_argument("-r", "--rate", type=int, help="sample frequency (Hz)", choices=[8000, 16000, 32000, 48000],
                   default=8000)
    p.add_argument("-c", "--channels", type=int, help="num channels", default=1)
    p.add_argument("-q", "--sql_threshold", type=int, help="SQL threshold (dB)", default=-120)
    p.add_argument("-d", "--sql_duration", type=int, help="SQL closing time duration (ms)", default=300)
    p.add_argument("-v", "--vad", type=bool, help="voice activity detector", default=False)

    args = p.parse_args()

    list_devices()

    print()

    record(
        file_out=args.file,
        rate=args.rate,
        channels=args.channels,
        sql_threshold_db=args.sql_threshold,
        sql_duration=args.sql_duration,
        use_vad=args.vad,
        input_device_index=args.input_device,
    )
