#!/usr/bin/env python3
"""
기사 클러스터링 및 이슈 생성 파이프라인

1. 임베딩 벡터화 (OpenAI)
2. DBSCAN 클러스터링
3. 이슈 생성 및 저장
4. 기사 issue_id 업데이트
"""

import os
import sys
import time
from datetime import datetime
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich.panel import Panel
from rich.text import Text
import argparse
import subprocess

# 프로젝트 루트 경로 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))))

from embed_articles import ArticleEmbedder
from cluster_articles import ArticleClusterer
from generate_issues import IssueGenerator
from update_articles import ArticleUpdater

# rich 콘솔
console = Console()

def print_step_header(step_num: int, title: str):
    """단계별 헤더를 출력합니다."""
    console.print(Panel(
        f"[bold blue]단계 {step_num}[/bold blue]: {title}",
        border_style="blue",
        padding=(0, 1)
    ))

def print_step_footer(step_num: int, success: bool):
    """단계별 푸터를 출력합니다."""
    if success:
        console.print(f"[bold green]✅ 단계 {step_num} 완료[/bold green]")
    else:
        console.print(f"[bold red]❌ 단계 {step_num} 실패[/bold red]")

def check_environment():
    """필요한 환경변수와 설정을 확인합니다."""
    console.print("[bold yellow]환경 설정 확인 중...[/bold yellow]")
    
    required_env_vars = [
        "OPENAI_API_KEY",
        "SUPABASE_URL", 
        "SUPABASE_ANON_KEY"
    ]
    
    missing_vars = []
    for var in required_env_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        console.print(f"[bold red]❌ 누락된 환경변수: {', '.join(missing_vars)}[/bold red]")
        console.print("[yellow]⚠️  .env 파일을 확인하고 필요한 환경변수를 설정해주세요.[/yellow]")
        return False
    
    console.print("[bold green]✅ 환경 설정 확인 완료[/bold green]")
    return True

def run_pipeline():
    """전체 파이프라인을 실행합니다."""
    start_time = time.time()
    
    console.print(Panel(
        "[bold green]🚀 기사 클러스터링 및 이슈 생성 파이프라인 시작[/bold green]",
        border_style="green",
        padding=(0, 1)
    ))
    console.print(f"[cyan]시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/cyan]")
    
    # 환경 설정 확인
    if not check_environment():
        return False
    
    pipeline_steps = [
        (1, "임베딩 벡터화", run_embedding_step),
        (2, "DBSCAN 클러스터링", run_clustering_step),
        (3, "이슈 생성", run_issue_generation_step),
        (4, "기사 업데이트", run_article_update_step)
    ]
    
    for step_num, title, step_func in pipeline_steps:
        print_step_header(step_num, title)
        
        try:
            success = step_func()
            print_step_footer(step_num, success)
            
            if not success:
                console.print(f"[bold red]❌ 단계 {step_num}에서 실패했습니다. 파이프라인을 중단합니다.[/bold red]")
                return False
                
        except Exception as e:
            console.print(f"[bold red]❌ 단계 {step_num}에서 예외 발생: {e}[/bold red]")
            print_step_footer(step_num, False)
            return False
    
    # 전체 실행 시간 계산
    end_time = time.time()
    total_time = end_time - start_time
    
    console.print(Panel(
        f"[bold green]🎉 파이프라인 완료![/bold green]\n"
        f"[cyan]총 실행 시간: {total_time:.2f}초[/cyan]\n"
        f"[cyan]완료 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/cyan]",
        border_style="green",
        padding=(0, 1)
    ))
    
    return True

def run_embedding_step():
    """1단계: 임베딩 벡터화"""
    try:
        embedder = ArticleEmbedder()
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console
        ) as progress:
            task = progress.add_task("[bold blue]기사 임베딩 생성", total=None)
            
            # 임베딩 실행
            embedder.run()
            
            # 결과 파일 확인
            if os.path.exists("article_embeddings.json"):
                progress.update(task, completed=1, total=1)
                console.print("[bold green]✅ 임베딩 결과 파일 생성 완료[/bold green]")
                return True
            else:
                console.print("[bold red]❌ 임베딩 결과 파일이 생성되지 않았습니다.[/bold red]")
                return False
            
    except Exception as e:
        console.print(f"[bold red]❌ 임베딩 단계에서 오류 발생: {e}[/bold red]")
        return False

