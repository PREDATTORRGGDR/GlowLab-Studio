"""Claude writes the scene script from the facts. Runs the local Claude Code CLI on the owner's
subscription (no API key) with a JSON schema, so the output shape is guaranteed."""
import glob
import json
import os
import re
import shutil
import subprocess
import tempfile

from data import section_score

LANG_NAMES = {"ru": "русский", "en": "English", "uk": "українська"}
KINDS = ["hook", "section", "metric", "verdict", "outro"]
SCHEMA = {
    "type": "object", "required": ["scenes", "hashtags"],
    "properties": {"hashtags": {"type": "array", "minItems": 8, "maxItems": 12, "items": {"type": "string"}},
                   "scenes": {"type": "array", "minItems": 6, "maxItems": 20, "items": {
        "type": "object", "required": ["kind", "ref", "title", "voice", "highlight"],
        "properties": {
            "kind": {"type": "string", "enum": KINDS},
            "ref": {"type": "string"},
            "title": {"type": "string"},
            "voice": {"type": "string"},
            "highlight": {"type": "array", "items": {"type": "string"}},
        }}}},
}
SYSTEM = """Ты сценарист коротких вертикальных роликов канала про оценку внешности: быстрый разбор лица по цифрам из бота GlowLab.
Тебе дают JSON «фактов» о человеке. Ты пишешь сценарий из сцен. Каждая сцена это один кадр и одна реплика диктора.

Как звучат ролики канала (образец темпа и тона, цифры в образце чужие):
«Насколько привлекателен Дрейк? Гармония в анфас 5. Из минусов у него: большой промежуток в один глаз. Плохая пропорция нижней трети. Плохая высота скул. Гармония в профиль 5 и 6. Из минусов: плохая выпуклость профиля. Плохой носолобный угол. Дальше смотрите сами. <призыв в бота>»
Если лицо сильное, наоборот перечисляются плюсы: «Гармония в анфас 9 и 5, минусов просто нет».

Длина: весь голос вместе 15..35 секунд, это 40..80 слов. Темп быстрый, реплики рубленые.

Порядок сцен:
1. hook (ref пустой): вопрос-интрига, например «Насколько привлекателен <имя>?». Он звучит поверх эдита со знаменитостью.
2. section с ref "harmony_front": гармония анфаса с баллом.
3. metric: 2..5 метрик анфаса (side = "front"). Если гармония анфаса ниже 7, это минусы: самые низкие баллы, реплика «Плохая <метрика>.» или «Большой/маленький ...». Если 7 и выше, это плюсы: самые высокие баллы. Первую метрику списка можно начать словами «Из минусов у него/неё» или «Из плюсов».
4. section с ref "harmony_side": гармония профиля, если она есть. Затем так же 2..5 метрик профиля (side = "side").
5. Только если subject.mode = "full": section с ref "overall" (общий балл) и verdict с архетипом, если архетип есть.
6. outro (ref пустой): «Дальше смотрите сами» и призыв зайти в бота из описания. Призыв каждый раз пиши заново своими словами, живо и коротко, до 12 слов, как сказал бы блогер, а не реклама: зацепи тем, что зритель узнает про своё лицо (свои баллы, свои минусы, что подтянуть). Не пиши «оценить себя или получить профессиональный анализ» и другие казённые связки через «или». Можно одной или двумя сценами.

Жёсткие правила:
1. Только числа и факты из JSON. Ничего не выдумывай: ни баллы, ни метрики, ни имена, ни проценты. Поля со значением null или пустые означают, что данных нет, про них не говори.
2. Баллы пиши так, как их произносит диктор: дробный балл через «и»: 8.2 это «8 и 2», 5.6 это «5 и 6»; целый балл просто «5»; «из 10» можно добавить. Один знак после запятой, не больше. Значения метрик (градусы, проценты, отношения) не называй.
3. Если subject.mode = "harmony" (звезда): только гармония анфаса и профиля и метрики. Нет общего балла, диморфизма, архетипа, советов.
4. Реплика метрики 2..8 слов, остальных сцен до 16 слов. Разговорная речь, без канцелярита. Не используй тире.
5. Метрику называй по-человечески по её name: «промежуток в один глаз», «пропорция нижней трети», «носолобный угол». Тон разбора, без унижений.
6. title: подпись на экране, до 4 слов, без цифр. Для метрики это её название.
7. highlight: обычно пустой список.
8. Никаких медицинских советов, процедур и препаратов.
9. Язык всех title и voice: {lang}.

Хэштеги для TikTok (hashtags): 8..12 штук, каждый с #, слитно, только буквы и цифры. Состав:
1. Имя человека латиницей слитно и по-русски: #drake #дрейк, #meganfox #меганфокс. Если subject.source = "me" (мой анализ, имени нет), этой группы нет.
2. Если человек известен эдитами, фанатские теги: #meganfoxedits #meganfoxprime.
3. Ниша: #луксмаксинг #facerate #mog #могг #looks #оценкавнешности, по смыслу ролика можно #mogger #height #primal.
4. Охват: #fyp #pourtoi #foryoupage #edit #viral.
Наборы, которые залетают у владельца, равняйся на них:
#pourtoi #fyp #edit #foryoupage #drake #дрейк #looks #луксмаксинг #facerate #могг #mog
#edit #viral #fyp #meganfoxprime #меганфокс #meganfoxedits #facerate #луксмаксинг
#tylermaher #edit #mog #height #mogger #оценкавнешности #primal"""


