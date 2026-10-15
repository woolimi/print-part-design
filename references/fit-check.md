# 설계 검사 하네스

부품을 만들거나 형상을 바꾸면(새 부품·재설계·출력 정리 모두) 빌드 스크립트가 같은 실행 안에서 아래 검사를 돌리고,
하나라도 걸리면 non-zero 로 끝난다. 일회성 scratch 스크립트로 확인하고 끝내지 않는다. 검사가 빌드에 들어 있어야
다음 수정에서도 다시 돈다. 공통 검사 함수는 `templates/checks.py` 에 있다(리포 `scripts/` 로 복사해 import).

## 1. 부품 하나의 검사

| 검사 | 함수 | 기준 |
|---|---|---|
| 단일 유효 solid | `one_solid(name, part)` | `status()` 가 NoError, 조각 1개. 떨어진 조각은 boolean 잔재다 |
| 베드 크기 | `fits_bed(name, part, bed)` | 출력하는 자세(눕힌 방향)의 bounding box 가 프린터 build volume 안 |
| 출력 결함 | `scripts/print_flaws.py` | strip·speck·piece·void·overhang 목록. 판정은 `print-tidy.md` 4절 |

## 2. 조립 검사

부품에 들어가는 **모터(서보)·보드·베어링·나사머리**와, 나눠 출력해 나사로 잇는 프린트 조각·핀마다 실제 메시를
조립 자세(URDF joint origin · visual origin, 또는 빌드의 배치 행렬)에 놓고 검사한다.

| 검사 | 함수 | 내용 |
|---|---|---|
| 제자리 간섭 | `overlap(a, b)` + `no_worse` | 조립 자세에서 교집합 부피(mm³). 판정은 2.1절의 기준본 대비 |
| 부품 사이 틈 | `apart(a, b, min_gap)` | 겹침이 없고 최소 거리가 `min_gap` 이상(맞물리는 조각 사이 0.3 mm 정도) |
| 홈 여유 | `apart(part, sides(housing, n, d), c)` | 앉는 면을 뺀 하우징과 몸통 옆면 사이. 옆 0.2 mm, 돌기 둘레 0.3 mm 정도. 여유 0 은 FDM 치수 오차로 안 들어간다 |
| 조립 경로 | `slides_in(name, part, placed, way)` | 넣는 방향으로 0.5 mm 씩 밀어 넣는 sweep 에서 간섭 없음. 밑면 리드 소켓 커버·horn·spline 같은 돌기와 케이블 출구를 메시에 포함한다 |
| 조립 순서 | `slides_in` 을 순서대로 | 실제 조립 순서대로 하나씩: 앞서 놓인 부품 전부가 `placed`. 완성 자세의 간섭·관절 sweep 이 다 통과해도 순서가 막힐 수 있다 |

새로 깎는 모터 홈은 옆 0.2 mm, 돌기 둘레 0.3 mm 여유로 판다. 홈을 실제 모터 메시로 깎으면(메시를 여유만큼 키워 뺌)
홈과 검사가 같은 형상을 기준으로 한다.

### 2.1 기준본 대비 판정

겹침은 0 이 아니라 **기준본 대비 증가분**으로 판정한다. 기준본은 실물로 조립되는 판이다. upstream 원본(CAD·URDF·메시)이나
이전에 출력해 조립한 판이 여기에 해당한다. upstream CAD 자체가 공칭 서보 모델과 0.2 mm 안팎으로 겹치는 일이 흔한데
(압입, 모델 차이), 그건 실물로 잘 들어간다. 그래서

1. 같은 검사를 기준본에 돌려 쌍마다 겹침 부피를 얻는다. 이 값은 config 에 상수로 둔다(`reference = {"servo in body": 13.2, …}`).
2. 새 빌드의 같은 쌍을 `no_worse(what, value, baseline)` 로 본다. 새로 생기거나 커진 겹침만 실패다.
3. 그 쌍의 `slides_in` 은 `allow=baseline` 으로 돌린다. 제자리에서 이미 겹치는 만큼은 경로에서도 허용한다.

기준본 없이 겹침 수치를 "문제"로 보고하지 않는다. 검출 계산이 맞아도 판정 기준이 틀리면 실물로 잘 들어가는 자리를
고장으로 보고하게 된다. 반대로 기준본 30 mm³ 가 재설계 뒤 184 mm³ 로 커졌다면, 그 증가분은 실물에서 서보가 안 들어가는
진짜 문제다. 판단이 안 서면 실물 조립 경험을 사용자에게 묻는다.

## 3. 빌드 스크립트 모양

```python
from checks import apart, fits_bed, no_worse, one_solid, overlap, sides, slides_in

def main() -> int:
    parts = build()                                   # name -> Manifold, placed as assembled
    write_stls(parts)                                 # the STLs are written either way
    faults = []
    for name, part in parts.items():
        faults += one_solid(name, part)
        faults += fits_bed(name, lying(name, part), SETTINGS.bed)
    faults += apart("lid", parts["lid"], "body", parts["body"], SETTINGS.min_gap)
    servo = placed_servo()                            # the real servo mesh, horn and plugs in it
    faults += no_worse("servo in body", overlap(servo, parts["body"]), SETTINGS.reference["servo in body"])
    faults += apart("servo", servo, "body sides", sides(parts["body"], (0, 0, 1), SEAT_Z), SETTINGS.servo_room)
    faults += slides_in("servo", servo, [parts["body"]], way=(0, 0, -1),
                        allow=SETTINGS.reference["servo in body"])
    for f in faults:
        print("FAIL", f)
    print("ok" if not faults else f"{len(faults)} failed")
    return 1 if faults else 0
```

- 검사마다 통과한 값도 한 줄씩 찍는다(겹침 mm³·최소 거리 mm). 다음 수정 때 기준본 값으로 바로 옮겨 쓴다.
- 조립 순서와 각 단계의 넣는 방향은 README 에 적기 전에 이 검사로 확인한다.
- 검사가 걸린 자리는 `marks.json` 에 적어 뷰어에 띄운다(`viewer.md` 2절 marks). 좌표는 부품 STL frame 이다.
