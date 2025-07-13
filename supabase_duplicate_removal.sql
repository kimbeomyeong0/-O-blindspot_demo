-- ============================================
-- 중복된 제목을 가진 기사 삭제 쿼리
-- ============================================

-- 1. 중복 제목 확인 (실행 전 확인용)
-- 이 쿼리를 먼저 실행해서 중복된 제목이 있는지 확인하세요
SELECT 
    title,
    COUNT(*) as duplicate_count,
    MIN(published_at) as oldest_published,
    MAX(published_at) as newest_published
FROM articles 
WHERE title IS NOT NULL 
GROUP BY title 
HAVING COUNT(*) > 1
ORDER BY duplicate_count DESC, title;

-- ============================================
-- 2. 중복 제거 쿼리 (주의: 데이터가 삭제됩니다!)
-- ============================================
-- 위의 확인 쿼리에서 중복이 있다면 이 쿼리를 실행하세요

DELETE FROM articles 
WHERE id IN (
    SELECT id FROM (
        SELECT 
            id,
            title,
            published_at,
            ROW_NUMBER() OVER (
                PARTITION BY title 
                ORDER BY published_at DESC
            ) as rn
        FROM articles 
        WHERE title IN (
            SELECT title 
            FROM articles 
            WHERE title IS NOT NULL 
            GROUP BY title 
            HAVING COUNT(*) > 1
        )
    ) ranked
    WHERE rn > 1
);

-- ============================================
-- 3. 검증 쿼리들 (삭제 후 실행)
-- ============================================

-- 3-1. 삭제 후 중복 확인
SELECT 
    title,
    COUNT(*) as remaining_count
FROM articles 
WHERE title IS NOT NULL 
GROUP BY title 
HAVING COUNT(*) > 1
ORDER BY remaining_count DESC, title;

-- 3-2. 전체 기사 수 확인
SELECT COUNT(*) as total_articles FROM articles;

-- 3-3. 카테고리별 기사 수 확인
SELECT 
    category,
    COUNT(*) as article_count
FROM articles 
GROUP BY category 
ORDER BY article_count DESC; 