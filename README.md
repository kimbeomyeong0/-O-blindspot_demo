# 🎯 Blindspot 프로젝트

편향된 뉴스를 균형있게 보여주는 플랫폼

## 📁 프로젝트 구조

```
blindspot_demo/
├── apps/
│   ├── frontend/                 # 프론트엔드 (Next.js + TypeScript)
│   └── backend/                  # 백엔드 (Python + Supabase)
│       ├── app/                  # 백엔드 애플리케이션
│       │   ├── db/              # 데이터베이스 연결
│       │   ├── models/          # 데이터 모델
│       │   └── services/        # 비즈니스 로직
│       ├── crawler/             # 크롤러
│       │   └── data/raw/        # 크롤링 결과
│       └── supabase/            # 데이터베이스 스키마
├── docs/                         # 설계 문서
├── .cursor/                      # Cursor IDE 규칙
└── README.md
```

## 🕷️ 크롤러

### 조선일보 크롤러
- **6개 카테고리**: 정치, 경제, 사회, 국제, 문화, 스포츠
- **각 카테고리당 최대 30개 기사** 수집
- **Supabase articles 테이블**에 자동 저장
- **중복 방지**: URL 기반 중복 체크
- **더보기 버튼 자동 클릭**: 충분한 기사 확보

### 실행 방법
```bash
cd apps/backend
python3 crawler/crawler_chosun.py
```

## 🗄️ 데이터베이스

### Supabase 연동
- **articles 테이블**: 크롤링된 기사 저장
- **media_outlets 테이블**: 미디어 정보
- **issues 테이블**: 이슈 그룹화 (향후 구현)

### 환경 설정
```bash
# apps/backend/.env 파일 생성
SUPABASE_URL=your_supabase_url_here
SUPABASE_ANON_KEY=your_supabase_anon_key_here
```

## 🚀 시작하기

1. 저장소 클론
```bash
git clone https://github.com/kimbeomyeong0/-O-blindspot_demo.git
cd blindspot_demo
```

2. 백엔드 의존성 설치
```bash
cd apps/backend
python3 -m pip install -r requirements.txt
```

3. 환경 변수 설정
```bash
cp env.example .env
# .env 파일을 편집하여 Supabase 설정 추가
```

4. 크롤러 실행
```bash
python3 crawler/crawler_chosun.py
```

## 📊 데이터베이스 스키마

자세한 스키마는 [docs/schema.md](docs/schema.md)를 참조하세요.

### Articles 테이블 주요 필드
- `title`: 기사 제목
- `url`: 기사 URL (프론트엔드 링크용)
- `content_full`: 기사 본문 전체
- `bias`: 성향 (left, center, right)
- `category`: 카테고리
- `published_at`: 발행일
- `author`: 작성자
- `image_url`: 이미지 URL

## 🛠️ 개발 가이드

### Cursor IDE 규칙
프로젝트에는 다음과 같은 Cursor Rules가 포함되어 있습니다:
- **supabase-integration.mdc**: Supabase 연동 가이드
- **crawler-development.mdc**: 크롤러 개발 가이드
- **database-schema.mdc**: 데이터베이스 스키마 가이드
- **articles-table-guide.mdc**: Articles 테이블 상세 가이드
- **field-mapping.mdc**: 필드 매핑 가이드

### 새로운 크롤러 추가
1. `apps/backend/crawler/` 디렉토리에 새 크롤러 파일 생성
2. `apps/backend/app/models/article.py` 모델 사용
3. `apps/backend/app/services/article_service.py` 서비스 활용

## 🤝 기여하기

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 📝 라이선스

이 프로젝트는 MIT 라이선스 하에 배포됩니다.

---

**Git 실습을 위한 업데이트**: 이 파일이 Git으로 버전관리되고 있습니다! 🎉
