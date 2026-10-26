# 설계 뷰어

부품을 코드(manifold3d → STL)로 만드는 리포에 붙이는 브라우저 뷰어다. three.js 는 CDN import map 으로 부르고,
모든 뷰어가 같이 쓰는 부분은 스킬에 들어 있는 **partview kit**(`kit/`)에 있다. 서버 공통 route(`KitHandler`)와
페이지 kit(`/kit/kit.js`·`kit.css`)이 클릭=점, 더블클릭=면 선택, marks, 나사 표기를 맡는다. 정본 템플릿은
`templates/` 의 `design_view.py`·`config.py`·`export_step.py` 이고, kit 를 설치한 env 에서 그대로 복사하면 바로 뜬다.

| 파일 | 역할 |
|---|---|
| `templates/design_view.py` | 서버 + 페이지. `PARTS`·`SLIDERS` 만 채운다 |
| `templates/config.py` | `Settings`: title·pose_yaml·print·meshes·python·port·marks·screws. `python` 은 save 가 빌드를 돌릴 venv 이고, 없으면 뷰어를 띄운 python 을 쓴다 |
| `templates/export_step.py` | STL → STEP. 뷰어의 export STEP 버튼이 부른다. 단독 실행도 된다 |
| `kit/` | partview 패키지. API·파일 형식은 `kit/README.md` |

## 1. 세팅 절차

1. `templates/` 의 `design_view.py`·`config.py`·`export_step.py` 를 리포 `scripts/` 로 복사한다. STEP 이 필요 없으면
   `export_step.py` 는 빼도 된다(버튼이 자동으로 숨는다). 이미 `config.py` 가 있으면 `Settings` 에 `title`·`pose_yaml`·
   `print`·`meshes`·`port`·`marks`·`screws` 만 합친다. `.gitignore` 에 `marks.json` 을 넣는다.
2. 뷰어가 도는 env 에 kit 를 editable 로 설치한다: `pip install -e ~/.claude/skills/print-part-design/kit`
   (uv venv 면 `uv pip install --python .venv/bin/python -e ~/.claude/skills/print-part-design/kit`).
   requirements·README 에 한 줄 적는다.
3. 포트를 정한다. 한 머신에서 여러 뷰어를 동시에 띄우므로 다른 뷰어와 겹치지 않는 번호로 `config.py` 에 둔다.
4. `PARTS` 를 채운다: `이름: (STL 경로, 색, 그룹)`. 그룹이 `"root"` 면 설계 좌표 그대로, 다른 이름이면
   assembly.json 의 `groups[그룹]` 4×4 행렬로 놓인다.
5. 슬라이더가 필요하면 `SLIDERS` 와 `BUILD`·`POSE` 를 맞춘다. 필요 없으면 `SLIDERS = []`
   (포즈 파일이나 빌드 스크립트가 없어도 슬라이더·save 가 자동으로 숨는다).
6. 빌드 스크립트가 `meshes/assembly.json` 을 쓰게 한다(아래 형식). 나사가 들어가는 부품이면 `meshes/screws.json` 도
   쓴다(형식은 `kit/README.md`). 구멍을 뚫는 상수에서 바로 만든다.
7. `applyLive()` 의 `TODO(project)` 자리에 "live" 슬라이더가 부품을 움직이는 코드를 넣는다.
8. `CENTRE`·`views` 를 부품 크기에 맞춘다.
9. venv 에 의존성을 넣는다: 빌드용 `manifold3d numpy`, STEP 용 `cadquery-ocp`(7.8.1.1.post1 로 확인). requirements 에 적는다.
10. `step/` 을 커밋할지 정한다. 부품 STL 을 커밋하는 리포면 STEP 도 같이, 아니면 `.gitignore`.
11. 띄우고 Playwright 로 확인한다(4절).

## 2. 템플릿 기능

