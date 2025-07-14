-- issues 테이블
CREATE TABLE IF NOT EXISTS issues (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title TEXT NOT NULL,
  summary TEXT NOT NULL,
  image_url TEXT,
  image_swipe_url TEXT,
  bias_left_pct FLOAT DEFAULT 0,
  bias_center_pct FLOAT DEFAULT 0,
  bias_right_pct FLOAT DEFAULT 0,
  dominant_bias TEXT CHECK (dominant_bias IN ('left', 'center', 'right')),
  source_count INTEGER DEFAULT 0,
  updated_at TIMESTAMP DEFAULT now()
);

-- media_outlets 테이블
CREATE TABLE IF NOT EXISTS media_outlets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  bias TEXT CHECK (bias IN ('left', 'center', 'right')) NOT NULL,
  logo_url TEXT
);

-- articles 테이블
CREATE TABLE IF NOT EXISTS articles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  issue_id UUID REFERENCES issues(id) ON DELETE CASCADE,
  media_id UUID REFERENCES media_outlets(id) ON DELETE SET NULL,
  title TEXT NOT NULL,
  summary_excerpt TEXT,
  url TEXT UNIQUE NOT NULL,
  category TEXT,
  published_at TIMESTAMP,
  author TEXT
);

-- bias_summaries 테이블
CREATE TABLE IF NOT EXISTS bias_summaries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  issue_id UUID REFERENCES issues(id) ON DELETE CASCADE,
  bias TEXT CHECK (bias IN ('left', 'center', 'right')) NOT NULL,
  summary_list JSONB NOT NULL
);

-- common_points 테이블
CREATE TABLE IF NOT EXISTS common_points (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  issue_id UUID REFERENCES issues(id) ON DELETE CASCADE,
  point TEXT NOT NULL
);

-- reactions 테이블
CREATE TABLE IF NOT EXISTS reactions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  issue_id UUID UNIQUE REFERENCES issues(id) ON DELETE CASCADE,
  likes INTEGER DEFAULT 0,
  comments INTEGER DEFAULT 0,
  views INTEGER DEFAULT 0
);

-- bookmarks 테이블
CREATE TABLE IF NOT EXISTS bookmarks (
  user_id UUID NOT NULL,
  issue_id UUID NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
  created_at TIMESTAMP DEFAULT now(),
  PRIMARY KEY (user_id, issue_id)
);