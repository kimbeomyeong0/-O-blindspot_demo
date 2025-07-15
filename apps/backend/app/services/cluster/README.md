# 기사 클러스터링 및 이슈 생성 서비스

이 서비스는 articles 테이블의 기사들을 분석하여 유사한 기사들을 클러스터링하고, 각 클러스터를 대표하는 이슈를 생성합니다.

## 📋 개요

### 개발 흐름

1. **임베딩 벡터화** (OpenAI)
   - articles 테이블에서 `issue_id`가 null인 기사들을 조회
   - title + content_full을 OpenAI 임베딩으로 벡터화
   - `text-embedding-3-small` 모델 사용

2. **DBSCAN 클러스터링**
   - 임베딩 벡터를 DBSCAN으로 클러스터링
   - eps=1.2, min_samples=2 기준으로 실험
   - 코사인 유사도 기반 클러스터링

3. **이슈 생성**
   - 각 클러스터별로 대표 이슈 생성
   - GPT로 요약 및 제목 생성
   - bias 비율 계산 (left/center/right)
   - 대표 이미지 선택

4. **기사 연결**
   - 생성된 이슈와 기사들을 연결
   - articles 테이블의 `issue_id` 업데이트

## 🛠 설치 및 설정

### 1. 의존성 설치

```bash
cd apps/backend
pip3 install -r requirements.txt
```

### 2. 환경변수 설정

`.env` 파일에 다음 환경변수들을 설정하세요:

```env
# OpenAI API
OPENAI_API_KEY=your_openai_api_key_here

# Supabase
SUPABASE_URL=your_supabase_url_here
SUPABASE_ANON_KEY=your_supabase_anon_key_here
```

## 🚀 사용법

### 전체 파이프라인 실행

```bash
cd apps/backend/app/services/cluster
python3 run_pipeline.py
```

### 개별 단계 실행

#### 1. 임베딩 벡터화
```bash
python3 embed_articles.py
```

#### 2. 클러스터링
```bash
python3 cluster_articles.py
```

#### 3. 이슈 생성
```bash
python3 generate_issues.py
```

#### 4. 기사 업데이트
```bash
python3 update_articles.py
```

## 📁 파일 구조

```
cluster/
├── README.md                 # 이 파일
├── run_pipeline.py          # 전체 파이프라인 실행
├── embed_articles.py        # 1단계: 임베딩 벡터화
├── cluster_articles.py      # 2단계: DBSCAN 클러스터링
├── generate_issues.py       # 3단계: 이슈 생성
├── update_articles.py       # 4단계: 기사 업데이트
├── article_embeddings.json  # 임베딩 결과 (생성됨)
├── cluster_results.json     # 클러스터링 결과 (생성됨)
└── cluster_issue_mapping.json # 클러스터-이슈 매핑 (생성됨)
```

## ⚙️ 설정 옵션

### 클러스터링 파라미터

`cluster_articles.py`에서 DBSCAN 파라미터를 조정할 수 있습니다:

```python
# 기본값
eps = 1.2
min_samples = 2

# 더 엄격한 클러스터링
eps = 0.8
min_samples = 3

# 더 관대한 클러스터링
eps = 1.5
min_samples = 2
```

### GPT 모델 설정

`generate_issues.py`에서 GPT 모델을 변경할 수 있습니다:

```python
# 기본값
model = "gpt-3.5-turbo"

# 더 강력한 모델
model = "gpt-4"
```

## 📊 출력 파일

### article_embeddings.json
```json
[
  {
    "article_id": "uuid",
    "title": "기사 제목",
    "embedding": [0.1, 0.2, ...],
    "text_length": 1234
  }
]
```

### cluster_results.json
```json
[
  {
    "article_id": "uuid",
    "title": "기사 제목",
    "cluster_id": 0,
    "text_length": 1234
  }
]
```

### cluster_issue_mapping.json
```json
{
  "0": "issue_uuid_1",
  "1": "issue_uuid_2"
}
```

## 🔍 모니터링

### 로그 확인

각 단계별로 상세한 로그가 출력됩니다:

```
=== 기사 임베딩 시작 ===
처리할 기사 수: 150
처리 중: 1/150 - 코스피 연중 최고치 경신...
  완료: 벡터 크기 1536
...

=== 기사 클러스터링 시작 ===
클러스터링 시작: 150개 벡터
파라미터: eps=1.2, min_samples=2
클러스터링 완료:
  - 총 클러스터 수: 12
  - 노이즈 포인트 수: 8
```

### 성능 지표

- **처리 시간**: 각 단계별 실행 시간
- **클러스터 수**: 생성된 클러스터 개수
- **노이즈 비율**: 클러스터링되지 않은 기사 비율
- **이슈 생성 성공률**: 성공적으로 생성된 이슈 비율

## ⚠️ 주의사항

1. **API 비용**: OpenAI API 사용으로 인한 비용이 발생할 수 있습니다.
2. **토큰 제한**: 긴 기사 내용은 자동으로 잘려서 처리됩니다.
3. **클러스터 품질**: eps와 min_samples 파라미터를 조정하여 클러스터 품질을 개선할 수 있습니다.
4. **데이터 백업**: 실행 전 데이터베이스 백업을 권장합니다.

## 🐛 문제 해결

### 일반적인 오류

1. **환경변수 오류**
   ```
   ❌ 누락된 환경변수: OPENAI_API_KEY
   ```
   → `.env` 파일을 확인하고 환경변수를 설정하세요.

2. **Supabase 연결 오류**
   ```
   기사 조회 중 오류 발생: ...
   ```
   → Supabase URL과 API 키를 확인하세요.

3. **OpenAI API 오류**
   ```
   임베딩 생성 중 오류 발생: ...
   ```
   → OpenAI API 키와 크레딧을 확인하세요.

### 디버깅

각 스크립트를 개별적으로 실행하여 문제를 파악할 수 있습니다:

```bash
# 1단계만 실행하여 임베딩 확인
python3 embed_articles.py

# 결과 파일 확인
ls -la *.json
```

## 📈 성능 최적화

1. **배치 처리**: 대량의 기사가 있는 경우 배치 단위로 처리
2. **캐싱**: 임베딩 결과를 캐시하여 재사용
3. **병렬 처리**: 여러 클러스터를 병렬로 처리
4. **메모리 최적화**: 대용량 데이터 처리 시 메모리 사용량 모니터링

## 🤝 기여

새로운 기능이나 개선사항이 있다면 이슈를 생성하거나 풀 리퀘스트를 보내주세요. 