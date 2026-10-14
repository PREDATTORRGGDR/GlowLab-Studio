"""ElevenLabs + ffmpeg: scenes -> final.mp4.
Template: the edit's first seconds with the caption and the hook voiced over them, then the Mini App screens one per
scene, each as long as its voice line; the edit's audio is the music bed, looped for the whole video and ducked under the voice."""
import hashlib
import subprocess
from pathlib import Path

import httpx
from PIL import Image

from data import LIB, load_settings, tool
import frames

FPS, W, H = 60, 1080, 1920  # 60: the list scroll must be smooth, and every clip shares one rate for concat
GAP = 0.2            # s of silence after each line: the owner's videos are fast
SPEED = 1.1          # ElevenLabs voice speed (0.7..1.2): the owner wants it a bit faster
PAN = 2200           # px/s, top speed of the metric list scroll in "see for yourself"
MUSIC, VOICE = 0.45, 1.6   # bed and voice gains before ducking
VOICE_CACHE = LIB / "voice"


def run(args: list, log: Path) -> None:
    r = subprocess.run([str(a) for a in args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    with log.open("a", encoding="utf-8") as f:
        f.write(" ".join(map(str, args)) + "\n" + r.stderr + "\n")
    if r.returncode:
        raise RuntimeError("ffmpeg не справился:\n" + "\n".join(r.stderr.strip().splitlines()[-5:]))


def duration(path: Path) -> float:
    out = subprocess.run([tool("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    return float(out.strip())


def tts(text: str) -> Path:
    """One ElevenLabs request per line, cached by hash of voice + text: an edit of one line re-voices only that line."""
    s = load_settings()
    if not s["elevenlabs_key"] or not s["voice_id"]:
        raise RuntimeError("Не хватает ключа ElevenLabs или голоса в настройках")
    path = VOICE_CACHE / (hashlib.sha1(f"{s['voice_id']}|{SPEED}|{text}".encode()).hexdigest()[:16] + ".mp3")
    if not path.exists():
        r = httpx.post(f"https://api.elevenlabs.io/v1/text-to-speech/{s['voice_id']}", timeout=120,
                       headers={"xi-api-key": s["elevenlabs_key"]},
                       json={"text": text, "model_id": "eleven_multilingual_v2",
                             "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "speed": SPEED}})
        if r.status_code == 401:
            raise RuntimeError("ElevenLabs не принял ключ")
        if r.status_code == 402:
            raise RuntimeError("Этот голос из библиотеки ElevenLabs работает только на платном тарифе. Выбери стандартный голос в настройках или пополни ElevenLabs")
        if r.status_code >= 400:
            raise RuntimeError(f"ElevenLabs ответил {r.status_code}: {r.text[:200]}")
        VOICE_CACHE.mkdir(parents=True, exist_ok=True)
        path.write_bytes(r.content)
    return path


def intro_clip(edit: Path, start: float, length: float, caption: Path, voice: Path, out: Path, log: Path) -> None:
    """Edit fitted to the width on black, caption on top, the hook line from 0.3 s. Its own sound comes back as the bed."""
    vf = (f"[0:v]fps={FPS},scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1[e];"
          f"[e][1:v]overlay=0:0,format=yuv420p[v];[2:a]adelay=300|300,apad,atrim=0:{length}[a]")
    run([tool("ffmpeg"), "-y", "-ss", start, "-t", length, "-i", edit, "-i", caption, "-i", voice,
         "-filter_complex", vf, "-map", "[v]", "-map", "[a]", "-t", length,
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-ar", "44100", "-ac", "2", out], log)


def scene_clip(png: Path, voice: Path, length: float, out: Path, log: Path) -> None:
    vf = f"[0:v]scale={W}:{H},fps={FPS},format=yuv420p[v];[1:a]apad,atrim=0:{length}[a]"
    run([tool("ffmpeg"), "-y", "-loop", "1", "-t", length, "-i", png, "-i", voice,
         "-filter_complex", vf, "-map", "[v]", "-map", "[a]", "-t", length,
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-ar", "44100", "-ac", "2", out], log)


def outro_clip(shot: dict, voices: list[Path], out: Path, log: Path) -> None:
    """A screen-recording look for the closing lines: the front metric list scrolls to its end, then the profile
    one, the tab bar stays at the bottom; the closing lines play one after another over it."""
    lens = [duration(v) + GAP for v in voices]
    half = sum(lens) / 2
    parts, args = [], []
    for k, (tall, y0) in enumerate(zip(shot["tall"], shot["y0"])):
        dist = min(PAN * half, max(0, Image.open(tall).height - H - y0))  # to the end of the list, not faster than PAN
        ease = f"(3*pow(t/{half:.3f},2)-2*pow(t/{half:.3f},3))"  # smoothstep: speeds up, glides, slows down at the end
        parts.append(f"[{k}:v]fps={FPS},crop={W}:{H}:0:'{y0}+{dist:.0f}*{ease}',trim=0:{half},setpts=PTS-STARTPTS[p{k}]")
        args += ["-loop", "1", "-framerate", FPS, "-t", half, "-i", tall]
    audio = "".join(f"[{3 + k}:a]apad,atrim=0:{n}[a{k}];" for k, n in enumerate(lens))
    fc = (";".join(parts) + f";[p0][p1]concat=n=2:v=1:a=0[page];[page][2:v]overlay=0:H-h,format=yuv420p[v];"
          + audio + "".join(f"[a{k}]" for k in range(len(lens))) + f"concat=n={len(lens)}:v=0:a=1[a]")
    run([tool("ffmpeg"), "-y", *args, "-i", shot["nav"], *[x for v in voices for x in ("-i", v)],
         "-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-t", sum(lens),
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-ar", "44100", "-ac", "2", out], log)


def make(project: Path, scenes: list[dict], shots: list, edit: Path, start: float = 0, length: float = 5,
         caption: str = "", font_path=None, progress=lambda msg: None, cancelled=lambda: False) -> Path:
    if not (tool("ffmpeg") and tool("ffprobe")):
        raise RuntimeError("ffmpeg не найден: положи ffmpeg.exe и ffprobe.exe в папку bin")
    work = project / "clips"
    work.mkdir(parents=True, exist_ok=True)
    log = project / "ffmpeg.log"
    log.write_text("", "utf-8")

    clips = []
    for n, (scene, shot) in enumerate(zip(scenes, shots)):
        if cancelled():
            raise RuntimeError("Отменено")
        if n and isinstance(shot, dict) and shot is shots[n - 1]:
            continue  # already in the outro clip of the previous scene
        progress(f"Озвучка и монтаж: сцена {n + 1} из {len(scenes)}")
        voice = tts(scene["voice"])
        if scene["kind"] == "hook":
            cap = frames.text_overlay(caption or scene["voice"], work / "caption.png", font_path)
            intro_clip(edit, start, max(length, duration(voice) + 0.6), cap, voice, work / f"{n:02}.mp4", log)
        elif isinstance(shot, dict):  # this and every following scene sharing the scroll
            group = [scene] + [s for s, sh in zip(scenes[n + 1:], shots[n + 1:]) if sh is shot]
            outro_clip(shot, [voice] + [tts(s["voice"]) for s in group[1:]], work / f"{n:02}.mp4", log)
        elif shot:
            scene_clip(shot, voice, duration(voice) + GAP, work / f"{n:02}.mp4", log)
        else:
            continue
        clips.append(work / f"{n:02}.mp4")

    progress("Склейка и музыка")
    (work / "list.txt").write_text("".join(f"file '{c.name}'\n" for c in clips), "utf-8")
    run([tool("ffmpeg"), "-y", "-f", "concat", "-safe", "0", "-i", work / "list.txt", "-c", "copy", work / "body.mp4"], log)
    total = duration(work / "body.mp4")
    # The bed: the edit's own track from its start, looped; it ducks whenever the voice speaks (sidechain).
    mix = (f"[1:a]atrim=0:{total},volume={MUSIC}[m];[0:a]volume={VOICE},asplit[v][key];"
           f"[m][key]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=350[duck];"
           f"[v][duck]amix=inputs=2:normalize=0:duration=first,loudnorm=I=-14:TP=-1.5:LRA=11[a]")
    final = project / "final.mp4"
    run([tool("ffmpeg"), "-y", "-i", work / "body.mp4", "-stream_loop", "-1", "-ss", start, "-i", edit,
         "-filter_complex", mix, "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
         "-ar", "44100", "-movflags", "+faststart", "-t", total, final], log)
    return final
