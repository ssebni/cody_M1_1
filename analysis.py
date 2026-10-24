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
    parser.add_argument('--followers', type=Path, default=ROOT / 'data/follower_history.json',
                        help='Verified daily follower totals exported from Threads account insights')
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
    dates = pd.date_range(d.timestamp.min().normalize(), d.timestamp.max().normalize(), freq='D')
    # Count original posts even if their insights are unavailable. Exclude reshare facades.
    uploads = d.loc[d.media_type.ne('REPOST_FACADE')].copy()
    uploads['date'] = uploads.timestamp.dt.normalize()
    daily = uploads.groupby('date').size().reindex(dates, fill_value=0).to_frame('uploads')
    daily['partial_boundary_day'] = (daily.index == dates[0]) | (daily.index == dates[-1])
    history = json.loads(args.followers.read_text(encoding='utf-8-sig'))
    if history.get('source') != 'threads_account_insights_ui':
        raise ValueError('Expected verified account insights UI follower history')
    follower_rows = history.get('items', [])
    if not follower_rows or any(type(row.get('followers_count')) is not int or row['followers_count'] < 0 for row in follower_rows):
        raise ValueError('Invalid follower totals')
    followers = pd.DataFrame(follower_rows)
    followers['date'] = pd.to_datetime(followers.date, format='%Y-%m-%d', errors='raise').dt.tz_localize('Asia/Seoul')
    if followers.date.duplicated().any():
        raise ValueError('Duplicate follower dates')
    followers = followers.set_index('date').sort_index()
    follower_start, follower_end = followers.index.min(), followers.index.max()
    followers = followers.reindex(pd.date_range(min(dates.min(), follower_start), max(dates.max(), follower_end), freq='D'))
    # A difference needs two adjacent known calendar-day totals. Never bridge gaps.
    followers['net_change'] = followers.followers_count.diff()
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
    ax.bar(x, daily.uploads, color='#2563eb')
    ax.set(ylabel='Original posts in the API snapshot', xlabel='Posting date (KST)',
           title=f'Daily uploads | {len(uploads)} original posts; reshares excluded')
    ax.set_xticks(x[::2], labels[::2]); ax.set_yticks(range(0, int(daily.uploads.max())+2, 2)); ax.grid(axis='y', alpha=.2)
    fig.savefig(images / '01_daily_uploads.png'); plt.close(fig)
    fig, ax = plt.subplots(figsize=(11, 4.8), layout='constrained')
    changes = followers.net_change
    fx = np.arange(len(followers))
    ax.bar(fx, changes, color=['#2563eb' if pd.notna(v) and v >= 0 else '#dc2626' for v in changes])
    missing = changes.isna()
    for pos in fx[missing]:
        ax.axvspan(pos-.45, pos+.45, color='#e5e7eb', alpha=.7, lw=0)
    ax.axhline(0, color='#64748b', lw=1)
    ax.set_xticks(fx[::2], followers.index.strftime('%m-%d')[::2]); ax.grid(axis='y', alpha=.2)
    ax.set(xlabel='Account insights date (KST) | gray = unavailable, not zero', ylabel='Net follower change (people)',
           title=f'Daily follower net change | verified history through {follower_end:%Y-%m-%d}')
    fig.savefig(images / '02_follower_net_change.png'); plt.close(fig)
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
    daily.to_csv(results / 'daily_uploads.csv', index_label='date', encoding='utf-8-sig')
    followers.to_csv(results / 'follower_daily.csv', index_label='date', encoding='utf-8-sig')
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
               'original_uploads':len(uploads),
               'follower_history_start':follower_start.date().isoformat(),
               'follower_history_end':follower_end.date().isoformat(),
               'follower_history_observed_at':history.get('observed_at'),
               'follower_daily_changes':int(followers.net_change.notna().sum()),
               'valid_sample_requirement_met':len(clean)>=100}
    (results / 'quality_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    quality_rows = '\n'.join(f'| `{c}` | {int(raw[c].isna().sum())} |' for c in required)
    media_rows = '\n'.join(f'| {k} | {int(v.n)} | {v.median_views:,.0f} | {v.mean_views:,.0f} | {v.median_rate:.2f}% |' for k,v in groups.iterrows())
    media_observation = '; '.join(f'{k} {int(v.n)}개: {v.median_views:,.0f}회' for k,v in groups.iterrows())
    nonempty = changes.dropna()
    max_day = nonempty.idxmax().strftime('%m-%d') if len(nonempty) else '산출 불가'
    max_change = f'{nonempty.max():,.0f}명' if len(nonempty) else '산출 불가'
    first_followers = int(followers.loc[follower_start, 'followers_count'])
    last_followers = int(followers.loc[follower_end, 'followers_count'])
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
Threads의 업로드 활동, 날짜별 팔로워 순증감, 조회수 집중도와 콘텐츠 유형별 성과를 분석한다. SNS 콘텐츠별 확산과 반응 차이를 살펴보기 위해 게시물 1개를 관측 단위로 정했다. SNS의 빠른 확산과 관심 변화는 주제 선정의 이유이며, 게시 후 경과 시간의 영향은 별도 한계로 고려한다.

**갱신일: {d.collected_at.max():%Y-%m-%d}, 진행 상태: {'유효 표본 100개 요건 충족' if len(clean)>=100 else '필수 표본 요건 미충족'}.** 전체 {len(d)}개, 유효 인사이트 {len(clean)}개다. 데이터 포인트는 성과 지표가 완전한 고유 게시물 1개로 정의한다. {'추가 표본 확보 요건을 충족했다.' if len(clean)>=100 else f'현재 최소 {100-len(clean)}개의 유효 게시물을 추가 확보해야 한다.'} 시각화용 일별 집계의 관측 수와 고유 게시물 수는 구분한다.

## 2. 분석 질문
1. 날짜별로 직접 업로드한 게시물 수는 얼마이며, 업로드가 많은 날은 언제인가?
2. 날짜별 팔로워 순증감은 얼마이며, 증가가 가장 큰 날은 언제인가?
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
- 팔로워 자료는 별도 `data/follower_history.json`의 계정 인사이트 화면에서 확인한 날짜별 총 팔로워 수다. 관측 날짜는 {follower_start:%Y-%m-%d}~{follower_end:%Y-%m-%d}, 화면 확인 시각은 {history.get('observed_at')}다. 게시물 성과 CSV와 출처·기간이 다르며, 10월 24일의 최신 팔로워 이력으로 간주하지 않는다.

| 컬럼 | 결측 수 |
|---|---:|
{quality_rows}

현재 성과 분석에서 제외한 행은 {len(incomplete)}개이며 유형별 건수는 {incomplete_types}다. 상태별 전체 건수는 {d.status.value_counts().to_dict()}다. 유형별 미제공 여부는 추가 확인이 필요하다. 업로드 수는 인사이트 성공 여부와 관계없이 `REPOST_FACADE`를 제외한 원본 게시물 목록으로 집계했다. 목록에 게시물이 없는 날짜는 '이번 API 반환 목록 기준 0개'로 표시한다. 삭제·비공개 게시물 또는 API 미반환 이력까지 포함한 실제 과거 게시 수를 보장하지 않는다. 팔로워 자료의 누락 날짜와 차이를 계산할 수 없는 날짜는 0으로 채우지 않는다. 첫날·마지막 날은 완전한 일 단위 수집 범위가 아닐 수 있어 경계일로 표시한다.

조회수 IQR 상한은 {upper:,.1f}회이며 초과 게시물은 {int((clean.views>upper).sum())}개다. 실제 확산 가능성이 있어 제거하거나 상한으로 치환하지 않았다. 재게시·인용은 0이 많아 IQR=0일 수 있으므로 이 기준으로 양수 값을 일괄 제거하지 않는다.

## 4. 시계열 분석 방법
게시물 성과는 **서로 다른 게시물의 누적 성과를 한 번 수집한 스냅샷**이며, 계정의 일별 신규 조회수가 아니다. 반면 팔로워 이력은 계정의 날짜별 총수로, 전일 대비 차이를 계산할 수 있다. 서로 다른 관측 단위와 기간을 구분하며, 원본 {len(d)}행을 {len(d)}일의 일별 시계열로 간주하지 않는다.

KST의 달력 날짜를 집계 단위로 사용했다. {len(dates)}개 달력일 범위에서 업로드 활동과 팔로워 변화를 날짜별로 살펴보기 위한 선택이다. 직접 업로드한 게시물이 있는 날짜는 {int(daily.uploads.gt(0).sum())}일이다. 주별·월별 집계로는 비교 구간이 너무 적다.

1. **날짜별 구간 집계:** 게시 시각을 KST 날짜로 변환하고 날짜별 직접 업로드 건수를 센다. 재게시 파사드는 제외한다. 이는 업로드 활동량을 보여주며 조회수의 높고 낮음을 뜻하지 않는다.
2. **1차 차분:** `당일 총 팔로워 수 - 전일 총 팔로워 수`를 계산한다. 단위는 명이며 백분율 변화율이 아니다. 양수는 순증가, 음수는 순감소다. 전일 값이 없으면 계산하지 않으며 여러 날을 건너뛴 차이를 일일 증감으로 표시하지 않는다.

팔로워 순증감은 신규 팔로우와 언팔로우의 순효과이며 각각의 건수를 분리하지 못한다. 날짜별 총수 집계가 수정되면 차이에도 영향을 줄 수 있다. 업로드와 팔로워의 공통 관측 기간에서 추가 비교할 수 있으나, 게시물이 팔로워 증가를 유발했다고 단정하지 않는다.

트렌드는 시간에 따른 지속적인 방향성, 계절성은 일정 주기로 반복되는 패턴, 노이즈는 개별 게시물이나 관측 조건에 따른 불규칙 변동이다. 이 표본에서는 짧은 기간과 서로 다른 게시 경과 시간 때문에 장기 트렌드나 주간 계절성을 확정하지 않는다. 게시 후 경과 시간은 약 {clean.age_hours.min():.1f}~{clean.age_hours.max():.1f}시간이다.

## 5. 분석 결과 및 시각화

### 5.1 날짜별 업로드 게시물 수
![날짜별 직접 업로드 게시물 수](images/01_daily_uploads.png)

현재 API 목록의 직접 업로드 게시물은 총 {len(uploads)}개다. 가장 많이 업로드한 날은 {daily.uploads.idxmax():%m월 %d일}의 {int(daily.uploads.max())}개이며, 동률인 날짜가 있으면 첫 날짜를 표시한다. 마지막 수집일은 하루 전체가 끝나기 전이라 일일 최종 건수가 아니다.

### 5.2 날짜별 팔로워 순증감
![날짜별 팔로워 순증감. 회색은 미확인 구간](images/02_follower_net_change.png)

확인된 총 팔로워 수는 {follower_start:%m월 %d일} {first_followers}명에서 {follower_end:%m월 %d일} {last_followers}명으로, 두 시점 사이 {last_followers-first_followers:+d}명 변했다. 계산 가능한 일일 순증감은 {len(nonempty)}개다. 최대 순증가는 {max_day}의 {max_change}이다. 첫 날짜는 전일 기준값이 없어 증감을 계산하지 않는다. {follower_end:%m월 %d일} 이후의 회색 구간은 미수집이며 0명을 뜻하지 않는다. 팔로워 이력은 별도 화면에서 확인한 값이며 게시물의 팔로우 유입 수를 합산한 값이 아니다.

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
3. **확인된 기간에 계정 팔로워 수가 증가했다.** 관찰: 그래프 2에서 {follower_start:%m월 %d일} {first_followers}명에서 {follower_end:%m월 %d일} {last_followers}명으로 {last_followers-first_followers:+d}명 변했고, 최대 일일 순증가는 {max_day}의 {max_change}이다. 해석: 게시물 확산이나 계정 노출 등이 가능한 요인이지만 이 자료만으로 원인을 특정할 수 없다. 행동: 증가가 큰 날짜의 게시물·노출을 공통 관측 기간에서 확인하고, 이후 팔로워 이력을 추가해 비교한다.
4. **업로드 활동이 날짜별로 고르지 않다.** 관찰: 그래프 1에서 {len(dates)}개 달력일 중 {int(daily.uploads.gt(0).sum())}일에 직접 업로드가 있으며, 최대는 하루 {int(daily.uploads.max())}개다. 해석: 활동량 차이는 계정 노출 기회의 차이와 연결될 수 있으나 성과의 인과 효과를 뜻하지 않는다. 행동: 업로드 수를 기록하면서 팔로워 이력이 있는 날짜에 한해 후속 비교한다.

## 7. 결론·한계 및 업데이트 계획
현재 데이터로 기초 품질 점검, 시계열 기법 2가지(날짜별 집계·1차 차분)와 시각화 4개를 수행했다. 업로드 활동과 팔로워 순증감은 별개 지표로 보고, 조회수 대표 성과는 중앙값으로 설명한다. {'유효 게시물 100개 이상이라는 수량 요건도 충족했다.' if len(clean)>=100 else '유효 게시물 100개 이상이라는 수량 요건은 아직 미충족이다.'}

한계는 {len(dates)}개 달력일의 짧은 게시 범위, 유형별 불균형, 게시물 성과의 단일 수집 스냅샷, 게시 경과 시간 차이, 외부 변수 미반영이다. 팔로워 이력은 {follower_end:%Y-%m-%d}까지만 확인돼 게시물 자료와 종료일이 다르다. 100개 게시물이 독립적인 100일 시계열이 되는 것은 아니며, 두 지표를 비교할 때 공통 관측 날짜만 사용해야 한다.

이번에는 `collect_threads.py`로 일회 수집한 뒤 고유 ID 중복과 지표 완전성을 확인하고 통계·그래프·문서를 갱신했다. 같은 게시물의 반복 측정은 신규 고유 표본으로 세지 않았다. 자동·예약 수집은 활성화하지 않았다. 현재 버전의 코드·리포트·시각화는 GitHub 저장소에 보관하며 원본 CSV는 포함하지 않는다.

{comparison_text}

## 8. AI 사용 로그
| 사용 작업 | 사용 이유 | 수행한 검증 |
|---|---|---|
| CSV 구조·결측·형식 점검 및 통계 계산 코드 작성 | 반복 점검 자동화 | 원본 {len(d)}행·고유 ID 수·유효 {len(clean)}행 대조, 지표별 비수치·음수·시간 선후 관계 확인 |
| Threads API 일회 수집 및 갱신 | 최신 표본 확보와 수량 요건 확인 | 페이지네이션 종료 확인, 중복 ID·상태별 건수 확인, 인증 정보와 원문 CSV의 Git 제외 확인 |
| 날짜별 업로드 집계·팔로워 차분과 시각화 작성 | 본인이 설명할 수 있는 활동·성장 지표로 교체 | 재게시 제외 확인, 팔로워 첫날·누락 날짜의 차분을 NA로 유지, 전일 총수와 증감 대조 |
| 인사이트 초안 및 보고서 구성 | 수치와 설명을 일관되게 정리 | 누적 스냅샷과 일별 증가량을 구분하고 관찰·해석을 분리 |

위 작업은 AI 지원으로 작성했다. 작성자가 각 그래프와 수치를 이해하고 설명하는 학습 검증은 별도로 필요하며, 본 보고서는 그 검증까지 완료했다고 주장하지 않는다.

## 9. 재현 및 출처·이용 조건
실행 방법과 라이브러리 버전은 `README.md`, `requirements.txt`를 참고한다. 본인 Threads 계정의 게시물 성과는 API, 날짜별 총 팔로워 수는 로그인된 계정 인사이트 화면의 정확한 날짜별 값으로 수집했다. 토큰 등 인증 정보는 공개하지 않는다. 게시물 원문 CSV·행 단위 파생 데이터·화면 수집 원본 JSON은 GitHub 공개 대상에서 제외한다. 과제에서 데이터 대신 수집 방법 문서를 허용하므로 README와 `collect_threads.py`에 출처·방법·범위·입력 스키마를 기록하고, 코드·집계 결과·리포트·그래프를 공개 대상으로 구성한다. 게시물 성과 수집 종료일은 {d.collected_at.max():%Y-%m-%d}, 팔로워 이력의 마지막 확인 날짜는 {follower_end:%Y-%m-%d}다. 기본 실행에는 두 종류의 로컬 입력 파일이 필요하다. 데이터 재배포 라이선스는 부여하지 않는다.
'''
    (ROOT / 'REPORT.md').write_text(report, encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=True))


if __name__ == '__main__':
    main()