| 기능 | 내용 |
|---|---|
| 서버 | `ThreadingHTTPServer` 127.0.0.1, `_send` 가 항상 `no-store`. 라우트 `/` `/mesh/<name>` `/mtimes` `/assembly` `/favicon.ico` `POST /pose` `POST /step` |
| 좌표 | 설계 좌표 z-up 을 `root.rotation.x = -π/2` 로 태우고 `w2f`/`f2w` 로 변환. 단위 mm |
| 자동 새로고침 | 1초마다 `/mtimes` 를 확인해 바뀐 STL 만 다시 로드하고, `assembly` 가 바뀌면 포즈를 다시 적용. 하단 오른쪽에 "X reloaded 시각" |
| 외곽선 | `EdgesGeometry(geo, 25)` → `LineSegments2`, 공유 `LineMaterial`(resolution 은 매 프레임 갱신). outlines 체크박스 |
| 부품 표시 | 부품마다 체크박스. 숨기면 트리에서 빼서 probe 가 못 맞힌다. 체크박스를 담는 `#show` 는 `display:contents` 라 시점 버튼 줄에 가로로 놓인다 |
| 시점 | iso / front(+x) / left(+y) / top 버튼. 매 프레임 `view (카메라) -> (타깃)` 줄이 떠서 스크린샷만으로 시점을 알 수 있다 |
| 점·면 선택 (kit `picker`) | 클릭(5 px 이상 움직이면 orbit 으로 봄) → 노란 점, `probe <부품> (x,y,z) mm \| in its own frame (…)`. 더블클릭 → 그 면을 파랗게 칠하고 `face <부품> 넓이 mm2, flat/curved, normal, n.p \| box … in its own frame`. 평면은 0.5° 안으로 이어진 삼각형, 곡면(구멍·라운드)은 가는 띠 facet 끼리만 이어서 통째로 고른다. 점·면은 부품에 붙어 슬라이더로 움직여도 따라간다. 읽은 줄을 클릭하면 클립보드로 복사된다(초록 깜빡임) |
| marks (kit `marks`) | `SETTINGS.marks`(marks.json, 커밋 안 함)의 `{part, at, box?, label, note?, view?, from?, faces?}` 를 부품에 분홍 점·상자·번호로 붙인다. 좌표는 부품 STL frame mm 다. 가려도 보이고 화면상 크기가 일정하다. 목록을 클릭하면 그 부품만 진하게 남고(나머지 반투명, Esc 로 해제), 카메라는 `from`(부품 frame 방향)에 가장 가까우면서 부품에 막히지 않는 방향에서 `view` mm 거리로 간다. `faces`(부품 frame 방향)가 있으면 상자 안에서 그 방향 45° 이내를 향하는 면을 분홍으로 칠해 가려도 보이게 한다. 포켓 천장·턱 밑처럼 겉에서 안 보이는 면용이고, overhang 이면 출력 down 방향을 준다. 파일이 바뀌면 mtimes 확인으로 다시 그린다. 다른 뷰어의 부품을 가리키는 mark 는 "+N" 으로만 센다. 스크립트·Claude 가 "여기"를 사용자 화면에 보여 줄 때 쓴다 |
| 나사 (kit `screws` + picker) | 빌드가 쓴 `SETTINGS.screws`(`meshes/screws.json`)의 나사마다 구멍 속에 반투명 막대(나사산 + 머리)를 가려도 보이게 그리고 옆에 이름표(`label`)를 붙인다. 클릭한 점이 어느 나사 구멍(나사산 원통이나 머리 자리, 벽에서 1.5 mm 까지, 그 구멍이 지나는 어느 부품이든) 안이면 probe 줄 끝에 `screw: <spec> into <into>` 가 붙는다. picker 는 클릭마다 `/screws` 를 물어서, 파일이 없는 뷰어는 아무 말도 하지 않는다. screws 체크박스로 숨긴다 |
| 슬라이더 | `kind: "live"`(조립 때 정하는 값, 페이지가 바로 움직임) / `"cut"`(부품에 새겨지는 값, 저장 전까지 preview). `#stale` 줄이 둘을 구분해 알려 준다 |
| save & rebuild | 포즈 yaml 의 **숫자만** 정규식으로 바꿔 주석을 보존 → 빌드 실행(venv python) → 실패하면 yaml 을 원상복구하고 한 번 더 빌드해 실패한 빌드가 써 둔 부품도 되돌린다. 로그 창에 출력. save 는 빌드된 포즈가 슬라이더에 올라온 뒤에만 켜진다(assembly.json 이 없으면 바로 켜짐) |
| revert | 빌드된 포즈로 슬라이더 복귀 |
| export STEP | `POST /step` → `export_step.py` 실행 → 로그 창에 결과. `step/<부품>.step` 과, 이름 붙은 부품이 assembly.json 대로 배치된 `step/assembly.step`. 부품마다 `PARTS` 의 뷰어 색이 STEP 색으로 들어간다 |
| 디버그 핸들 | `window.__controls/__camera/__scene/__THREE/__parts`. Playwright 가 시점을 옮기고 상태를 읽는다 |
| 서버 공통 route (`KitHandler`) | `/kit/<file>`, `/marks`, `/screws`, `/favicon.ico`. 뷰어 Handler 는 `KitHandler` 를 상속하고 `do_GET` 첫 줄에서 `if self.kit(path): return`. 응답은 `self.send_body(body, ctype, status)` |
| 테마 | 배경 `#16181c`, 글자 `#cfd2d8`, 버튼 `#2a2d33`/`#3a3e45`, 축 x `#e05252` y `#3ec46d` z `#5277e0`, probe `#8fb4e8`, 강조 노랑 `#f2e14c` |

