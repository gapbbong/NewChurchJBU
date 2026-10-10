# -*- coding: utf-8 -*-
"""
자막(교정본) 분류 · 통합 · 인덱스 생성기
- 입력: transcripts_clean/*.txt (헤더 # title/url/upload/bonmun + 본문)
- 출력(모두 신규, 원본 미변경):
    분류_성경책별/{NN_책이름}/파일...        (성경 순서 폴더)
    분류_예배종류별/{예배종류}/파일...
    통합_성경책별/{NN_책이름}.txt            (같은 책 설교를 날짜순 한 파일로)
    index.xlsx                              (마스터 인덱스: 정렬·필터·링크)
"""
import os
import re
import glob
import shutil
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "transcripts_clean")
DIR_BOOK = os.path.join(BASE, "분류_성경책별")
DIR_SVC = os.path.join(BASE, "분류_예배종류별")
DIR_MERGE = os.path.join(BASE, "통합_성경책별")
INDEX_XLSX = os.path.join(BASE, "index.xlsx")

# 성경 66권 정경 순서 (폴더 접두 번호용). 별칭은 매칭에서 처리.
BOOKS = [
    "창세기","출애굽기","레위기","민수기","신명기","여호수아","사사기","룻기","사무엘상","사무엘하",
    "열왕기상","열왕기하","역대상","역대하","에스라","느헤미야","에스더","욥기","시편","잠언",
    "전도서","아가","이사야","예레미야애가","예레미야","에스겔","다니엘","호세아","요엘","아모스",
    "오바댜","요나","미가","나훔","하박국","스바냐","학개","스가랴","말라기","마태복음",
    "마가복음","누가복음","요한복음","사도행전","로마서","고린도전서","고린도후서","갈라디아서","에베소서","빌립보서",
    "골로새서","데살로니가전서","데살로니가후서","디모데전서","디모데후서","디도서","빌레몬서","히브리서","야고보서","베드로전서",
    "베드로후서","요한일서","요한이서","요한삼서","유다서","요한계시록",
]
# 매칭은 긴 이름 우선(예: 예레미야애가 > 예레미야, 요한복음 > 요한일서)
BOOK_ORDER = {b: i + 1 for i, b in enumerate(BOOKS)}
BOOK_MATCH = sorted(BOOKS + ["계시록"], key=len, reverse=True)
BOOK_ALIAS = {"계시록": "요한계시록"}


def find_book(bonmun):
    for b in BOOK_MATCH:
        if b in (bonmun or ""):
            return BOOK_ALIAS.get(b, b)
    return None


# 예배 종류: 우선순위대로 키워드 검색(먼저 걸리는 것 채택)
SVC_RULES = [
    ("주일저녁예배", ["주일저녁"]),
    ("젊은이예배", ["젊은이"]),
    ("새벽예배", ["새벽예배"]),
    ("특별새벽기도", ["특별새벽", "특새", "새벽기도"]),
    ("수요예배", ["수요"]),
    ("금요철야예배", ["금요", "철야"]),
    ("주일예배", ["주일예배", "주일"]),
    ("헌신예배", ["헌신예배"]),
    ("송구영신예배", ["송구영신"]),
    ("성탄예배", ["성탄"]),
]


def find_service(title):
    t = title or ""
    for name, kws in SVC_RULES:
        if any(k in t for k in kws):
            return name
    return "기타"


def parse_file(path):
    meta = {"title": "", "url": "", "upload": "", "bonmun": ""}
    lines = open(path, encoding="utf-8").read().splitlines()
    body_start = len(lines)
    for i, ln in enumerate(lines):
        if ln.startswith("# title:"):
            meta["title"] = ln[len("# title:"):].strip()
        elif ln.startswith("# url:"):
            meta["url"] = ln[len("# url:"):].strip()
        elif ln.startswith("# upload:"):
            meta["upload"] = ln[len("# upload:"):].strip()
        elif ln.startswith("# bonmun:"):
            meta["bonmun"] = ln[len("# bonmun:"):].strip()
        elif ln.startswith("# ----- transcript"):
            body_start = i + 1
            break
    body = "\n".join(lines[body_start:]).strip()
    return meta, body


