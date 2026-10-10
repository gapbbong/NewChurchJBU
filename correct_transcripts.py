# -*- coding: utf-8 -*-
"""
자막 오탈자/가독성 교정기 (완전 무료 · 오프라인)
- kiwipiepy 로 띄어쓰기 교정 + 문장 단위 재구성
- replacements.json 치환표로 반복되는 용어 오인식 교정
- transcripts/ -> transcripts_clean/ 로 저장
- 이미 교정된 파일은 건너뜀 (이어하기)
LLM 없이 무료로 동작. 검색/자료 정리 용도에 적합.
"""
import os
import re
import json
import datetime

from kiwipiepy import Kiwi

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IN_DIR = os.path.join(BASE_DIR, "transcripts")
OUT_DIR = os.path.join(BASE_DIR, "transcripts_clean")
REPL_JSON = os.path.join(BASE_DIR, "replacements.json")
LOG_FILE = os.path.join(BASE_DIR, "clean.log")


def log(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_replacements():
    if not os.path.exists(REPL_JSON):
        return {}
    with open(REPL_JSON, encoding="utf-8") as f:
        data = json.load(f)
    # _로 시작하는 메타키 제외
    return {k: v for k, v in data.items() if not k.startswith("_")}


def apply_replacements(text, repl):
    for wrong, right in repl.items():
        if wrong:
            text = text.replace(wrong, right)
    return text


def clean_one(kiwi, repl, in_path, out_path):
    with open(in_path, encoding="utf-8") as f:
        lines = f.readlines()

    # 헤더(#로 시작) 와 본문 분리
    header = [ln.rstrip("\n") for ln in lines if ln.startswith("#")]
    body_lines = [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]

    # 자막 조각을 하나의 흐름으로 이어붙임
    raw = " ".join(body_lines)
    raw = re.sub(r"\s+", " ", raw).strip()

    # 1) 치환표 (띄어쓰기 교정 전 원형 기준으로 먼저 적용)
    raw = apply_replacements(raw, repl)

    # 2) 띄어쓰기 교정
    spaced = kiwi.space(raw)

    # 3) 띄어쓰기 후 다시 치환표 (교정으로 새로 생긴 형태 보정)
    spaced = apply_replacements(spaced, repl)

    # 4) 문장 단위로 분리 -> 한 줄에 한 문장 (검색·가독성 향상)
    sents = [s.text.strip() for s in kiwi.split_into_sents(spaced) if s.text.strip()]

    with open(out_path, "w", encoding="utf-8") as f:
        for h in header:
            f.write(h + "\n")
        f.write("\n")
        f.write("\n".join(sents))
        f.write("\n")
    return len(sents)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    repl = load_replacements()
    log(f"치환표 {len(repl)}개 로드")

    kiwi = Kiwi()
    files = sorted(f for f in os.listdir(IN_DIR) if f.endswith(".txt"))
    total = len(files)
    done = skipped = failed = 0

    for i, name in enumerate(files, 1):
        in_path = os.path.join(IN_DIR, name)
        out_path = os.path.join(OUT_DIR, name)
        if os.path.exists(out_path):
            skipped += 1
            continue
        try:
            n = clean_one(kiwi, repl, in_path, out_path)
            done += 1
            if i % 25 == 0 or i == total:
                log(f"[{i}/{total}] 교정중... (방금 {n}문장) {name[:40]}")
        except Exception as ex:
            failed += 1
            log(f"[{i}/{total}] 오류 {type(ex).__name__}: {ex} / {name}")

    log(f"===== 교정 완료: 성공 {done}, 건너뜀 {skipped}, 실패 {failed}, 전체 {total} =====")


if __name__ == "__main__":
    main()