### assembly.json 형식 (빌드가 씀)

```json
{ "pose":    {"angle": 20, "length": 150},
  "groups":  {"arm": [[1,0,0,0],[0,1,0,0],[0,0,1,20],[0,0,0,1]]},
  "sliders": {"length": {"min": 100, "max": 300, "step": 10}} }
```

`pose` 는 빌드된 값(변경 감지 기준), `groups` 는 설계 좌표 안 배치, `sliders` 는 빌드가 아는 범위
(톱니 피치·구멍 간격처럼 설계에서 나오는 값)로 페이지의 min/max/step 을 덮어쓴다.

같은 조립을 여러 벌 나란히 볼 때(형상은 같고 끼우는 부품만 다른 경우)는 부품 STL 을 하나로 두고, `PARTS` 를
`<부품>_<벌>` 로 늘려 벌마다 그룹을 주고, 빌드가 벌마다 x 로 띄운 `groups` 행렬을 쓴다.

## 3. STEP 변환

- 부품이 메시(STL)라서 **파라메트릭 STEP 이 아니다.** 삼각형을 꿰매(`BRepBuilderAPI_Sewing`, 0.001 mm) 솔리드로
  만들고, `ShapeFix_Solid` 로 boolean 연산이 남긴 극세 조각을 고친 뒤, `ShapeUpgrade_UnifySameDomain` 으로 같은 평면의
  삼각형을 한 면으로 합친다. 평면은 진짜 평면(박스 → 면 6개)이 되고 원통·톱니는 다각면으로 남는다.
- 합친 결과가 `BRepCheck_Analyzer` 를 통과하지 못하면 합치기 전 솔리드를 쓴다(면은 많아도 유효).
- 확인값: 8220 삼각형 부품 → 3400 면 5.9 s, 4444 → 1079 면, 5072 → 2922 면. 전부 유효 솔리드이고 부피가 원본과
  같다. 조립 STEP 을 다시 읽으면 부품 배치가 그대로다. 변환 뒤에는 솔리드 수·유효성·부피를 STL 과 대조한다.
- 원통을 진짜 원통 면으로 원하면(치수 재기 쉬운 CAD 모델) 부품을 처음부터 CadQuery/build123d 로 설계한다.
  그런 B-rep 부품이면 `export_step.py` 자리에 같은 이름으로, 빌드 solid 를 메시 변환 없이 그대로 쓰고 이름·색을 붙인
  조립 Compound 를 만드는 스크립트를 둔다. 같은 solid 를 여러 파일에 넣을 때는 `moved(Location())` 복사본에
  label·color 를 붙인다. manifold3d 메시에서 원통을 되살리는 건 범위 밖이다.
- 크기·시간: 7부품 조립 STEP 이 30 MB, 약 30 s. `step/` 은 보통 `.gitignore` 에 넣는다.
- OCCT 는 전송 통계를 fd 1 에 직접 찍으므로 `quiet()` 로 막아 둔다(로그 창이 지저분해지지 않게).