def run_clustering_step(extra_args=None):
    """2단계: DBSCAN 클러스터링 (추가 인자 지원)"""
    try:
        # cluster_articles.py를 서브프로세스로 실행
        cmd = [sys.executable, os.path.join(os.path.dirname(__file__), 'cluster_articles.py')]
        if extra_args:
            cmd += extra_args
        result = subprocess.run(cmd, capture_output=False)
        # 결과 파일 확인
        if os.path.exists("cluster_results.json"):
            console.print("[bold green]✅ 클러스터링 결과 파일 생성 완료[/bold green]")
            return True
        else:
            console.print("[bold red]❌ 클러스터링 결과 파일이 생성되지 않았습니다.[/bold red]")
            return False
    except Exception as e:
        console.print(f"[bold red]❌ 클러스터링 단계에서 오류 발생: {e}[/bold red]")
        return False

def run_issue_generation_step():
    """3단계: 이슈 생성"""
    try:
        generator = IssueGenerator()
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console
        ) as progress:
            task = progress.add_task("[bold blue]이슈 생성", total=None)
            
            # 이슈 생성 실행
            generator.run()
            
            # 결과 파일 확인
            if os.path.exists("cluster_issue_mapping.json"):
                progress.update(task, completed=1, total=1)
                console.print("[bold green]✅ 이슈 생성 결과 파일 생성 완료[/bold green]")
                return True
            else:
                console.print("[bold red]❌ 이슈 생성 결과 파일이 생성되지 않았습니다.[/bold red]")
                return False
            
    except Exception as e:
        console.print(f"[bold red]❌ 이슈 생성 단계에서 오류 발생: {e}[/bold red]")
        return False

def run_article_update_step():
    """4단계: 기사 업데이트"""
    try:
        updater = ArticleUpdater()
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console
        ) as progress:
            task = progress.add_task("[bold blue]기사 업데이트", total=None)
            
            # 기사 업데이트 실행
            updater.run()
            
            progress.update(task, completed=1, total=1)
            console.print("[bold green]✅ 기사 업데이트 완료[/bold green]")
            return True
            
    except Exception as e:
        console.print(f"[bold red]❌ 기사 업데이트 단계에서 오류 발생: {e}[/bold red]")
        return False

def cleanup_files():
    """임시 파일들을 정리합니다."""
    temp_files = [
        "article_embeddings.json",
        "cluster_results.json", 
        "cluster_issue_mapping.json"
    ]
    
    console.print("[bold yellow]🧹 임시 파일 정리 중...[/bold yellow]")
    
    for file in temp_files:
        if os.path.exists(file):
            try:
                os.remove(file)
                console.print(f"  [green]삭제됨: {file}[/green]")
            except Exception as e:
                console.print(f"  [red]삭제 실패: {file} - {e}[/red]")

def main():
    parser = argparse.ArgumentParser(description="기사 클러스터링 및 이슈 생성 파이프라인")
    parser.add_argument('--step', type=str, choices=['embedding', 'clustering', 'issue', 'update'], help='실행할 파이프라인 단계')
    # 나머지 인자는 clustering 단계에서만 사용하므로 parse_known_args로 받음
    args, unknown = parser.parse_known_args()

    try:
        if args.step == 'embedding':
            print_step_header(1, "임베딩 벡터화")
            run_embedding_step()
            print_step_footer(1, True)
        elif args.step == 'clustering':
            print_step_header(2, "DBSCAN 클러스터링")
            run_clustering_step(extra_args=unknown)
            print_step_footer(2, True)
        elif args.step == 'issue':
            print_step_header(3, "이슈 생성")
            run_issue_generation_step()
            print_step_footer(3, True)
        elif args.step == 'update':
            print_step_header(4, "기사 업데이트")
            run_article_update_step()
            print_step_footer(4, True)
        else:
            # 전체 파이프라인 실행
            run_pipeline()
    except KeyboardInterrupt:
        console.print(Panel(
            "[bold yellow]⚠️  사용자에 의해 파이프라인이 중단되었습니다.[/bold yellow]",
            border_style="yellow",
            padding=(0, 1)
        ))
        sys.exit(1)
    except Exception as e:
        console.print(Panel(
            f"[bold red]❌ 예상치 못한 오류가 발생했습니다: {e}[/bold red]",
            border_style="red",
            padding=(0, 1)
        ))
        sys.exit(1)

if __name__ == "__main__":
    main() 