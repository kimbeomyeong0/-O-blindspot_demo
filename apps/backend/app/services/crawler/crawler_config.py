# 크롤러 공통 설정

CATEGORY_URLS = {
    "정치": [
        "https://www.chosun.com/politics/",
        "https://www.chosun.com/politics/?page=1",
        "https://www.chosun.com/politics/?page=2",
        "https://www.chosun.com/politics/?page=3"
    ],
    "경제": [
        "https://www.chosun.com/economy/",
        "https://www.chosun.com/economy/?page=1",
        "https://www.chosun.com/economy/?page=2", 
        "https://www.chosun.com/economy/?page=3"
    ],
    "사회": [
        "https://www.chosun.com/national/",
        "https://www.chosun.com/national/?page=1", 
        "https://www.chosun.com/national/?page=2",
        "https://www.chosun.com/national/?page=3"
    ],
    "국제": [
        "https://www.chosun.com/international/",
        "https://www.chosun.com/international/?page=1",
        "https://www.chosun.com/international/?page=2",
        "https://www.chosun.com/international/?page=3"
    ],
    "문화": [
        "https://www.chosun.com/culture-style/",
        "https://www.chosun.com/culture-style/?page=1",
        "https://www.chosun.com/culture-style/?page=2",
        "https://www.chosun.com/culture-style/?page=3"
    ],
    "스포츠": [
        "https://www.chosun.com/sports/",
        "https://www.chosun.com/sports/?page=1",
        "https://www.chosun.com/sports/?page=2",
        "https://www.chosun.com/sports/?page=3"
    ]
}

# 브라우저 최적화 설정
BROWSER_ARGS = [
    '--no-sandbox',
    '--disable-dev-shm-usage',
    '--disable-extensions',
    '--disable-plugins',
    '--disable-images',
    '--disable-web-security',
    '--disable-features=TranslateUI',
    '--disable-renderer-backgrounding',
    '--disable-background-timer-throttling',
    '--disable-default-apps',
    '--disable-sync',
    '--disable-translate',
    '--hide-scrollbars',
    '--mute-audio',
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-component-update',
    '--disable-domain-reliability',
    '--disable-print-preview',
    '--disable-speech-api',
    '--disable-web-bluetooth',
    '--disable-client-side-phishing-detection',
    '--disable-hang-monitor',
    '--disable-prompt-on-repost',
    '--disable-breakpad',
    '--disable-dev-tools',
    '--disable-in-process-stack-traces',
    '--disable-histogram-customizer',
    '--disable-gl-extensions',
    '--disable-3d-apis',
    '--disable-accelerated-2d-canvas',
    '--disable-accelerated-jpeg-decoding',
    '--disable-accelerated-mjpeg-decode',
    '--disable-accelerated-video-decode',
]

# 기사 목록 셀렉터들
ARTICLE_SELECTORS = [
    "div.story-card a",
    ".story-card a",
    ".article-card a",
    ".news-card a",
    "article a",
    ".headline a",
    ".story-item a",
    ".news-item a",
    "a[href*='/article/']",
    "a[href*='/news/']",
    ".list-item a",
    ".news-list a",
    ".article-list a",
    "a[href*='/politics/']",
    "a[href*='/national/']",
    "a[href*='/economy/']",
    "a[href*='/international/']",
    "a[href*='/culture/']",
    "a[href*='/sports/']"
]

# 더보기 버튼 셀렉터들
MORE_BUTTON_SELECTORS = [
    "button:has-text('기사 더보기')",
    "a:has-text('기사 더보기')",
    "button:has-text('더보기')",
    "a:has-text('더보기')",
    ".more-btn",
    ".btn-more",
    "#more-btn",
    "button.more",
    "a.more",
    "[data-more]",
    "[onclick*='more']",
    "button:has-text('More')",
    ".load-more",
    ".btn-load-more",
    ".more-articles",
    ".load-articles",
    "button[data-load]",
    "a[data-load]",
    ".paging .next",
    ".pagination .next",
    "a:has-text('다음')",
    "button:has-text('다음')",
    ".next-page",
    ".page-next"
]

# 본문 셀렉터들
CONTENT_SELECTORS = [
    '.article-body',
    '.news-article-body', 
    '.story-content',
    '.entry-content',
    '#article-body',
    '.article-content',
    '.text-content',
    '.content-body',
    '.article-text',
    '.story-body'
] 