## 4. 확인과 운영

- **띄우기**: Linux 는 `(setsid nohup .venv/bin/python scripts/design_view.py > /dev/null 2>&1 &)` 후
  `curl -s -o /dev/null -w "%{http_code}" http://localhost:<port>/` 가 200 인지 본다. macOS 에는 `setsid` 가 없어 셸이
  바로 실패하므로 `(nohup ... > log 2>&1 &)` 로 띄운다. conda env 의 python 을 경로로 직접 부르면 그 env 의 `bin`
  (xacro 등)이 PATH 에 없으니 `PATH=<env>/bin:$PATH` 를 붙인다.
- 디버그 핸들(`window.__camera/__controls/__THREE` + 부품 목록)은 템플릿 밖의 뷰어에도 둔다. `scripts/shots.js` 가
  이것으로 STL 좌표를 겨냥해 캡처한다(부품 목록을 `__visuals` 배열로 두는 뷰어도 받는다).
- `pkill -f` 가 종료코드 144 로 셸을 끊는 경우가 있으니 **끄기와 띄우기를 다른 명령으로** 나누고, 끈 뒤에는
  `ss -ltn | grep <port>`(macOS 는 `lsof -iTCP:<port> -sTCP:LISTEN`)로 확인한다.
- **페이지나 PARTS 를 고쳤으면 서버를 재시작한다.** `PAGE` 문자열과 `PARTS` 는 시작할 때 메모리에 올라가서, STL 은
  자동으로 새로고침돼도 HTML·JS·부품 목록 수정은 재시작 전까지 안 보인다. kit(`kit.js`·`kit.css`)는 요청마다 패키지
  파일을 읽으므로 브라우저 새로고침만으로 반영된다.
- 서버를 상대 경로(`python scripts/design_view.py`)로 띄우면 `pkill -f <절대경로>` 가 안 맞는다.
  `lsof -tiTCP:<port> -sTCP:LISTEN` 으로 PID 를 찾아 끈다.
- **Playwright 확인**: `browser_navigate` → 3초 대기 → `browser_evaluate` 로 `window.__camera.position.set(...)`,
  `__controls.target.set(...)`, `__controls.update()` 로 보고 싶은 시점을 잡고 `browser_take_screenshot`.
  world 좌표는 `(x, z, -y)` 다(설계 z-up). 콘솔 에러도 `browser_console_messages` 로 확인한다. 스크린샷은
  `.playwright-mcp/` 아래에 저장되니 리포 `.gitignore` 에 넣는다.
- 헤드리스 소프트웨어 GL 에서 `browser_take_screenshot` 이 타임아웃 나면 페이지가 캔버스를 직접 내보내게 한다.
  `__snap()` 이 `renderer.render` 후 `toDataURL` 을 돌려주게 두고, `browser_evaluate` 결과를 base64 로 풀어 PNG 로 저장한다.
- 슬라이더 값은 **min/max 를 먼저, value 를 나중에** 넣는다. range input 은 기존 범위로 값을 잘라 버린다
  (HTML 기본 max 270 이 남은 채로 280 을 넣으면 270 이 된다).
- 페이지를 연 직후 save 를 누르면 슬라이더의 HTML 기본값이 포즈 파일에 저장된다. 템플릿은 save 를 `disabled` 로
  시작해 assembly 를 읽은 뒤에 켠다. Playwright 로 슬라이더를 바꿀 때도 `__parts` 가 찬 뒤(몇 초 기다린 뒤)에 바꾼다.
- 페이지의 부품 표는 서버의 `PARTS` 에서 만든다. 서버 목록과 페이지 목록을 따로 두면 한쪽에만 있는 부품이 mtime
  확인 때 예외를 낸다.
- 설계 로직(빌드·충돌 검사)은 빌드 스크립트에 두고 뷰어는 보여 주기만 한다. 뷰어가 설계 상수를 알아야 하면
  하드코딩하지 말고 assembly.json 으로 받는다. 서버 값을 페이지에 넣을 때는 템플릿의 `__PARTS__` 처럼 `/` 요청마다
  `replace` 한다.
