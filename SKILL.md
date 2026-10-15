---
name: print-part-design
description: 코드(manifold3d·build123d → STL)로 3D 프린트 부품을 설계하는 리포의 하네스. 브라우저 3D 설계 뷰어(design_view.py + 동봉 partview kit — z-up, 파일 바뀌면 자동 새로고침, 클릭 좌표 probe·더블클릭 면 선택·marks·나사 표기, 외곽선, 부품 표시/숨김, 시점 버튼, 슬라이더 → 저장 → 재빌드, STEP 내보내기), 빌드에 넣는 설계 검사(단일 유효 solid·베드 크기·부품 사이 틈·서보·보드 제자리 간섭·삽입 경로 sweep·조립 순서·모터 홈 여유, 기준본 대비 판정), 출력용 형상 정리(sliver·단차·홈·떨어진 조각·쓸모없는 stock 형상·작은 overhang·teardrop 을 찾아 원인 자리에서 고침)를 한 스킬로 묶었다. "설계 뷰어 만들어줘", "3D 뷰어 띄울 수 있게 해줘", "STL 보는 뷰어", "부품 뷰어 추가", "슬라이더로 자세 바꿔보는 뷰어", "STEP 으로 뽑고 싶어", "CAD 로 넘길 수 있게", "뷰어에 표시해줘", "면 선택 기능", "서보 들어가는지 봐줘", "조립되는지 검사", "간섭 검사", "모터 홈 여유", "출력 잘 되게 다듬어줘", "자잘한 굴곡/단차 정리", "쓸데없는 형상 제거", "print 친화적으로" 같은 요청, manifold3d/STL 로 부품을 만드는 새 리포를 시작할 때, 프린트 부품의 형상을 바꿀 때마다 쓴다. 3MF·슬라이스 설정은 bambu-3mf 스킬.
---

# print-part-design — 3D 프린트 부품 설계 하네스

부품을 코드로 만드는 리포는 빌드 스크립트 하나가 부품 STL 을 쓰고, 같은 실행에서 설계 검사를 돌리고, 브라우저 뷰어가
그 STL 을 바로 그린다. 이 스킬은 그 하네스의 정본이다. 뷰어 템플릿과 뷰어 공용 kit, 빌드에 넣는 검사 함수, 출력용
형상 정리 도구와 절차가 들어 있다.

| 경로 | 내용 |
|---|---|
| `templates/design_view.py`·`config.py`·`export_step.py` | 설계 뷰어 서버 + 페이지, 설정, STL → STEP. 리포 `scripts/` 로 복사해 채운다 |
| `templates/checks.py` | 빌드의 ok 조건이 되는 검사 함수(`one_solid`·`fits_bed`·`apart`·`slides_in`·`no_worse`·`sides`) |
| `kit/` | partview 패키지. 모든 뷰어가 같이 쓰는 서버 route 와 페이지 kit(점·면 선택, marks, 나사). `pip install -e` 로 설치 |
| `scripts/print_flaws.py`·`sections.py`·`shots.js` | 출력 결함 목록, 단면 겹쳐 보기, STL 좌표를 겨냥한 Playwright 캡처 |
| `references/viewer.md` | 뷰어 세팅 절차, 기능, assembly.json 형식, STEP 변환, 운영 함정 |
| `references/fit-check.md` | 설계 검사 하네스: 무엇을 어떤 기준으로 검사하고 빌드에 어떻게 넣는지 |
| `references/print-tidy.md` | 출력용 형상 정리: 원칙, 결함 분류, 고치는 순서, 검증, manifold3d 함정 |

## 1. 리포 구조

```
scripts/config.py        # Settings 하나: 경로·포트·베드 크기·최소 틈·기준본 겹침값 (설정은 여기 한 곳)
scripts/build.py         # 부품 → print/*.stl, meshes/assembly.json, meshes/screws.json, 그리고 검사
scripts/checks.py        # templates/checks.py 복사본
scripts/design_view.py   # 뷰어 (templates/)
scripts/export_step.py   # STEP (templates/)
print/                   # 출력할 STL (출력 자세가 아니라 설계 좌표)
meshes/                  # 뷰어가 부품 옆에 그리는 것(서보·보드 메시, assembly.json, screws.json)
step/                    # 내보낸 STEP (보통 .gitignore)
marks.json               # 뷰어에 띄울 표시 (커밋 안 함)
```

