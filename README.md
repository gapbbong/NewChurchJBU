# 홍대새교회 설교 자막 수집 & 교정

유튜브 재생목록(영상 1473개)의 자막을 모두 내려받아 텍스트로 저장하고,
무료로 오탈자/띄어쓰기를 교정하는 도구.

## 구성 파일
- `fetch_transcripts2.py` : **자막 수집기(권장, yt-dlp 기반)** — 차단에 강함
- `fetch_transcripts.py`  : 구버전(youtube-transcript-api). 참고용, IP 차단 잘 남
- `correct_transcripts.py`: 자막 교정기(kiwipiepy, 완전 무료·오프라인)
- `organize.py`           : 분류·통합·인덱스 생성기 (교정본을 성경책별/예배종류별 폴더로 복사 + 책별 통합문서 + index.xlsx)
- `replacements.json`     : 자주 틀리는 용어 치환표 (직접 추가해서 품질 향상)
- `playlist.json`         : 재생목록 1473개 (id/title) 캐시
- `metadata.jsonl`        : 영상별 제목/재생링크/업로드일/**본문(성경구절)**/설명문 집계 (한 줄=한 영상)
- `transcripts/`          : 수집된 원본 자막 (헤더에 링크·본문·설명 포함)
- `transcripts_clean/`    : 교정된 자막 (헤더 그대로 보존)
- `progress.log` / `clean.log` : 진행 로그
- `failed.tsv`            : 실패 목록 (나중에 재시도용)

---

## 1) 자막 수집

### (권장) 로그인 쿠키로 실행 — 차단 최소화
YouTube는 로그인 안 한 대량 요청을 막습니다. 아래처럼 쿠키를 한 번만 내보내세요.

1. Chrome 확장 **"Get cookies.txt LOCALLY"** 설치
2. youtube.com 에 **로그인된 상태**에서 확장 아이콘 클릭 → **Export** → `cookies.txt` 저장
3. 그 파일을 이 폴더(`E:\NewChurchJBU\cookies.txt`)에 두기
4. 실행:
```powershell
$env:PYTHONUTF8=1
python E:\NewChurchJBU\fetch_transcripts2.py --cookiefile E:\NewChurchJBU\cookies.txt
```

### 쿠키 없이 실행 (느리고 차단 가능성 큼)
```powershell
$env:PYTHONUTF8=1
python E:\NewChurchJBU\fetch_transcripts2.py
```

### 백그라운드로 실행 (창 닫아도 계속 돌아감)
```powershell
$env:PYTHONUTF8=1
$p = Start-Process python -ArgumentList "E:\NewChurchJBU\fetch_transcripts2.py --cookiefile E:\NewChurchJBU\cookies.txt" `
     -WorkingDirectory "E:\NewChurchJBU" `
     -RedirectStandardOutput "E:\NewChurchJBU\run_stdout.log" `
     -RedirectStandardError "E:\NewChurchJBU\run_stderr.log" `
     -WindowStyle Hidden -PassThru
$p.Id | Out-File E:\NewChurchJBU\run.pid -Encoding ascii
```

### 진행 확인 / 중지 / 재개
```powershell
# 진행 로그
Get-Content E:\NewChurchJBU\progress.log -Tail 10 -Encoding UTF8
# 완료 개수 (/1473)
(Get-ChildItem E:\NewChurchJBU\transcripts).Count
# 중지
Stop-Process -Id (Get-Content E:\NewChurchJBU\run.pid) -Force
# 재개: 같은 명령 다시 실행 → 이미 받은 건 자동으로 건너뜀(이어받기)
# 실패분만 재시도
python E:\NewChurchJBU\fetch_transcripts2.py --cookiefile E:\NewChurchJBU\cookies.txt --retry-failed
```

**멈춤 방지 설계**: 이어받기 + 요청 간 10~18초 대기 + 429/차단 시 지수 백오프 재시도 +
영상 하나 실패해도 전체가 멈추지 않고 `failed.tsv`에 기록 후 계속 진행.

**각 자막 파일 헤더 예시**:
```
# title: 20180703_새벽예배_[예수님의 융통성]_...
# url: https://youtu.be/bGtvEX0cUS8
# upload: 20180703
# bonmun: 요한복음 2장 1~11절      ← 본문(제목/설명문에서 자동 추출)
# lang: ko
# ----- description -----
# 본문 : 요한복음 2장 1~11절
# 홈페이지 : http://www.new-church.com/
# ----- transcript -----

(자막 본문...)
```
본문만 한눈에 모아 보려면 `metadata.jsonl` 사용:
```powershell
Get-Content E:\NewChurchJBU\metadata.jsonl -Encoding UTF8 | ForEach-Object { ($_ | ConvertFrom-Json).bonmun }
```

---

## 2) 오탈자 교정 (무료)
수집이 끝난 뒤(또는 도중에도) 실행. `transcripts/` → `transcripts_clean/`.
```powershell
$env:PYTHONUTF8=1
python E:\NewChurchJBU\correct_transcripts.py
```
- **하는 것**: 자막 조각을 문장으로 이어붙임 + 띄어쓰기 교정 + 치환표 용어 교정 + 문장별 줄바꿈
- **한계**: 음성인식 자체 오류(예: "표적"→"표정")는 못 고침 → 그건 LLM 필요.
  검색·자료 정리 용도에는 이 정도로 충분.
- **품질 올리기**: `transcripts_clean/`를 훑어보고 반복되는 오인식 단어를
  `replacements.json`에 `"틀린표기": "바른표기"` 로 추가한 뒤 다시 실행.
  (이미 교정된 파일을 다시 만들려면 `transcripts_clean/`의 해당 파일 삭제 후 실행)

---

## 3) 분류 · 통합 · 인덱스
교정본(`transcripts_clean/`)을 여러 방식으로 정리. 원본은 건드리지 않고 새 폴더에 복사.
```powershell
$env:PYTHONUTF8=1; python E:\NewChurchJBU\organize.py
```
생성물:
- `분류_성경책별/{NN_책이름}/`  : 성경 순서 폴더(01_창세기 … 66_요한계시록, 00_본문미상)
- `분류_예배종류별/{예배종류}/` : 새벽예배/주일예배/수요예배/금요철야예배/… /기타
- `통합_성경책별/{NN_책이름}.txt` : 같은 성경책 설교를 날짜순 한 파일로 통합
- `index.xlsx` : 마스터 인덱스(날짜·연도·예배종류·제목·성경책·본문·재생링크·파일명). 자동필터·링크 포함.

분류 규칙(성경책=본문에서, 예배종류=제목 키워드)은 `organize.py` 상단 `BOOKS`/`SVC_RULES`에서 조정.
재실행하면 폴더/통합/인덱스를 다시 생성(덮어씀).