def fmt_date(upload):
    if upload and len(upload) == 8 and upload.isdigit():
        return f"{upload[:4]}-{upload[4:6]}-{upload[6:]}"
    return upload or ""


def short_title(title):
    m = re.search(r"\[([^\]]+)\]", title or "")
    return m.group(1).strip() if m else (title or "")


def main():
    for d in (DIR_BOOK, DIR_SVC, DIR_MERGE):
        os.makedirs(d, exist_ok=True)

    files = sorted(glob.glob(os.path.join(SRC, "*.txt")))
    rows = []          # 인덱스용
    by_book = {}       # 통합용: 책 -> [(upload, meta, body, fname)]

    for path in files:
        fname = os.path.basename(path)
        meta, body = parse_file(path)
        book = find_book(meta["bonmun"])
        svc = find_service(meta["title"])
        upload = meta["upload"]

        # 성경 책별 폴더 복사
        if book:
            folder = f"{BOOK_ORDER[book]:02d}_{book}"
        else:
            folder = "00_본문미상"
        dst_book = os.path.join(DIR_BOOK, folder)
        os.makedirs(dst_book, exist_ok=True)
        shutil.copy2(path, os.path.join(dst_book, fname))

        # 예배 종류별 폴더 복사
        dst_svc = os.path.join(DIR_SVC, svc)
        os.makedirs(dst_svc, exist_ok=True)
        shutil.copy2(path, os.path.join(dst_svc, fname))

        # 통합용 수집
        key = folder
        by_book.setdefault(key, []).append((upload, meta, body, fname))

        rows.append({
            "date": fmt_date(upload),
            "year": upload[:4] if len(upload) >= 4 else "",
            "svc": svc,
            "title": short_title(meta["title"]),
            "book": book or "",
            "bonmun": meta["bonmun"],
            "url": meta["url"],
            "file": fname,
        })

    # 통합 문서 작성 (책별, 날짜순)
    for key, items in by_book.items():
        items.sort(key=lambda x: (x[0] or "99999999"))
        out = os.path.join(DIR_MERGE, key + ".txt")
        with open(out, "w", encoding="utf-8") as f:
            f.write(f"# {key} 통합 ({len(items)}편)\n\n")
            for upload, meta, body, fname in items:
                f.write("=" * 70 + "\n")
                f.write(f"[{fmt_date(upload)}] {meta['title']}\n")
                f.write(f"본문: {meta['bonmun']} | {meta['url']}\n")
                f.write("=" * 70 + "\n")
                f.write(body + "\n\n")

    # 마스터 인덱스 xlsx
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "설교목록"
    headers = ["날짜", "연도", "예배종류", "제목", "성경책", "본문", "재생링크", "파일명"]
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="4472C4")
        c.alignment = Alignment(horizontal="center")
    rows.sort(key=lambda r: (r["date"], r["svc"]))
    for r in rows:
        ws.append([r["date"], r["year"], r["svc"], r["title"], r["book"],
                   r["bonmun"], r["url"], r["file"]])
        cell = ws.cell(row=ws.max_row, column=7)
        if r["url"]:
            cell.hyperlink = r["url"]
            cell.font = Font(color="0563C1", underline="single")
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:H{ws.max_row}"
    widths = [12, 6, 12, 34, 10, 22, 30, 40]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
    wb.save(INDEX_XLSX)

    # 요약 출력
    from collections import Counter
    sc = Counter(r["svc"] for r in rows)
    print(f"처리 파일: {len(rows)}")
    print(f"성경책 폴더: {len(by_book)}개 / 예배종류 폴더: {len(sc)}개")
    print(f"통합 문서: {len(by_book)}개 -> {DIR_MERGE}")
    print(f"인덱스: {INDEX_XLSX}")
    print("예배종류:", dict(sc.most_common()))


if __name__ == "__main__":
    main()
