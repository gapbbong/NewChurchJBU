# -*- coding: utf-8 -*-
"""
유튜브 재생목록 자막 추출기 v2 (yt-dlp 기반, 차단에 강함)
- yt-dlp 로 자막(vtt) 다운로드 -> 깨끗한 텍스트로 변환
- 브라우저 impersonate + (선택) 로그인 쿠키로 차단 회피
- 영상당 랜덤 대기 + 429 장시간 백오프
- 이어받기: 이미 받은 파일은 건너뜀
- 실패는 failed.tsv 기록

사용:
  python fetch_transcripts2.py                # 쿠키 없이
  python fetch_transcripts2.py --cookies chrome   # 크롬 로그인 쿠키 사용(권장)
  python fetch_transcripts2.py --cookies edge     # 엣지
"""
import os
import re
import json
import time
import random
import argparse
import datetime

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

try:
    from yt_dlp.networking.impersonate import ImpersonateTarget
    IMPERSONATE = ImpersonateTarget.from_str("chrome")
except Exception:
    IMPERSONATE = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE_DIR, "transcripts")
SUB_DIR = os.path.join(BASE_DIR, "_subs")          # 임시 vtt
PLAYLIST_JSON = os.path.join(BASE_DIR, "playlist.json")
PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLsoeGhLvvoGKpyvszFG5ZiPQG_gkMfBHK"
FAILED_TSV = os.path.join(BASE_DIR, "failed.tsv")
LOG_FILE = os.path.join(BASE_DIR, "progress.log")
META_JSONL = os.path.join(BASE_DIR, "metadata.jsonl")   # 영상별 제목/링크/본문/설명 집계

SUB_LANGS = ["ko", "ko-orig", "ko-KR"]   # 한국어 우선(수동->자동)
MIN_DELAY, MAX_DELAY = 10.0, 18.0        # 영상 간 대기(초). 쿠키 사용 시 줄여도 됨
MAX_RETRY = 6                            # 429 등 재시도 횟수


