# 🎯 Blindspot 프로젝트

편향된 뉴스를 균형있게 보여주는 플랫폼

## 📁 프로젝트 구조

```
blindspot_demo/
├── apps/
│   ├── frontend/                 # 프론트엔드 (Next.js + TypeScript + Vercel)
│   └── backend/                  # 백엔드 (FastAPI + Railway 배포)
├── data/                         # 수집된 JSON 예시, 샘플 기사, 테스트용 데이터
├── scripts/                      # 단발성 실행 스크립트 (초기 데이터 삽입 등)
├── docs/                         # 설계 문서, ERD, 엔티티 정의 등
├── .github/                      # GitHub Actions 배포 자동화 등
├── .env                          # 공용 환경 변수 파일
└── README.md
```

## 🕷️ 크롤러

### 조선일보 크롤러
- **6개 카테고리**: 정치, 경제, 사회, 국제, 문화, 스포츠
- **각 카테고리당 최대 30개 기사** 수집
- **Supabase articles 테이블 형식**으로 반환

### 테스트
```bash
python3 scripts/test_crawlers.py
```

## 🚀 시작하기

1. 저장소 클론
```bash
git clone https://github.com/kimbeomyeong0/-O-blindspot_demo.git
cd blindspot_demo
```

2. 의존성 설치
```bash
pip install -r requirements.txt
```

3. 환경 변수 설정
```bash
cp .env.example .env
# .env 파일을 편집하여 필요한 설정 추가
```

4. 테스트 실행
```bash
python3 scripts/test_crawlers.py
```

## 📊 데이터베이스 스키마

자세한 스키마는 [docs/schema.md](docs/schema.md)를 참조하세요.

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
