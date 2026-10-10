# -*- coding: utf-8 -*-
"""
유튜브 재생목록 전체 스크립트(자막) 추출기
- 재생목록의 모든 영상 ID를 yt-dlp로 수집
- youtube-transcript-api로 각 영상 자막을 받아 파일로 저장
- 중단 후 재실행하면 이미 받은 것은 건너뜀 (이어받기)
- 실패는 failed.tsv에 기록, 나중에 --retry-failed 로 재시도
- 요청 간 딜레이 + 지수 백오프로 IP 차단 회피
"""
import os
import sys
import json
import time
import random
import argparse
import datetime

from yt_dlp import YoutubeDL
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api import (
    TranscriptsDisabled, NoTranscriptFound, VideoUnavailable,
    VideoUnplayable, AgeRestricted, RequestBlocked, IpBlocked,
    InvalidVideoId, YouTubeRequestFailed,
)

# ------------------------- 설정 -------------------------
PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLsoeGhLvvoGKpyvszFG5ZiPQG_gkMfBHK"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE_DIR, "transcripts")     # 자막 저장 폴더
PLAYLIST_JSON = os.path.join(BASE_DIR, "playlist.json")
FAILED_TSV = os.path.join(BASE_DIR, "failed.tsv")
LOG_FILE = os.path.join(BASE_DIR, "progress.log")

# 자막 우선순위: 수동 한국어 -> 자동생성 한국어 -> 영어
LANG_PREF = ["ko", "ko-KR", "a.ko", "en", "en-US"]

MIN_DELAY = 1.5      # 요청 간 최소 딜레이(초)
MAX_DELAY = 3.5      # 요청 간 최대 딜레이(초)
MAX_RETRY = 5        # 일시적 오류 재시도 횟수
# --------------------------------------------------------


def log(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def get_playlist(force=False):
    """재생목록의 모든 영상 (id, title) 목록을 반환. 캐시 사용."""
    if os.path.exists(PLAYLIST_JSON) and not force:
        with open(PLAYLIST_JSON, encoding="utf-8") as f:
            data = json.load(f)
        log(f"재생목록 캐시 로드: {len(data)}개 영상")
        return data

    log("재생목록 정보 수집 중... (yt-dlp, 수 분 걸릴 수 있음)")
    opts = {
        "extract_flat": True,   # 각 영상 페이지는 안 열고 목록만 빠르게
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(PLAYLIST_URL, download=False)

    entries = []
    for e in info.get("entries", []):
        if not e:
            continue
        entries.append({"id": e.get("id"), "title": e.get("title", "")})
    with open(PLAYLIST_JSON, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    log(f"재생목록 수집 완료: {len(entries)}개 영상 -> {PLAYLIST_JSON}")
    return entries


def safe_name(s, maxlen=80):
    bad = '<>:"/\\|?*\n\r\t'
    s = "".join(("_" if c in bad else c) for c in s).strip()
    return s[:maxlen].rstrip(". ")


def already_done(idx, vid):
    """해당 영상 자막 파일이 이미 있으면 경로 반환, 없으면 None."""
    prefix = f"{idx:04d}_{vid}"
    for name in os.listdir(OUT_DIR):
        if name.startswith(prefix):
            return os.path.join(OUT_DIR, name)
    return None


def fetch_one(api, vid):
    """한 영상의 자막을 (텍스트, 사용언어)로 반환. 실패 시 예외."""
    fetched = api.fetch(vid, languages=LANG_PREF)
    lang = getattr(fetched, "language_code", "?")
    # 문장 단위로 합침 (타임스탬프는 별도 저장하지 않음)
    text = "\n".join(snip.text.strip() for snip in fetched if snip.text.strip())
    return text, lang


def record_failed(idx, vid, title, reason):
    with open(FAILED_TSV, "a", encoding="utf-8") as f:
        f.write(f"{idx}\t{vid}\t{reason}\t{title}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh-playlist", action="store_true", help="재생목록 캐시 무시하고 다시 수집")
    ap.add_argument("--retry-failed", action="store_true", help="failed.tsv 목록만 재시도")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    entries = get_playlist(force=args.refresh_playlist)

    # 재시도 모드면 실패목록만 대상으로
    target_indices = None
    if args.retry_failed and os.path.exists(FAILED_TSV):
        target_indices = set()
        with open(FAILED_TSV, encoding="utf-8") as f:
            for ln in f:
                parts = ln.split("\t")
                if parts:
                    try:
                        target_indices.add(int(parts[0]))
                    except ValueError:
                        pass
        # 재시도 시작 시 실패목록 비우기 (새로 기록)
        open(FAILED_TSV, "w", encoding="utf-8").close()
        log(f"재시도 모드: {len(target_indices)}개 대상")

    api = YouTubeTranscriptApi()
    total = len(entries)
    done = skipped = failed = 0

    for i, e in enumerate(entries, start=1):
        vid = e["id"]
        title = e.get("title", "")

        if target_indices is not None and i not in target_indices:
            continue
        if not vid:
            continue

        # 이어받기: 이미 있으면 건너뜀
        existing = already_done(i, vid)
        if existing and target_indices is None:
            skipped += 1
            continue

        attempt = 0
        while True:
            attempt += 1
            try:
                text, lang = fetch_one(api, vid)
                fname = f"{i:04d}_{vid}_{safe_name(title)}.txt"
                path = os.path.join(OUT_DIR, fname)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(f"# {title}\n")
                    f.write(f"# https://youtu.be/{vid}\n")
                    f.write(f"# lang={lang}\n\n")
                    f.write(text)
                done += 1
                log(f"[{i}/{total}] OK ({lang}, {len(text)}자) {title[:40]}")
                break

            # --- 자막 자체가 없는 경우: 재시도 무의미, 기록 후 넘어감 ---
            except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable,
                    VideoUnplayable, AgeRestricted, InvalidVideoId) as ex:
                reason = type(ex).__name__
                record_failed(i, vid, title, reason)
                failed += 1
                log(f"[{i}/{total}] 자막없음/불가 ({reason}) {title[:40]}")
                break

            # --- IP 차단 / 일시적 오류: 백오프 후 재시도 ---
            except (RequestBlocked, IpBlocked, YouTubeRequestFailed) as ex:
                if attempt >= MAX_RETRY:
                    record_failed(i, vid, title, type(ex).__name__)
                    failed += 1
                    log(f"[{i}/{total}] 재시도 초과 ({type(ex).__name__}) {title[:40]}")
                    break
                wait = min(60, 5 * (2 ** (attempt - 1))) + random.uniform(0, 5)
                log(f"[{i}/{total}] 차단/오류, {wait:.0f}초 대기 후 재시도({attempt}/{MAX_RETRY})")
                time.sleep(wait)

            # --- 기타 예외: 기록 후 넘어감 ---
            except Exception as ex:
                record_failed(i, vid, title, f"{type(ex).__name__}:{ex}")
                failed += 1
                log(f"[{i}/{total}] 오류 {type(ex).__name__} {title[:40]}")
                break

        # 정상 요청 사이 딜레이 (차단 회피)
        time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

    log(f"===== 완료: 성공 {done}, 건너뜀 {skipped}, 실패 {failed}, 전체 {total} =====")


if __name__ == "__main__":
    main()