def log(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def get_playlist(force=False):
    if os.path.exists(PLAYLIST_JSON) and not force:
        with open(PLAYLIST_JSON, encoding="utf-8") as f:
            data = json.load(f)
        log(f"재생목록 캐시 로드: {len(data)}개")
        return data
    log("재생목록 수집 중...")
    with YoutubeDL({"extract_flat": True, "quiet": True, "no_warnings": True,
                    "ignoreerrors": True}) as ydl:
        info = ydl.extract_info(PLAYLIST_URL, download=False)
    entries = [{"id": e.get("id"), "title": e.get("title", "")}
               for e in info.get("entries", []) if e]
    with open(PLAYLIST_JSON, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    log(f"재생목록 수집 완료: {len(entries)}개")
    return entries


def safe_name(s, maxlen=80):
    s = s or ""
    s = "".join(("_" if c in '<>:"/\\|?*\n\r\t' else c) for c in s).strip()
    return s[:maxlen].rstrip(". ")


def already_done(idx, vid):
    prefix = f"{idx:04d}_{vid}"
    for name in os.listdir(OUT_DIR):
        if name.startswith(prefix):
            return True
    return False


def record_failed(idx, vid, title, reason):
    with open(FAILED_TSV, "a", encoding="utf-8") as f:
        f.write(f"{idx}\t{vid}\t{reason}\t{title}\n")


def write_metadata(idx, vid, title, upload, views, bonmun, desc):
    """영상별 메타데이터를 metadata.jsonl 에 한 줄씩 append (본문/링크 검색·집계용)."""
    rec = {
        "index": idx,
        "id": vid,
        "url": f"https://youtu.be/{vid}",
        "title": title,
        "upload_date": upload,
        "view_count": views,
        "bonmun": bonmun,
        "description": desc,
    }
    with open(META_JSONL, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


_TAG = re.compile(r"<[^>]+>")           # <00:00:00.000>, <c> 등
_TS = re.compile(r"^\d{2}:\d{2}:\d{2}\.\d{3}\s*-->")


def vtt_to_text(path):
    """유튜브 자동자막 vtt -> 중복 제거된 평문."""
    out = []
    last = None
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if not line or line.startswith(("WEBVTT", "Kind:", "Language:")):
                continue
            if _TS.match(line) or "-->" in line:
                continue
            line = _TAG.sub("", line).strip()
            line = line.replace("&nbsp;", " ").replace("&amp;", "&")
            if not line or line == last:
                continue
            # 이전 줄이 이 줄의 접두어면(자동자막 롤링) 이전 줄 대체
            if last is not None and line.startswith(last):
                out[-1] = line
            else:
                out.append(line)
            last = line
    return "\n".join(out)


# 본문(성경 구절) 추출용
_BONMUN = re.compile(r"본문\s*[:：]\s*([^\n\r]+)")
_BOOKS = ("창세기|출애굽기|레위기|민수기|신명기|여호수아|사사기|룻기|사무엘|열왕기|역대|에스라|"
          "느헤미야|에스더|욥기|시편|잠언|전도서|아가|이사야|예레미야|예레미야애가|에스겔|다니엘|"
          "호세아|요엘|아모스|오바댜|요나|미가|나훔|하박국|스바냐|학개|스가랴|말라기|마태복음|마가복음|"
          "누가복음|요한복음|사도행전|로마서|고린도|갈라디아서|에베소서|빌립보서|골로새서|데살로니가|"
          "디모데|디도서|빌레몬서|히브리서|야고보서|베드로|요한|유다서|요한계시록|계시록")
_PASSAGE = re.compile(r"(" + _BOOKS + r")\s*\d+\s*장(?:\s*\d+\s*절(?:\s*[~\-–]\s*\d+\s*절?)?)?")


def extract_bonmun(title, desc):
    """본문(성경 구절)을 설명문 '본문:' 우선, 없으면 제목/설명 내 'N장 M절' 패턴에서 추출."""
    m = _BONMUN.search(desc or "")
    if m:
        return m.group(1).strip()
    for src in (title or "", desc or ""):
        m = _PASSAGE.search(src)
        if m:
            return m.group(0).strip()
    return ""


def download_sub(vid, cookies_browser, cookiefile):
    """한 영상의 (vtt경로, info딕셔너리)를 반환. 자막 없으면 (None, info)."""
    outtmpl = os.path.join(SUB_DIR, f"{vid}.%(ext)s")
    opts = {
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": SUB_LANGS,
        "subtitlesformat": "vtt",
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": False,
        "retries": 3,
        "sleep_interval_subtitles": 1,
        # 자막만 받으므로 영상 포맷을 못 찾아도 무시하고 진행
        "ignore_no_formats_error": True,
        "allow_unplayable_formats": True,
    }
    if IMPERSONATE is not None:
        opts["impersonate"] = IMPERSONATE
    if cookiefile:
        opts["cookiefile"] = cookiefile
    elif cookies_browser:
        opts["cookiesfrombrowser"] = (cookies_browser, )

    with YoutubeDL(opts) as ydl:
        # download=True 로 자막 파일 저장 + 메타데이터(info) 동시 획득
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=True)

    # 생성된 vtt 중 선호 언어 순으로 선택
    for lang in SUB_LANGS + [""]:
        for name in os.listdir(SUB_DIR):
            if name.startswith(vid + ".") and name.endswith(".vtt") and (lang in name or lang == ""):
                return os.path.join(SUB_DIR, name), info
    return None, info


def cleanup_subs(vid):
    for name in os.listdir(SUB_DIR):
        if name.startswith(vid + "."):
            try:
                os.remove(os.path.join(SUB_DIR, name))
            except OSError:
                pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cookies", default=None, help="쿠키 브라우저: chrome/edge/firefox/brave 등")
    ap.add_argument("--cookiefile", default=None, help="cookies.txt 경로(권장, 브라우저 확장으로 내보낸 파일)")
    ap.add_argument("--min-delay", type=float, default=MIN_DELAY, help="영상 간 최소 대기(초)")
    ap.add_argument("--max-delay", type=float, default=MAX_DELAY, help="영상 간 최대 대기(초)")
    ap.add_argument("--start-delay", type=float, default=0, help="시작 전 대기(초). IP 식힐 때 사용")
    ap.add_argument("--retry-failed", action="store_true")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(SUB_DIR, exist_ok=True)
    entries = get_playlist()

    target = None
    if args.retry_failed and os.path.exists(FAILED_TSV):
        target = set()
        with open(FAILED_TSV, encoding="utf-8") as f:
            for ln in f:
                p = ln.split("\t")
                if p and p[0].isdigit():
                    target.add(int(p[0]))
        open(FAILED_TSV, "w", encoding="utf-8").close()
        log(f"재시도 모드: {len(target)}개")

    total = len(entries)
    done = skipped = failed = 0
    if args.start_delay > 0:
        log(f"시작 전 {args.start_delay:.0f}초 대기 (IP 쿨다운)...")
        time.sleep(args.start_delay)

    cookie_mode = args.cookiefile or args.cookies or "none"
    log(f"수집 시작 (impersonate={'on' if IMPERSONATE else 'off'}, cookies={cookie_mode}, "
        f"간격={args.min_delay:.0f}~{args.max_delay:.0f}s)")

    for i, e in enumerate(entries, 1):
        vid, title = e["id"], (e.get("title") or "")
        if not vid:
            continue
        if target is not None and i not in target:
            continue
        if target is None and already_done(i, vid):
            skipped += 1
            continue

        attempt = 0
        while True:
            attempt += 1
            try:
                sub_path, info = download_sub(vid, args.cookies, args.cookiefile)
                info = info or {}
                title = info.get("title") or title or ""   # 재생목록 title이 None이면 실제 제목 사용
                desc = info.get("description") or ""
                upload = info.get("upload_date") or ""
                views = info.get("view_count")
                bonmun = extract_bonmun(title, desc)

                # 메타데이터는 자막 유무와 무관하게 항상 기록
                write_metadata(i, vid, title, upload, views, bonmun, desc)

                if not sub_path:
                    record_failed(i, vid, title, "NoSubtitle")
                    failed += 1
                    log(f"[{i}/{total}] 자막없음(메타만 저장) {title[:40]}")
                    break
                text = vtt_to_text(sub_path)
                cleanup_subs(vid)
                m = re.search(r"\.([a-zA-Z\-]+)\.vtt$", sub_path)
                lang = m.group(1) if m else "?"
                path = os.path.join(OUT_DIR, f"{i:04d}_{vid}_{safe_name(title)}.txt")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(f"# title: {title}\n")
                    f.write(f"# url: https://youtu.be/{vid}\n")
                    f.write(f"# upload: {upload}\n")
                    f.write(f"# bonmun: {bonmun}\n")
                    f.write(f"# lang: {lang}\n")
                    f.write("# ----- description -----\n")
                    for dl in desc.splitlines():
                        f.write(f"# {dl}\n")
                    f.write("# ----- transcript -----\n\n")
                    f.write(text)
                done += 1
                log(f"[{i}/{total}] OK ({lang}, {len(text)}자, 본문='{bonmun}') {title[:35]}")
                break
            except DownloadError as ex:
                msg = str(ex)
                if "429" in msg or "Too Many Requests" in msg or "Sign in" in msg:
                    if attempt >= MAX_RETRY:
                        record_failed(i, vid, title, "RateLimited")
                        failed += 1
                        log(f"[{i}/{total}] 재시도 초과(429) {title[:40]}")
                        break
                    wait = min(600, 60 * (2 ** (attempt - 1))) + random.uniform(0, 20)
                    log(f"[{i}/{total}] 429/차단, {wait:.0f}초 대기 후 재시도({attempt}/{MAX_RETRY})")
                    time.sleep(wait)
                else:
                    record_failed(i, vid, title, "DownloadError")
                    failed += 1
                    log(f"[{i}/{total}] 오류: {msg[:60]}")
                    break
            except Exception as ex:
                record_failed(i, vid, title, f"{type(ex).__name__}")
                failed += 1
                log(f"[{i}/{total}] 예외 {type(ex).__name__}: {str(ex)[:60]}")
                break

        time.sleep(random.uniform(args.min_delay, args.max_delay))

    log(f"===== 완료: 성공 {done}, 건너뜀 {skipped}, 실패 {failed}, 전체 {total} =====")


if __name__ == "__main__":
    main()
