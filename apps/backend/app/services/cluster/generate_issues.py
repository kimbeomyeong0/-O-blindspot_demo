import json
import random
import os
from typing import List, Dict, Any, Optional
from openai import OpenAI
from dotenv import load_dotenv
import sys
from datetime import datetime
import uuid
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

# 프로젝트 루트 경로 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))))

from app.db.supabase_client import supabase_client

# .env 파일 로드
load_dotenv()

# rich 콘솔
console = Console()

class IssueGenerator:
    def __init__(self):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.supabase = supabase_client.get_client()
    
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
    
    def get_articles_by_cluster(self, cluster_id: int) -> List[Dict[str, Any]]:
        """특정 클러스터에 속한 기사들의 상세 정보를 가져옵니다."""
        try:
            # 클러스터 결과에서 해당 클러스터의 article_id 목록 추출
            cluster_results = self.load_cluster_results()
            cluster_article_ids = [
                item['article_id'] for item in cluster_results 
                if item['cluster_id'] == cluster_id
            ]
            
            if not cluster_article_ids:
                console.print(f"[yellow]클러스터 {cluster_id}에 속한 기사가 없습니다.[/yellow]")
                return []
            
            # Supabase에서 해당 기사들의 상세 정보 조회
            response = self.supabase.table("articles").select("*").in_("id", cluster_article_ids).execute()
            
            if response is None:
                console.print(f"[bold red]클러스터 {cluster_id} 기사 조회 응답이 None입니다.[/bold red]")
                return []
            
            if not hasattr(response, 'data') or response.data is None:
                console.print(f"[bold red]클러스터 {cluster_id} 기사 조회 데이터가 None입니다.[/bold red]")
                return []
            
            console.print(f"[cyan]클러스터 {cluster_id}에서 {len(response.data)}개 기사 조회 완료[/cyan]")
            return response.data
            
        except Exception as e:
            console.print(f"[bold red]클러스터 {cluster_id} 기사 조회 중 오류 발생: {e}[/bold red]")
            return []
    
    def calculate_bias_ratio(self, articles: List[Dict[str, Any]]) -> Dict[str, float]:
        """기사들의 bias 비율을 계산합니다."""
        try:
            bias_counts = {"left": 0, "center": 0, "right": 0}
            total = len(articles)
            
            for article in articles:
                bias = article.get('bias', 'center')
                if bias in bias_counts:
                    bias_counts[bias] += 1
            
            return {
                "bias_left": bias_counts["left"] / total if total > 0 else 0,
                "bias_center": bias_counts["center"] / total if total > 0 else 0,
                "bias_right": bias_counts["right"] / total if total > 0 else 0
            }
        except Exception as e:
            console.print(f"[bold red]Bias 비율 계산 중 오류 발생: {e}[/bold red]")
            return {
                "bias_left": 0.0,
                "bias_center": 1.0,
                "bias_right": 0.0
            }
    
    def select_representative_image(self, articles: List[Dict[str, Any]]) -> Optional[str]:
        """대표 이미지 URL을 선택합니다."""
        try:
            image_urls = [article.get('image_url') for article in articles if article.get('image_url')]
            return random.choice(image_urls) if image_urls else None
        except Exception as e:
            console.print(f"[bold red]대표 이미지 선택 중 오류 발생: {e}[/bold red]")
            return None
    
    def generate_issue_summary(self, articles: List[Dict[str, Any]]) -> str:
        """GPT를 사용하여 클러스터의 기사들을 요약합니다."""
        if not articles:
            return ""
        
        try:
            # 제목과 내용을 모아서 요약용 텍스트 생성
            titles = [article.get('title', '') for article in articles]
            contents = [article.get('content_full', '') for article in articles]
            
            # 텍스트 길이 제한 (GPT 토큰 제한 고려)
            combined_text = "\n\n".join([
                f"제목: {title}\n내용: {content[:500]}..." 
                for title, content in zip(titles, contents)
            ])
            
            if len(combined_text) > 3000:  # 토큰 제한 고려
                combined_text = combined_text[:3000] + "..."
            
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system",
                        "content": "다음 기사들을 읽고 핵심 이슈를 간결하게 요약해주세요. 200자 이내로 작성해주세요."
                    },
                    {
                        "role": "user",
                        "content": f"다음 기사들을 분석해주세요:\n\n{combined_text}"
                    }
                ],
                max_tokens=300,
                temperature=0.7
            )
            
            if response is None or not hasattr(response, 'choices') or not response.choices:
                console.print("[yellow]OpenAI 응답이 비어있습니다. 기본 요약을 사용합니다.[/yellow]")
                return f"{len(articles)}개 기사가 포함된 이슈"
            
            content = response.choices[0].message.content
            return content.strip() if content else f"{len(articles)}개 기사가 포함된 이슈"
            
        except Exception as e:
            console.print(f"[bold red]요약 생성 중 오류 발생: {e}[/bold red]")
            # 기본 요약 생성
            return f"{len(articles)}개 기사가 포함된 이슈"
    
    def generate_issue_title(self, articles: List[Dict[str, Any]]) -> str:
        """GPT를 사용하여 이슈 제목을 생성합니다."""
        if not articles:
            return "기본 이슈 제목"
        
        try:
            # 대표 제목들 선택
            titles = [article.get('title', '') for article in articles[:5]]  # 처음 5개만
            titles_text = "\n".join([f"- {title}" for title in titles if title])
            
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system",
                        "content": "다음 기사들의 제목을 참고하여 짧고 명확한 이슈 제목을 생성해주세요. 50자 이내로 작성해주세요."
                    },
                    {
                        "role": "user",
                        "content": f"다음 기사 제목들을 참고하여 이슈 제목을 만들어주세요:\n\n{titles_text}"
                    }
                ],
                max_tokens=100,
                temperature=0.7
            )
            
            if response is None or not hasattr(response, 'choices') or not response.choices:
                console.print("[yellow]OpenAI 응답이 비어있습니다. 기본 제목을 사용합니다.[/yellow]")
                return f"이슈 {len(articles)}개 기사"
            
            content = response.choices[0].message.content
            return content.strip() if content else f"이슈 {len(articles)}개 기사"
            
        except Exception as e:
            console.print(f"[bold red]제목 생성 중 오류 발생: {e}[/bold red]")
            # 기본 제목 생성
            return f"이슈 {len(articles)}개 기사"
    
    def create_issue_data(self, cluster_id: int, articles: List[Dict[str, Any]]) -> Dict[str, Any]:
        """이슈 데이터를 생성합니다."""
        if not articles:
            console.print(f"[yellow]클러스터 {cluster_id}에 기사가 없습니다.[/yellow]")
            return {}
        
        try:
            # bias 비율 계산
            bias_ratios = self.calculate_bias_ratio(articles)
            
            # 대표 이미지 선택
            image_url = self.select_representative_image(articles)
            
            # 요약 및 제목 생성
            summary = self.generate_issue_summary(articles)
            title = self.generate_issue_title(articles)
            
            # 가장 우세한 bias 계산
            dominant_bias = max(bias_ratios.items(), key=lambda x: x[1])[0].replace("bias_", "")
            
            return {
                "id": str(uuid.uuid4()),
                "title": title,
                "summary": summary,
                "image_url": image_url,
                "image_swipe_url": None,
                "bias_left_pct": bias_ratios["bias_left"],
                "bias_center_pct": bias_ratios["bias_center"],
                "bias_right_pct": bias_ratios["bias_right"],
                "dominant_bias": dominant_bias,
                "source_count": len(articles),
                "updated_at": datetime.utcnow().isoformat() + "Z"
            }
        except Exception as e:
            console.print(f"[bold red]이슈 데이터 생성 중 오류 발생: {e}[/bold red]")
            return {}
    
    def save_issue_to_supabase(self, issue_data: Dict[str, Any]) -> bool:
        """이슈를 Supabase에 저장합니다."""
        try:
            response = self.supabase.table("issues").insert(issue_data).execute()
            console.print(f"[bold green]✅ 이슈 저장 완료: {issue_data['title']}[/bold green]")
            return True
        except Exception as e:
            console.print(f"[bold red]이슈 저장 중 오류 발생: {e}[/bold red]")
            return False
    
    def get_cluster_ids(self, cluster_results: List[Dict[str, Any]]) -> List[int]:
        """클러스터 ID 목록을 추출합니다 (노이즈 제외)."""
        cluster_ids = set()
        for item in cluster_results:
            cluster_id = item['cluster_id']
            if cluster_id != -1:  # 노이즈 제외
                cluster_ids.add(cluster_id)
        return sorted(list(cluster_ids))
    
    def save_cluster_issue_mapping(self, cluster_issue_mapping: Dict[int, str], filename: str = "cluster_issue_mapping.json"):
        """클러스터 ID와 이슈 ID 매핑을 저장합니다."""
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(cluster_issue_mapping, f, ensure_ascii=False, indent=2)
            console.print(f"[bold green]✅ 클러스터-이슈 매핑이 {filename}에 저장되었습니다.[/bold green]")
        except Exception as e:
            console.print(f"[bold red]매핑 저장 중 오류 발생: {e}[/bold red]")
    
    def run(self):
        """전체 이슈 생성 프로세스를 실행합니다."""
        console.print("[bold green]=== 이슈 생성 시작 ===[/bold green]")
        
        # 클러스터 결과 로드
        cluster_results = self.load_cluster_results()
        if not cluster_results:
            console.print("[bold red]클러스터 결과를 로드할 수 없습니다.[/bold red]")
            return
        
        # 클러스터 ID 목록 추출 (노이즈 제외)
        cluster_ids = self.get_cluster_ids(cluster_results)
        console.print(f"[cyan]처리할 클러스터 수: {len(cluster_ids)}[/cyan]")
        
        cluster_issue_mapping = {}
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console
        ) as progress:
            task = progress.add_task("[bold blue]이슈 생성", total=len(cluster_ids))
            
            for i, cluster_id in enumerate(cluster_ids):
                # 클러스터에 속한 기사들 조회
                articles = self.get_articles_by_cluster(cluster_id)
                
                if not articles:
                    progress.update(task, advance=1)
                    continue
                
                # 이슈 데이터 생성
                issue_data = self.create_issue_data(cluster_id, articles)
                
                if not issue_data:
                    progress.update(task, advance=1)
                    continue
                
                # Supabase에 저장
                if self.save_issue_to_supabase(issue_data):
                    cluster_issue_mapping[cluster_id] = issue_data['id']
                    progress.update(task, advance=1)
                else:
                    progress.update(task, advance=1)
        
        # 매핑 저장
        if cluster_issue_mapping:
            self.save_cluster_issue_mapping(cluster_issue_mapping)
            console.print(f"[bold green]✅ 총 {len(cluster_issue_mapping)}개 이슈가 생성되었습니다.[/bold green]")
        else:
            console.print("[bold yellow]생성된 이슈가 없습니다.[/bold yellow]")

if __name__ == "__main__":
    generator = IssueGenerator()
    generator.run() 