좌표는 설계 frame(z-up, mm)이다. 검사·`print_flaws.py`·뷰어 probe·marks 가 모두 같은 부품 STL frame 으로 말한다.

## 2. 작업 흐름

1. **새 리포**: `templates/` 를 `scripts/` 로 복사하고 `references/viewer.md` 1절대로 뷰어를 세운다. `build.py` 는
   부품을 쓴 뒤 `checks.py` 검사를 돌리고 실패가 있으면 non-zero 로 끝나게 만든다(`references/fit-check.md` 3절).
2. **부품을 만들거나 고칠 때마다**: 빌드 → 검사 통과 → 뷰어로 확인 → 보고. 들어가는 서보·보드·베어링·나사머리마다
   실제 메시로 제자리 간섭·삽입 경로·홈 여유·조립 순서를 검사하고, 겹침은 **기준본 대비 증가분**으로 판정한다
   (`references/fit-check.md`). 묻지 않고 같은 작업 안에서 한다.
3. **출력 전 정리**: `references/print-tidy.md`. 형상은 그대로 두고 이음매 결함만 원인 자리에서 고친다. 고친 뒤
   2번 검사를 다시 돌린다.
4. **CAD 로 넘길 때**: 뷰어의 export STEP 또는 `export_step.py` 단독 실행(`references/viewer.md` 3절).
5. **출력 파일**: 3MF·재질·슬라이스 설정은 bambu-3mf 스킬(https://github.com/woolimi/bambu-3mf).

## 3. 공통 규칙

- 설정은 `config.py` 의 `Settings` 한 곳에 둔다. 경로·포트·튜닝값을 스크립트마다 따로 두거나 환경변수로 흩지 않는다.
- 설계 로직(형상·검사)은 빌드 스크립트에 두고 뷰어는 보여 주기만 한다. 뷰어가 설계 상수를 알아야 하면 빌드가
  assembly.json 으로 넘긴다.
- 검사는 빌드에 넣어 재빌드마다 돈다. scratch 스크립트로 한 번 확인하고 끝내지 않는다.
- 사용자에게 "여기"를 보여 줄 때는 `marks.json` 에 적어 열린 뷰어에 띄운다. 결함·질문할 형상·검사가 걸린 자리 모두.
- 끝났다고 말하기 전에 뷰어로 실제 화면을 찍어 본다.

## 4. 스킬 유지 규칙

이 스킬이 설계 뷰어·검사 하네스·출력 정리의 정본이다. 어느 리포에서든 이 셋을 고치면 같은 작업 안에서 여기도 고친다.

| 바뀐 것 | 반영하는 곳 |
|---|---|
| 어느 뷰어에나 같은 상호작용(선택·표시·readout) | `kit/`(`kit.js`·`server.py`). 한 뷰어에 인라인으로 넣지 않는다. `kit/README.md` 와 `references/viewer.md` 2절 표에 한 줄 |
| 어느 프로젝트에나 쓸 뷰어 기능·버그 수정(장면·서버 구조) | `templates/`. 템플릿을 scratch 프로젝트로 실제로 띄워 확인한 뒤 `references/viewer.md` 2절 표에 한 줄 |
| 새 검사 유형 | `templates/checks.py` 에 함수를 넣고 scratch 형상으로 통과·실패 둘 다 확인, `references/fit-check.md` 표에 한 줄 |
| 새 결함 유형과 처리, manifold3d 함정 | `references/print-tidy.md` 4절·8절 |
| 결함 도구 기능 추가·버그 수정 | `scripts/` 를 고치고 실제 부품에 돌려 확인 |
| 운영하다 겪은 뷰어 함정 | `references/viewer.md` 4절 |

kit 는 요청마다 패키지 파일을 읽으므로, editable 로 설치한 뷰어는 kit 를 고친 뒤 브라우저 새로고침(`kit.js`·`kit.css`)
또는 서버 재시작(`server.py`)만 하면 된다. 문서와 코드에는 특정 프로젝트 이름·머신 경로를 넣지 않는다.
