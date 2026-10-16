"""TikTok Studio in its own window. The owner logs in there by hand, the app only puts the video's hashtags into the
caption (the Tampermonkey script, moved here). It never clicks «Опубликовать» or «Запланировать», never reads or saves
a login, cookies or password: the window gets no js_api, and pywebview's default private mode keeps the session in
memory only."""
import json
import re

UPLOAD = "https://www.tiktok.com/tiktokstudio/upload"
WAIT = 300  # seconds for the caption field: the owner logs in and uploads the video by hand

# Read the caption text, or null when the page has no editor (login page, upload not started).
CAPTION_JS = "(() => { const e = document.querySelector('.public-DraftEditor-content'); return e ? e.innerText : null; })()"
STATE_JS = "window.__glowlabHtf || null"
STOP_JS = "window.__glowlabHtf && (window.__glowlabHtf.stop = true)"

# Types each tag letter by letter, waits for its suggestion and clicks it: only then the tag turns black.
# Same steps as the Tampermonkey script, with the messages the owner asked for. A missing suggestion or editor stops
# the run and clears what was typed; the page keeps the job state in window.__glowlabHtf for the app to read.
JOB = """(async () => {
  const S = window.__glowlabHtf;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const ed = () => document.querySelector('.public-DraftEditor-content');
  const toEnd = () => {
    const e = ed();
    if (!e) return false;
    e.focus();
    const sel = getSelection();
    sel.selectAllChildren(e);
    sel.collapseToEnd();
    return true;
  };
  const click = (el) => {
    const o = { bubbles: true, cancelable: true, view: window };
    ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'].forEach((t) =>
      el.dispatchEvent(new (t.startsWith('pointer') ? PointerEvent : MouseEvent)(t, o)));
  };
  const erase = async (n) => {
    toEnd();
    for (let k = 0; k < n; k++) { document.execCommand('delete'); await sleep(60); }
  };
  const pick = (tag) => [...document.querySelectorAll('.hashtag-suggestion-item')]
    .find((e) => e.textContent.trim().split(/\\s+/)[0].toLowerCase() === tag.toLowerCase());
  try {
    for (const tag of S.tags) {
      if (S.stop) break;
      S.tag = tag;
      if (!toEnd()) { S.error = 'Не нашли поле описания: открой загрузку видео в TikTok Studio'; break; }
      await sleep(150);
      for (const ch of tag) { document.execCommand('insertText', false, ch); await sleep(20); }
      let item;
      const t0 = Date.now();
      while (!S.stop && !(item = pick(tag)) && Date.now() - t0 < 10000) await sleep(250);
      if (S.stop) { await erase(tag.length); break; }
      if (!item) { await erase(tag.length); S.error = 'Не нашли подсказку: ' + tag; break; }
      await sleep(200);
      click(item.querySelector('.hash-tag-topic') || item);
      await sleep(300);
      S.added += 1;
      S.at += 1;
    }
  } catch (e) {
    S.error = 'Что-то пошло не так: ' + e.message;
  }
  S.running = false;
})();"""


def tokens(caption: str) -> set[str]:
    """Hashtags of a caption as whole words, lowercased: `#mogg` is not `#mog`."""
    return set(re.findall(r"#\w+", caption.lower()))


def missing(caption: str, tags: list[str]) -> list[str]:
    """Tags that are not in the caption yet, in their order, each once."""
    seen, out = tokens(caption), []
    for tag in tags:
        t = "#" + tag.lstrip("#")
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


def job_js(tags: list[str], skipped: int) -> str:
    """Script for the TikTok page. It returns at once; the work goes on in the page and reports to window.__glowlabHtf."""
    state = {"tags": tags, "total": len(tags), "skipped": skipped, "added": 0, "at": 0, "tag": "", "error": "",
             "stop": False, "running": True}
    return "window.__glowlabHtf = " + json.dumps(state) + ";\n" + JOB + "\n'started';"


def describe(job: dict | None) -> dict:
    """The panel's line, from the job state the page reports."""
    if not job:
        return {"running": False, "message": ""}
    total, added = job["total"], job["added"]
    if job["running"]:
        return {"running": True, "message": f"{job['at'] + 1} из {total}: {job['tag']}"}
    if job["error"]:
        return {"running": False, "message": f"{job['error']}. Не добавлено: {total - added} из {total}"}
    if job["stop"]:
        return {"running": False, "message": f"Остановлено: добавлено {added} из {total}"}
    return {"running": False, "message": f"Готово: добавлено {added}, уже были в описании {job['skipped']}"}
