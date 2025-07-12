# 📌 Blindspot DB 스키마 정의 (2025.07 기준)

## 🟦 issues
- id: UUID (PK)
- title: TEXT
- summary: TEXT
- image_url: TEXT
- image_swipe_url: TEXT
- bias_left_pct / center_pct / right_pct: FLOAT
- dominant_bias: TEXT ('left' | 'center' | 'right')
- source_count: INTEGER
- updated_at: TIMESTAMP

## 📰 articles
- id: UUID (PK)
- issue_id: UUID (FK)
- media_id: UUID (FK)
- title: TEXT
- summary_excerpt: TEXT
- url: TEXT (UNIQUE)
- bias: TEXT
- category: TEXT
- published_at: TIMESTAMP
- author: TEXT (optional)

## 🏢 media_outlets
- id: UUID (PK)
- name: TEXT
- bias: TEXT
- logo_url: TEXT

## 📊 bias_summaries
- id: UUID (PK)
- issue_id: UUID (FK)
- bias: TEXT
- summary_list: JSONB

## 🔁 common_points
- id: UUID (PK)
- issue_id: UUID (FK)
- point: TEXT

## ❤️ reactions
- id: UUID (PK)
- issue_id: UUID (FK, UNIQUE)
- likes / comments / views: INTEGER

## 📌 bookmarks
- user_id: UUID (PK)
- issue_id: UUID (PK, FK)
- created_at: TIMESTAMP 