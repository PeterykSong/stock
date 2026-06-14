# 주가 자동 조회 (GitHub Actions)

pykrx + yfinance로 한국·미국 종목 시세를 매일 자동 조회합니다.
GitHub의 클라우드 러너에서 실행되므로 PC를 켜둘 필요가 없습니다.

## 종목

- 한국: 삼성전자(005930), SK하이닉스(000660), 한화오션(042660), 효성중공업(298040)
- 미국: NVDA, AMD, NVDY, AMDY, GOOY, TLSA
  - ※ TLSA는 Tiziana Life Sciences입니다. 테슬라가 필요하면 `stock_prices.py`의 `US_TICKERS`에서 `TSLA`로 변경하세요.

## 파일 구조

```
your-repo/
├─ stock_prices.py
├─ requirements.txt
└─ .github/
   └─ workflows/
      └─ stock-prices.yml
```

`stock-prices.yml`은 반드시 `.github/workflows/` 폴더 안에 두어야 합니다.

## 설정 방법

1. GitHub에서 새 저장소(repository)를 만듭니다. (private 가능)
2. 위 3개 파일을 같은 구조로 올립니다.
   - 웹에서 올릴 경우: "Add file → Create new file"에서 경로를 `.github/workflows/stock-prices.yml`로 입력하면 폴더가 자동 생성됩니다.
3. 저장소 → **Settings → Actions → General → Workflow permissions**에서
   **"Read and write permissions"**를 켭니다. (결과 커밋에 필요)
4. **Actions** 탭 → "Daily Stock Prices" → **Run workflow**로 즉시 테스트.
5. 이후 매일 한국시간 07:00에 자동 실행됩니다.

## 결과 확인

- 저장소에 `stock_prices_result.csv`와 `stock_prices_result.md`가 매일 갱신·커밋됩니다.
- Actions 실행 페이지의 **Artifacts**에서도 다운로드할 수 있습니다.

## 스케줄 변경

`stock-prices.yml`의 cron은 **UTC** 기준입니다.

- 07:00 KST → `0 22 * * *`
- 08:00 KST → `0 23 * * *`
- 평일만 → `0 22 * * 0-4` (일~목 UTC = 월~금 KST)

> 참고: GitHub Actions 스케줄은 러너 혼잡 시 수 분 지연될 수 있습니다.

## (선택) 알림 받기

결과를 텔레그램/슬랙/이메일로 받고 싶으면 워크플로에 한 단계만 추가하면 됩니다.
필요하면 요청하세요 — 텔레그램 봇 또는 슬랙 Webhook 버전을 만들어 드립니다.
