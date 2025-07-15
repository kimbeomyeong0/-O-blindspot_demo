import json
import os
from typing import List, Dict, Any
from dotenv import load_dotenv
import sys
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

# 프로젝트 루트 경로 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))))

from app.db.supabase_client import supabase_client

# .env 파일 로드
load_dotenv()

# rich 콘솔
console = Console()

class ArticleUpdater:
    def __init__(self):
        self.supabase = supabase_client.get_client()
    
    def load_cluster_issue_mapping(self, filename: str = "cluster_issue_mapping.json") -> Dict[int, str]:
        """클러스터 ID와 이슈 ID 매핑을 불러옵니다."""
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                data = json.load(f)
            console.print(f"[cyan]클러스터-이슈 매핑 로드 완료: {len(data)}개 매핑[/cyan]")
            return data
        except FileNotFoundError:
            console.print(f"[bold red]파일을 찾을 수 없습니다: {filename}[/bold red]")
            return {}
        except Exception as e:
            console.print(f"[bold red]파일 로드 중 오류 발생: {e}[/bold red]")
            return {}
    
    def load_cluster_results(self, filename: str = "cluster_results.json") -> List[Dict[str, Any]]:
        """클러스터링 결과를 불러옵니다."""
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                data = json.load(f)
            console.print(f"[cyan]클러스터 결과 로드 완료: {len(data)}개 기사[/cyan]")
            return data
        except FileNotFoundError:
            console.print(f"[bold red]파일을 찾을 수 없습니다: {filename}[/bold red]")
            return []
        except Exception as e:
            console.print(f"[bold red]파일 로드 중 오류 발생: {e}[/bold red]")
            return []
    
    def get_articles_by_cluster(self, cluster_id: int) -> List[str]:
        """특정 클러스터에 속한 기사 ID 목록을 반환합니다."""
        cluster_results = self.load_cluster_results()
        article_ids = [
            item['article_id'] for item in cluster_results 
            if item['cluster_id'] == cluster_id
        ]
        console.print(f"[cyan]클러스터 {cluster_id}에서 {len(article_ids)}개 기사 ID 찾음[/cyan]")
        return article_ids
    
    def update_articles_issue_id(self, article_ids: List[str], issue_id: str) -> bool:
        """기사들의 issue_id를 업데이트합니다."""
        if not article_ids:
            return True
        
        try:
            # 배치 업데이트 수행
            response = self.supabase.table("articles").update({
                "issue_id": issue_id
            }).in_("id", article_ids).execute()
            
            console.print(f"[bold green]✅ {len(article_ids)}개 기사 업데이트 완료[/bold green]")
            return True
            
        except Exception as e:
            console.print(f"[bold red]기사 업데이트 중 오류 발생: {e}[/bold red]")
            return False
    
    def verify_issue_exists(self, issue_id: str) -> bool:
        """이슈가 실제로 존재하는지 확인합니다."""
        try:
            response = self.supabase.table("issues").select("id").eq("id", issue_id).execute()
            exists = len(response.data) > 0
            console.print(f"[cyan]이슈 {issue_id} 존재 확인: {exists}[/cyan]")
            return exists
        except Exception as e:
            console.print(f"[bold red]이슈 확인 중 오류 발생: {e}[/bold red]")
            return False
    
    def run(self):
        """전체 기사 업데이트 프로세스를 실행합니다."""
        console.print("[bold green]=== 기사 issue_id 업데이트 시작 ===[/bold green]")
        
        # 클러스터-이슈 매핑 로드
        cluster_issue_mapping = self.load_cluster_issue_mapping()
        if not cluster_issue_mapping:
            console.print("[bold red]클러스터-이슈 매핑을 로드할 수 없습니다.[/bold red]")
            return
        
        total_updated = 0
        total_articles = 0
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console
        ) as progress:
            task = progress.add_task("[bold blue]기사 업데이트", total=len(cluster_issue_mapping))
            
            for cluster_id_str, issue_id in cluster_issue_mapping.items():
                # 문자열을 정수로 변환
                cluster_id = int(cluster_id_str)
                
                # 이슈 존재 확인
                if not self.verify_issue_exists(issue_id):
                    progress.update(task, advance=1)
                    continue
                
                # 클러스터에 속한 기사 ID 목록 가져오기
                article_ids = self.get_articles_by_cluster(cluster_id)
                
                if not article_ids:
                    progress.update(task, advance=1)
                    continue
                
                # 기사들의 issue_id 업데이트
                if self.update_articles_issue_id(article_ids, issue_id):
                    total_updated += len(article_ids)
                
                total_articles += len(article_ids)
                progress.update(task, advance=1)
        
        console.print(f"[bold green]=== 기사 업데이트 완료 ===[/bold green]")
        console.print(f"[cyan]총 {total_updated}/{total_articles}개 기사가 업데이트되었습니다.[/cyan]")
        
        if total_updated > 0:
            console.print("[bold green]✅ 기사와 이슈 연결이 성공적으로 완료되었습니다.[/bold green]")
        else:
            console.print("[bold yellow]❌ 업데이트된 기사가 없습니다.[/bold yellow]")

if __name__ == "__main__":
    updater = ArticleUpdater()
    updater.run() 