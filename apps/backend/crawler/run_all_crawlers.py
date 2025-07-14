import asyncio
import importlib
import time
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

# 실행할 크롤러 모듈명 (파일명 기준)
CRAWLER_MODULES = [
    "chosun",
    "joongang",
    "pressian",
    "ohmynews",
    "mbc",
    "kbs",
    "sbs",
    "hani",
    "khan",
    "donga",
    "jtbc",
    "yonhap"
]

CRAWLER_PATH = "apps.backend.crawler.crawlers"
console = Console()

async def run_crawler(module_name):
    try:
        mod = importlib.import_module(f"{CRAWLER_PATH}.{module_name}")
        start = time.time()
        await mod.main()
        elapsed = time.time() - start
        return (module_name, True, elapsed, None)
    except Exception as e:
        return (module_name, False, 0, str(e))

async def main():
    results = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        "[progress.percentage]{task.percentage:>3.0f}%",
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("전체 크롤러 실행 중...", total=len(CRAWLER_MODULES))
        for i, module_name in enumerate(CRAWLER_MODULES, 1):
            progress.update(task, advance=1, description=f"({i}/{len(CRAWLER_MODULES)}) {module_name}")
            result = await run_crawler(module_name)
            results.append(result)
    # 요약 테이블 출력
    table = Table(title="크롤러 실행 결과 요약")
    table.add_column("크롤러", style="cyan")
    table.add_column("성공", style="green")
    table.add_column("실행시간(초)", style="magenta")
    table.add_column("오류", style="red")
    for name, success, elapsed, err in results:
        table.add_row(
            name,
            "✅" if success else "❌",
            f"{elapsed:.1f}" if success else "-",
            "-" if success else (err or "오류")
        )
    console.print(table)
    total_success = sum(1 for r in results if r[1])
    total_fail = len(results) - total_success
    console.print(f"[bold green]성공: {total_success}개[/bold green] / [bold red]실패: {total_fail}개[/bold red]")

if __name__ == "__main__":
    asyncio.run(main()) 