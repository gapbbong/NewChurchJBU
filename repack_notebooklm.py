# -*- coding: utf-8 -*-
"""
통합_성경책별/ (55개) -> NotebookLM 무료 한도(소스 50개)에 맞게 ≤50개로 재묶음.
- 성경 정경 순서 유지, 인접한 작은 책들끼리 병합
- 각 파일 50만 단어(=CAP) 이하 보장
- 원본 미변경, 신규 폴더 notebooklm_50/ 에 출력
"""
import os
import glob

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "통합_성경책별")
OUT = os.path.join(BASE, "notebooklm_50")
TARGET = 50          # NotebookLM 무료 소스 한도
CAP = 500000         # 소스당 단어 한도


def prefix_num(name):
    n = name.split("_", 1)[0]
    return int(n) if n.isdigit() else 0


def book_part(name):
    return name.split("_", 1)[1] if "_" in name else name


def main():
    os.makedirs(OUT, exist_ok=True)
    files = sorted(glob.glob(os.path.join(SRC, "*.txt")),
                   key=lambda f: prefix_num(os.path.basename(f)[:-4]))
    bins = []
    for f in files:
        name = os.path.basename(f)[:-4]
        text = open(f, encoding="utf-8").read()
        bins.append({"names": [name], "text": text, "wc": len(text.split())})

    # 인접 쌍 중 합계가 가장 작은 쌍을 반복 병합 -> TARGET 도달
    while len(bins) > TARGET:
        best_i, best_wc = None, None
        for i in range(len(bins) - 1):
            wc = bins[i]["wc"] + bins[i + 1]["wc"]
            if wc <= CAP and (best_wc is None or wc < best_wc):
                best_i, best_wc = i, wc
        if best_i is None:
            print("경고: 더 병합하면 단어 한도 초과 -> 현재 개수에서 중단")
            break
        a, b = bins[best_i], bins[best_i + 1]
        bins[best_i:best_i + 2] = [{
            "names": a["names"] + b["names"],
            "text": a["text"] + "\n\n" + b["text"],
            "wc": a["wc"] + b["wc"],
        }]

    # 파일로 출력
    for bn in bins:
        names = bn["names"]
        if len(names) == 1:
            fname = names[0]
        else:
            lo = prefix_num(names[0])
            hi = prefix_num(names[-1])
            parts = "_".join(book_part(n) for n in names)
            fname = f"{lo:02d}-{hi:02d}_{parts}"
        fname = fname[:90] + ".txt"
        with open(os.path.join(OUT, fname), "w", encoding="utf-8") as f:
            f.write(bn["text"])

    print(f"최종 소스 파일: {len(bins)}개 (목표 ≤{TARGET})")
    print(f"최대 단어수: {max(b['wc'] for b in bins):,} (한도 {CAP:,})")
    print(f"출력: {OUT}")
    print("병합된 묶음:")
    for bn in bins:
        if len(bn["names"]) > 1:
            print(f"  {bn['wc']:>9,}  " + " + ".join(bn["names"]))


if __name__ == "__main__":
    main()
