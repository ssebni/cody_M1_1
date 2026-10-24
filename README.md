# Threads Insight M1-1

2026년 10월 24일 Threads API로 다시 수집한 게시물 105개 중 유효 인사이트 103개를 분석했다. **필수 유효 표본 100개 요건을 충족했다.** 기존 79개에서 신규 유효 게시물 24개를 추가했다. 결과는 [REPORT.md](REPORT.md)를 참고한다.

## 실행

Python 3.12.14에서 실행을 확인했다. 고정한 라이브러리 버전에 맞춰 Python 3.12 이상을 권장한다. 과제의 Python 3.10 이상 조건에 부합한다. 프로젝트 폴더로 이동한 뒤 실행한다.

```sh
python -m venv .venv
python -m pip install -r requirements.txt
python analysis.py
```

가상환경은 운영체제에 맞게 활성화한 후 설치·실행한다. 기본 입력은 `data/threads_insights.csv`이며 다른 입력은 다음과 같이 지정한다.

```sh
python analysis.py --input path/to/threads_insights.csv
```

이전 스냅샷과 비교하려면 선택적으로 다음 명령을 사용한다. 이전·현재 원본 CSV는 로컬에서 별도로 준비한다.

```sh
python analysis.py --input data/threads_insights.csv --baseline path/to/previous_snapshot.csv
```

이번 실행은 이전 2026-10-18 스냅샷과 비교했다. 결과는 `results/snapshot_comparison.json` 및 리포트의 이전 스냅샷 비교 절에 포함했다. `--baseline`을 생략하면 현재 스냅샷 분석만 수행한다.

실행하면 `images/`의 PNG 4개, `results/`의 분석 CSV·품질 JSON, `REPORT.md`를 갱신한다. 원본은 덮어쓰지 않는다. 날짜 누락은 0으로 채우지 않으며 결측 지표를 가진 게시물은 성과 분석에서 제외한다. 고유 ID가 중복되면 임의로 삭제하지 않고 실행을 중단한다.

## 데이터 출처와 수집 방법 기록

- 입력 출처: 분석자 본인의 Threads 계정.
- 수집 방법: Threads API로 본인 계정의 게시물과 인사이트를 수집해 CSV로 저장.
- 수집 대상 범위: 계정 생성 이후 API가 반환하는 본인 게시물 전체를 2026년 10월 24일까지 조회. 삭제·비공개 게시물까지 포함한 계정 전체 이력의 완전성을 보장하지는 않는다.
- 현재 게시 범위: 2026-10-02 17:02:51~2026-10-24 13:11:50, KST.
- 현재 수집 일시: 2026-10-24 14:02:25~14:03:49, KST.
- 필수 컬럼: `post_id,timestamp,text,media_type,views,likes,replies,reposts,quotes,status,collected_at`.
- 인코딩: UTF-8. 본문 줄바꿈은 CSV 따옴표 규칙에 따라 보존한다.
- `post_id`는 문자열, 시각은 시간대가 있는 ISO 형식, 성과 지표는 0 이상의 정수다.
- 수집 구현: `collect_threads.py`에서 Threads Graph API v1.0의 `GET /me/threads`를 최대 100개씩 조회하고 `paging.cursors.after`로 마지막 페이지까지 순회한다. 고유 게시물 ID별 `GET /{post_id}/insights`에서 `views,likes,replies,reposts,quotes`를 조회한다. 실제 사용한 접근 토큰의 권한 구성은 공개하지 않는다.
- 접근 토큰 등 인증 정보는 저장소에 포함하지 않는다.
- 공개 범위: 게시물 원문 CSV와 행 단위 파생 데이터는 GitHub 공개 대상에서 제외한다. 과제의 '데이터 또는 수집 방법 문서' 조건에 따라 수집 방법을 공개하고 코드·집계 결과·시각화·리포트를 포함한다. 이는 원본 데이터의 재배포 라이선스를 부여한다는 의미가 아니다. 공개 데이터 없이 기본 실행을 재현하려면 같은 스키마의 로컬 CSV를 별도로 준비해야 한다.

## API 일회 수집

본인 계정에 접근 가능한 토큰을 환경변수 `THREADS_ACCESS_TOKEN`에 설정한 뒤 실행한다. 토큰을 소스 코드·문서·CSV에 적거나 커밋하지 않는다. 수집 코드는 Python 표준 라이브러리만 사용한다.

```sh
python collect_threads.py
python analysis.py
```

기본 출력은 Git 제외 대상인 `data/threads_insights.csv`다. 완료 시 로컬 파일을 교체하므로 이전 스냅샷을 보존하려면 다른 출력 경로를 사용한다.

```sh
python collect_threads.py --output data/threads_insights_next.csv
```

정상 응답의 5개 성과 지표가 모두 정수로 확보되면 `success`, 일부 미제공이면 `empty`, 개별 게시물의 비인증·비할당량 오류이면 `error`로 남긴다. 인증·권한·호출 한도 오류에서는 중단하며 기존 CSV를 교체하지 않는다. 반복·예약 수집이나 게시물 발행 기능은 없다.

## 표본 업데이트

1. 기존 데이터와 새 데이터를 고유 `post_id`로 대조한다. 반복 수집 값은 최신 스냅샷 선택 기준을 정한 뒤 별도 보관한다.
2. 완전한 인사이트가 있는 고유 게시물 100개 이상인지 확인한다. 이번에는 103개로 충족했다. 반복 수집 횟수나 성과 지표의 개수를 곱해 표본 수를 늘려 세지 않는다.
3. 코드를 다시 실행하고 결과와 해석을 검토한다. 날짜 범위가 충분한지, 새 게시물의 관측 시간이 짧지 않은지도 함께 확인한다.
4. AI 사용 로그에 실제로 수행한 작업·이유·검증 내용을 추가하고 본인이 결과를 설명할 수 있는지 확인한다.
5. GitHub 저장소에 코드·REPORT.md·이미지·requirements.txt·README·허용되는 데이터 또는 수집 방법을 포함한다.

## 제출 기준 점검

- [x] 분석 질문 3개 이상
- [x] 품질 점검 및 결측·이상치 처리 기준
- [x] 시계열 기법 2가지 이상: 일별 집계, 3일 이동평균, 일별 집단 간 변화율
- [x] 시각화 2개 이상: PNG 4개
- [x] 그래프 근거를 포함한 인사이트 3개, 관찰과 해석 분리
- [x] Python 코드, 실행 방법, 의존성, AI 사용 로그
- [x] 유효 표본 100개 이상: 103개
- [x] 본인 계정·Threads API 수집 방법 및 인증 정보·원문 비공개 방침 기록
- [x] 수집 종료일 확정: 2026-10-24, 전체 105개·유효 103개로 갱신
- [x] GitHub 저장소에 코드·리포트·그래프·수집 방법 정리

웹 대시보드와 시계열 분해·예측은 보너스이며 이번 작업 범위에 포함하지 않았다. 본인이 그래프와 인사이트를 이해하고 설명하는 학습 검증은 별도로 진행한다.
