"""Reproduce the Threads M1-1 exploratory analysis from a CSV snapshot."""
from pathlib import Path
import argparse
import json
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
METRICS = ['views', 'likes', 'replies', 'reposts', 'quotes']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, default=ROOT / 'data/threads_insights.csv')
    parser.add_argument('--baseline', type=Path, help='Optional previous CSV snapshot for comparison')
    args = parser.parse_args()
    raw = pd.read_csv(args.input, dtype=str, encoding='utf-8-sig')
    required = ['post_id', 'timestamp', 'text', 'media_type', *METRICS, 'status', 'collected_at']
    missing_columns = sorted(set(required) - set(raw.columns))
    if missing_columns:
        raise ValueError(f'Missing columns: {missing_columns}')
    if raw.post_id.isna().any() or raw.post_id.duplicated().any():
        raise ValueError('Missing/duplicate post IDs; reconcile snapshots before analysis.')
    d = raw.copy()
    for col in METRICS:
        d[col] = pd.to_numeric(raw[col], errors='coerce')
        invalid = raw[col].notna() & d[col].isna()
        if invalid.any() or (d[col].dropna() < 0).any() or (d[col].dropna() % 1 != 0).any():
            raise ValueError(f'Invalid count in {col}')
    for col in ['timestamp', 'collected_at']:
        d[col] = pd.to_datetime(raw[col], utc=True, errors='raise').dt.tz_convert('Asia/Seoul')
        if d[col].isna().any():
            raise ValueError(f'Missing {col}')
    if (d.collected_at < d.timestamp).any():
        raise ValueError('Collection precedes posting.')
    valid = d.status.eq('success') & d[METRICS].notna().all(axis=1)
    clean = d.loc[valid].sort_values('timestamp').copy()
    if clean.empty or (clean.views <= 0).any():
        raise ValueError('Need valid posts with positive views for rate comparisons.')
    clean['age_hours'] = (clean.collected_at - clean.timestamp).dt.total_seconds() / 3600
    clean['interactions'] = clean[METRICS[1:]].sum(axis=1)
    clean['interaction_rate_pct'] = clean.interactions / clean.views * 100
    clean['date'] = clean.timestamp.dt.normalize()
    # Missing days remain NA: no evidence that a missing date means no posts.
    dates = pd.date_range(d.timestamp.min().normalize(), d.timestamp.max().normalize(), freq='D')
    daily = clean.groupby('date').agg(posts=('post_id', 'size'), median_views=('views', 'median'),
                                      total_views=('views', 'sum')).reindex(dates)
    # Require 3 populated consecutive calendar days; never bridge unknown gaps.
    daily['median_views_ma3'] = daily.median_views.rolling(3, min_periods=3).mean()
    daily['median_views_change_pct'] = daily.median_views.pct_change(fill_method=None) * 100
    daily['partial_boundary_day'] = (daily.index == dates[0]) | (daily.index == dates[-1])
    groups = clean.groupby('media_type').agg(n=('post_id', 'size'), median_views=('views', 'median'),
                    mean_views=('views', 'mean'), median_rate=('interaction_rate_pct', 'median'))
    images = ROOT / 'images'
    results = ROOT / 'results'
    images.mkdir(exist_ok=True)
    results.mkdir(exist_ok=True)
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 11, 'axes.spines.top': False,
                         'axes.spines.right': False, 'figure.dpi': 140})
    labels = daily.index.strftime('%m-%d')
    x = np.arange(len(daily))
    fig, ax = plt.subplots(figsize=(11, 4.8), layout='constrained')
    ax.plot(x, daily.median_views, 'o-', color='#2563eb', label='Daily cohort median')
    ax.plot(x, daily.median_views_ma3, 's-', color='#ea580c', label='3-calendar-day moving average')
    ax.set(yscale='log', ylabel='Cumulative views per post (log scale)', xlabel='Posting date (KST)',
           title='Views by posting-date cohort | one collection snapshot')
    ax.set_xticks(x[::2], labels[::2]); ax.grid(axis='y', alpha=.2); ax.legend()
    fig.savefig(images / '01_daily_cohort_trend.png'); plt.close(fig)
    fig, ax = plt.subplots(figsize=(11, 4.8), layout='constrained')
    changes = daily.median_views_change_pct
    ax.bar(x, changes, color=['#2563eb' if pd.notna(v) and v >= 0 else '#dc2626' for v in changes])
    ax.axhline(0, color='#64748b', lw=1)
    ax.set_xticks(x[::2], labels[::2]); ax.grid(axis='y', alpha=.2)
    ax.set(xlabel='Posting date (KST)', ylabel='Change from previous calendar day (%)',
           title='Change in daily cohort median | not daily account view growth')
    fig.savefig(images / '02_daily_cohort_change.png'); plt.close(fig)
    ranked = clean.sort_values('views', ascending=False)
    cumulative = ranked.views.cumsum() / ranked.views.sum() * 100
    fig, ax = plt.subplots(figsize=(9, 4.8), layout='constrained')
    ranks = np.arange(1, len(clean)+1)
    ax.plot(ranks, cumulative, color='#2563eb', lw=2)
    for k in sorted(set([1, min(5, len(clean))])):
        val = cumulative.iloc[k-1]
        ax.scatter(k, val, color='#ea580c', zorder=3)
        ax.annotate(f'Top {k}: {val:.1f}%', (k, val), xytext=(12, -15 if k==1 else 8), textcoords='offset points')
    ax.set(xlabel='Posts ranked by views', ylabel='Cumulative share of views (%)', ylim=(0, 105),
           title=f'View concentration across {len(clean)} valid posts')
    ax.grid(alpha=.2); fig.savefig(images / '03_view_concentration.png'); plt.close(fig)
    fig, ax = plt.subplots(figsize=(9, 4.8), layout='constrained')
    ax.bar(groups.index, groups.median_views, color=['#64748b', '#2563eb', '#0d9488'][:len(groups)])
    for i, row in enumerate(groups.itertuples()):
        ax.text(i, row.median_views, f'{row.median_views:,.0f}\nn={row.n}', ha='center', va='bottom')
    ax.set_ylim(0, groups.median_views.max()*1.3)
    ax.set(ylabel='Median cumulative views', title='Content-type comparison | unequal age and sample size')
    fig.savefig(images / '04_media_comparison.png'); plt.close(fig)
    daily.to_csv(results / 'daily_cohorts.csv', index_label='date', encoding='utf-8-sig')
    groups.to_csv(results / 'media_summary.csv', encoding='utf-8-sig')
    clean.to_csv(results / 'cleaned_posts.csv', index=False, encoding='utf-8-sig')
    q1, q3 = clean.views.quantile([.25, .75])
    upper = q3 + 1.5*(q3-q1)
    summary = {'rows':len(d), 'valid':len(clean), 'columns':list(raw), 'missing':raw.isna().sum().to_dict(),
               'collection_start':d.collected_at.min().isoformat(), 'collection_end':d.collected_at.max().isoformat(),
               'post_start':d.timestamp.min().isoformat(), 'post_end':d.timestamp.max().isoformat(),
               'view_total':int(clean.views.sum()), 'view_median':float(clean.views.median()),
               'top1_share_pct':float(cumulative.iloc[0]), 'top5_share_pct':float(cumulative.iloc[min(4,len(clean)-1)]),
               'iqr_upper':float(upper), 'iqr_high_count':int((clean.views > upper).sum()),
               'valid_sample_requirement_met':len(clean)>=100}
    (results / 'quality_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    quality_rows = '\n'.join(f'| `{c}` | {int(raw[c].isna().sum())} |' for c in required)
    media_rows = '\n'.join(f'| {k} | {int(v.n)} | {v.median_views:,.0f} | {v.mean_views:,.0f} | {v.median_rate:.2f}% |' for k,v in groups.iterrows())
    media_observation = '; '.join(f'{k} {int(v.n)}개: {v.median_views:,.0f}회' for k,v in groups.iterrows())
    nonempty = changes.dropna()
    max_day = nonempty.idxmax().strftime('%m-%d') if len(nonempty) else '산출 불가'
    max_change = f'{nonempty.max():,.1f}%' if len(nonempty) else '산출 불가'
    incomplete = d.loc[~valid]
    incomplete_types = incomplete.media_type.value_counts().to_dict()
    comparison_text = ''
    if args.baseline:
        before = pd.read_csv(args.baseline, dtype=str, encoding='utf-8-sig')
        if before.post_id.isna().any() or before.post_id.duplicated().any():
            raise ValueError('Baseline contains missing/duplicate IDs')
        before_metrics = before[METRICS].apply(pd.to_numeric, errors='raise')
        prior = before.loc[before.status.eq('success') & before_metrics.notna().all(axis=1)].copy()
        prior['views'] = pd.to_numeric(prior.views)
        common_ids = set(prior.post_id) & set(clean.post_id)
        previous_views = prior.loc[prior.post_id.isin(common_ids), 'views'].sum()
        current_views = clean.loc[clean.post_id.isin(common_ids), 'views'].sum()
        added_valid = clean.loc[~clean.post_id.isin(before.post_id)]
        comparison = {'previous_rows':len(before), 'previous_valid':len(prior),
                      'current_rows':len(d), 'current_valid':len(clean),
                      'new_unique_posts':len(set(d.post_id)-set(before.post_id)),
                      'new_valid_posts':len(added_valid), 'common_valid_posts':len(common_ids),
                      'common_previous_views':int(previous_views), 'common_current_views':int(current_views),
                      'new_valid_views':int(added_valid.views.sum())}
        (results / 'snapshot_comparison.json').write_text(json.dumps(comparison, indent=2), encoding='utf-8')
        comparison_text = f'''### 이전 스냅샷과 비교
- 이전 게시물 {len(before)}개·유효 {len(prior)}개에서 현재 게시물 {len(d)}개·유효 {len(clean)}개로 갱신했다.
- 이전 파일에 없던 신규 유효 게시물은 {len(added_valid)}개다.
- 공통 유효 게시물 {len(common_ids)}개의 누적 조회수는 {int(previous_views):,}회에서 {int(current_views):,}회로 변했다.
- 신규 유효 게시물 조회수 합계는 {int(added_valid.views.sum()):,}회다. 전체 조회수의 차이에는 기존 게시물 누적 증가와 새 게시물 추가가 섞여 있어 분리해 제시했다.
'''
    report = f'''# Threads Insight M1-1 분석 리포트

## 1. 분석 주제 및 선정 이유
Threads 게시 날짜별 성과 패턴과 콘텐츠 유형별 차이를 분석한다. 관심 있는 실제 게시물 데이터로 조회수의 집중도와 반응 특성을 확인하고 다음 콘텐츠 실험의 근거를 마련한다.

**갱신일: {d.collected_at.max():%Y-%m-%d}, 진행 상태: {'유효 표본 100개 요건 충족' if len(clean)>=100 else '필수 표본 요건 미충족'}.** 전체 {len(d)}개, 유효 인사이트 {len(clean)}개다. 데이터 포인트는 성과 지표가 완전한 고유 게시물 1개로 정의한다. {'추가 표본 확보 요건을 충족했다.' if len(clean)>=100 else f'현재 최소 {100-len(clean)}개의 유효 게시물을 추가 확보해야 한다.'} 시각화용 일별 집계의 관측 수와 고유 게시물 수는 구분한다.

## 2. 분석 질문
1. 게시 날짜별 조회수 중앙값은 어떻게 변하며, 3일 이동평균에서 어떤 패턴이 보이는가?
2. 인접한 게시 날짜 집단 사이에서 조회수 중앙값의 변화가 큰 구간은 언제인가?
3. 전체 조회수는 소수 게시물에 얼마나 집중되어 있는가?
4. 텍스트·이미지·캐러셀의 조회수와 상호작용률은 어떻게 다른가?

## 3. 데이터 설명 및 품질
- 출처: 분석자 본인의 Threads 계정. Threads API를 사용해 게시물과 인사이트를 수집한 CSV다.
- 수집 대상 범위: 본인 계정에서 API가 반환하는 게시물 전체를 페이지네이션으로 조회했다. 이번 수집 종료일은 {d.collected_at.max():%Y년 %m월 %d일}이다. 아래 게시 기간은 현재 CSV의 실제 관측 범위이며, 계정 생성일 또는 삭제·비공개 게시물까지의 완전성을 뜻하지 않는다.
- 원본: `data/threads_insights.csv`. 원본 파일은 보존하고 분석용 사본을 사용한다.
- 게시 기간(KST): {d.timestamp.min():%Y-%m-%d %H:%M:%S} ~ {d.timestamp.max():%Y-%m-%d %H:%M:%S}.
- 수집 기간(KST): {d.collected_at.min():%Y-%m-%d %H:%M:%S} ~ {d.collected_at.max():%Y-%m-%d %H:%M:%S}.
- 중복 ID 없음. 값이 있는 성과 지표의 비수치·음수·소수 없음. 게시·수집 시각 파싱 및 선후 관계 확인.
- 성과 분석은 `status=success`이고 5개 지표가 모두 있는 {len(clean)}개만 사용한다. 결측 지표를 0으로 대체하지 않는다.
- ID는 문자열로 읽어 17자리 숫자의 정밀도 손실을 방지한다.

| 컬럼 | 결측 수 |
|---|---:|
{quality_rows}

현재 성과 분석에서 제외한 행은 {len(incomplete)}개이며 유형별 건수는 {incomplete_types}다. 상태별 전체 건수는 {d.status.value_counts().to_dict()}다. 유형별 미제공 여부는 추가 확인이 필요하다. 날짜가 없는 구간도 실제 미게시인지 수집 누락인지 확인되지 않았으므로 0으로 채우지 않고 결측 구간으로 표시한다. 첫날·마지막 날은 완전한 일 단위 수집 범위가 아닐 수 있어 경계일로 표시한다.

조회수 IQR 상한은 {upper:,.1f}회이며 초과 게시물은 {int((clean.views>upper).sum())}개다. 실제 확산 가능성이 있어 제거하거나 상한으로 치환하지 않았다. 재게시·인용은 0이 많아 IQR=0일 수 있으므로 이 기준으로 양수 값을 일괄 제거하지 않는다.

## 4. 시계열 분석 방법
이번 데이터는 **게시 날짜가 다른 게시물의 누적 성과를 한 번 수집한 스냅샷**이다. 시간 축은 게시일이며 실제 일별 신규 조회수나 같은 게시물의 성장 곡선이 아니다. 원본 {len(d)}행을 {len(d)}일의 일별 시계열로 간주하지 않는다.

KST의 달력 날짜를 집계 단위로 사용했다. {len(dates)}개 달력일 범위에서 일별 게시 집단의 차이를 확인하기 위한 선택이다. 유효 게시물이 있는 날짜는 {int(daily.posts.notna().sum())}일이다. 주별·월별 집계로는 비교 구간이 너무 적다.

1. **일별 구간 통계:** 게시 날짜별 게시물 수와 누적 조회수 중앙값을 계산한다. 극단값의 영향을 줄이기 위해 중앙값을 대표 지표로 사용한다.
2. **3일 이동평균:** 일별 중앙값에 연속 3개 달력일의 산술평균을 적용한다. 3일 중 값이 하나라도 없으면 계산하지 않아 누락 구간을 건너 연결하지 않는다.
3. **일별 변화율:** `(당일 중앙값 / 전일 중앙값 - 1) × 100`을 계산한다. 전일이 없으면 결측으로 남긴다. 이는 서로 다른 게시 집단 사이의 변화율이다.

트렌드는 시간에 따른 지속적인 방향성, 계절성은 일정 주기로 반복되는 패턴, 노이즈는 개별 게시물이나 관측 조건에 따른 불규칙 변동이다. 이 표본에서는 짧은 기간과 서로 다른 게시 경과 시간 때문에 장기 트렌드나 주간 계절성을 확정하지 않는다. 게시 후 경과 시간은 약 {clean.age_hours.min():.1f}~{clean.age_hours.max():.1f}시간이다.

## 5. 분석 결과 및 시각화

### 5.1 게시 날짜별 성과와 이동평균
![게시 날짜별 조회수 중앙값과 3일 이동평균](images/01_daily_cohort_trend.png)

파란 선은 게시 날짜 집단의 누적 조회수 중앙값, 주황 선은 3일 이동평균이다. 결측 날짜는 선을 끊고, 값 범위 차이를 보기 위해 조회수 축에 로그 스케일을 적용했다. 선의 변화에는 콘텐츠 구성과 게시 경과 시간 차이가 섞여 있다.

### 5.2 인접 날짜 집단 간 변화율
![게시 날짜별 중앙값 변화율](images/02_daily_cohort_change.png)

인접 날짜의 중앙값 변화율이다. 집계 가능한 구간 중 가장 큰 증가율은 {max_day}의 {max_change}다. 이전 날짜 중앙값이 낮으면 변화율이 크게 보일 수 있다. 실제 계정의 일별 조회수 증가율로 해석하지 않는다.

### 5.3 조회수 집중도
![상위 게시물 조회수 집중도](images/03_view_concentration.png)

전체 조회수는 {int(clean.views.sum()):,}회다. 상위 1개가 {cumulative.iloc[0]:.1f}%, 상위 5개가 {cumulative.iloc[min(4,len(clean)-1)]:.1f}%를 차지한다. 조회수 평균은 {clean.views.mean():,.0f}회, 중앙값은 {clean.views.median():,.0f}회다.

### 5.4 콘텐츠 유형별 비교
![유형별 조회수 중앙값](images/04_media_comparison.png)

| 유형 | 표본 수 | 조회수 중앙값 | 조회수 평균 | 상호작용률 중앙값 |
|---|---:|---:|---:|---:|
{media_rows}

상호작용률은 이 분석의 보조 지표로 `(좋아요+답글+재게시+인용)/조회수×100`이다. 공식 참여율 또는 고유 사용자 비율로 간주하지 않는다. 유형별 표본 수와 게시 경과 시간이 다르므로 인과 효과를 나타내지 않는다.

## 6. 인사이트: 관찰·해석·행동

1. **조회수가 소수 게시물에 집중된다.** 관찰: 그래프 3에서 상위 5개가 전체 조회수의 {cumulative.iloc[min(4,len(clean)-1)]:.1f}%다. 해석: 일부 확산 사례가 전체 평균을 끌어올릴 가능성이 크다. 행동: 성과 기준은 중앙값과 집중도를 함께 보고, 상위 사례의 본문·주제를 별도로 검토한다.
2. **콘텐츠 유형의 조회수 중앙값에 차이가 있다.** 관찰: 그래프 4와 표의 유형별 중앙값·표본 수는 {media_observation}다. 해석: 유형 차이 외에 주제와 게시 경과 시간의 영향일 수 있다. 행동: 같은 주제·비슷한 관측 시간을 맞춘 후 유형 차이를 재검토한다.
3. **날짜별 차이를 시간에 따른 성장으로 단정할 수 없다.** 관찰: 그래프 2에서 가장 큰 증가율은 {max_day}의 {max_change}이고, 유효 게시물의 관측 경과 시간은 {clean.age_hours.min():.1f}~{clean.age_hours.max():.1f}시간이다. 해석: 실제 추세 외에 서로 다른 게시 집단과 누적 관측 시간이 영향을 준다. 행동: 게시 후 24시간·48시간 등 고정 시점에 추가 수집해 비교한다. 기존 게시물의 과거 24시간 값은 현재 값으로 복원하지 않는다.

## 7. 결론·한계 및 업데이트 계획
현재 데이터로 기초 품질 점검, 시계열 기법 3가지와 시각화 4개를 수행했다. 대표 성과는 중앙값으로 보고, 확산 사례와 보통 게시물을 나누어 검토하는 것이 적절하다. {'유효 게시물 100개 이상이라는 수량 요건도 충족했다.' if len(clean)>=100 else '유효 게시물 100개 이상이라는 수량 요건은 아직 미충족이다.'}

한계는 {len(dates)}개 달력일의 짧은 범위, 유형별 불균형, 단일 수집 스냅샷, 게시 경과 시간 차이, 외부 변수 미반영이다. 100개 게시물이 되어도 독립적인 100일 시계열이 되는 것은 아니다. 충분한 날짜 범위와 고정 관측 시점 확보가 추가로 필요하다.

이번에는 `collect_threads.py`로 일회 수집한 뒤 고유 ID 중복과 지표 완전성을 확인하고 통계·그래프·문서를 갱신했다. 같은 게시물의 반복 측정은 신규 고유 표본으로 세지 않았다. 자동·예약 수집은 활성화하지 않았다. 현재 버전의 코드·리포트·시각화는 GitHub 저장소에 보관하며 원본 CSV는 포함하지 않는다.

{comparison_text}

## 8. AI 사용 로그
| 사용 작업 | 사용 이유 | 수행한 검증 |
|---|---|---|
| CSV 구조·결측·형식 점검 및 통계 계산 코드 작성 | 반복 점검 자동화 | 원본 {len(d)}행·고유 ID 수·유효 {len(clean)}행 대조, 지표별 비수치·음수·시간 선후 관계 확인 |
| Threads API 일회 수집 및 갱신 | 최신 표본 확보와 수량 요건 확인 | 페이지네이션 종료 확인, 중복 ID·상태별 건수 확인, 인증 정보와 원문 CSV의 Git 제외 확인 |
| 시계열 집계 및 시각화 코드 작성 | 집계 방식과 그래프 대안 검토 | 누락 날짜를 NA로 유지, 3일 이동평균의 최소 관측 수와 변화율의 결측 처리 확인 |
| 인사이트 초안 및 보고서 구성 | 수치와 설명을 일관되게 정리 | 누적 스냅샷과 일별 증가량을 구분하고 관찰·해석을 분리 |

위 작업은 AI 지원으로 작성했다. 작성자가 각 그래프와 수치를 이해하고 설명하는 학습 검증은 별도로 필요하며, 본 보고서는 그 검증까지 완료했다고 주장하지 않는다.

## 9. 재현 및 출처·이용 조건
실행 방법과 라이브러리 버전은 `README.md`, `requirements.txt`를 참고한다. 본인 Threads 계정의 데이터를 Threads API로 수집했으며, 토큰 등 인증 정보는 공개하지 않는다. 게시물 원문 CSV와 행 단위 파생 데이터는 GitHub 공개 대상에서 제외한다. 과제에서 데이터 대신 수집 방법 문서를 허용하므로 README와 `collect_threads.py`에 출처·방법·범위·입력 스키마를 기록하고, 코드·집계 결과·리포트·그래프를 공개 대상으로 구성한다. 원본 비공개 상태에서 실행을 재현하려면 같은 스키마의 로컬 CSV 또는 본인 계정의 API 인증을 별도로 준비해야 한다. 데이터 재배포 라이선스는 부여하지 않는다. 수집 종료일은 {d.collected_at.max():%Y-%m-%d}로 확정했다.
'''
    (ROOT / 'REPORT.md').write_text(report, encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=True))


if __name__ == '__main__':
    main()