def claude_exe() -> str:
    # The desktop app is an MSIX package: outside it, its %APPDATA% lives under LocalCache.
    found = glob.glob(os.path.expandvars(r"%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude\claude-code\*\*\claude.exe"))
    found += glob.glob(os.path.expandvars(r"%APPDATA%\Claude\claude-code\*\*\claude.exe"))
    exe = max(found, key=os.path.getmtime) if found else shutil.which("claude")
    if not exe:
        raise RuntimeError("Не найден Claude Code: установи приложение Claude и войди в аккаунт")
    return exe


def brief(facts: dict) -> dict:
    """Facts without photos and points: only what the script may talk about."""
    keep = ("key", "name", "side", "value", "unit", "score", "verdict")
    out = {k: v for k, v in facts.items() if k not in ("photos", "points", "metrics")}
    out["metrics"] = [{k: m[k] for k in keep} for m in facts["metrics"]]
    return out


def ask(prompt: str, lang: str, model: str) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "ANTHROPIC"))}
    r = subprocess.run(
        [claude_exe(), "-p", "--output-format", "json", "--json-schema", json.dumps(SCHEMA), "--model", model,
         "--system-prompt", SYSTEM.replace("{lang}", LANG_NAMES.get(lang, lang)),
         "--tools", "", "--no-session-persistence", "--setting-sources", ""],
        input=prompt, capture_output=True, text=True, encoding="utf-8", env=env,
        cwd=tempfile.gettempdir(), timeout=300, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        j = json.loads(r.stdout)
    except ValueError:
        raise RuntimeError("Claude Code не ответил: " + (r.stderr or r.stdout)[-300:].strip())
    if j.get("is_error") or not j.get("structured_output"):
        msg = str(j.get("result") or "")
        if "login" in msg.lower():
            raise RuntimeError("Claude Code не залогинен: запусти его один раз и войди через /login")
        raise RuntimeError("Claude не вернул сценарий: " + msg[:300])
    return j["structured_output"]


def numbers(facts: dict) -> set[str]:
    """Every way a number from the facts may be spoken: as is, to 1 decimal, rounded."""
    out = {"10"}
    def walk(v):
        if isinstance(v, bool):
            return
        if isinstance(v, (int, float)):
            out.update({f"{v:g}", f"{v:.1f}", str(round(v)), f"{v:.2f}"})
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(brief(facts))
    return {n.rstrip("0").rstrip(".") if "." in n else n for n in out}


def check(facts: dict, scenes: list[dict]) -> list[str]:
    """Problems in the script: invented numbers, refs that are not in the facts."""
    ok, problems = numbers(facts), []
    keys = {m["key"] for m in facts["metrics"]}
    for n, s in enumerate(scenes, 1):
        text = re.sub(r"\b(\d+) и (\d)\b", r"\1.\2", s["title"] + " " + s["voice"])  # "8 и 2" is how 8.2 is spoken
        for num in re.findall(r"\d+(?:[.,]\d+)?", text):
            num = num.replace(",", ".")
            if (num.rstrip("0").rstrip(".") if "." in num else num) not in ok:
                problems.append(f"сцена {n}: число {num} не из фактов")
        if s["kind"] == "metric" and s["ref"] not in keys:
            problems.append(f"сцена {n}: нет метрики {s['ref']}")
        if s["kind"] == "section" and section_score(facts, s["ref"]) is None:
            problems.append(f"сцена {n}: нет раздела {s['ref']}")
        s["highlight"] = [k for k in s["highlight"] if k in keys]
    return problems


def clean_tags(raw: list[str]) -> tuple[list[str], list[str]]:
    """Hashtags checked by code, not trusted to the model: letters (latin, cyrillic) and digits only, no repeats."""
    out = []
    for t in raw:
        t = "#" + re.sub(r"[^0-9a-zа-яёіїєґ]", "", t.lower())
        if len(t) > 1 and t not in out:
            out.append(t)
    return out[:12], ([f"хэштегов {len(out)}, нужно 8..12"] if len(out) < 8 else [])


def write(facts: dict, lang: str = "ru", model: str = "claude-sonnet-5-5", current: dict | None = None,
          request: str = "", avoid: list[str] = ()) -> tuple[list[dict], list[str], list[str]]:
    """The script and hashtags. With current (scenes + hashtags of the made video) and the owner's request,
    the whole script comes back with that change. avoid: closing lines of recent videos, the call to the bot must be new."""
    prompt = "Факты:\n" + json.dumps(brief(facts), ensure_ascii=False)
    if avoid:
        prompt += "\n\nПризывы из прошлых роликов, не повторяй их и не перефразируй близко:\n" + "\n".join(avoid)
    if current:
        now = {"scenes": [{k: x[k] for k in ("kind", "ref", "title", "voice")} for x in current["scenes"]],
               "hashtags": current["hashtags"]}
        prompt += ("\n\nТекущий сценарий ролика:\n" + json.dumps(now, ensure_ascii=False) + "\n\nПросьба владельца: " + request
                   + "\nВерни весь сценарий целиком с этой правкой, остальное оставь как было. Хэштеги обнови, если правка их касается."
                   " Если просьбу нельзя выполнить по фактам, сделай ближайшее, что можно по фактам.")

    def once(p):
        out = ask(p, lang, model)
        tags, bad = clean_tags(out["hashtags"])
        return out["scenes"], tags, check(facts, out["scenes"]) + bad

    scenes, tags, problems = once(prompt)
    if problems:  # one retry with the exact complaints, then hand the rest to the UI as warnings
        scenes, tags, problems = once(prompt + "\n\nПрошлый вариант отклонён:\n" + "\n".join(problems) + "\nИсправь.")
    return scenes, tags, problems
