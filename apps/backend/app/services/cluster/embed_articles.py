import os
import json
import numpy as np
from typing import List, Dict, Any
from openai import OpenAI
from dotenv import load_dotenv
import sys
import os
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

# 프로젝트 루트 경로 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))))

from app.db.supabase_client import supabase_client

# .env 파일 로드
load_dotenv()

# rich 콘솔
console = Console()

class ArticleEmbedder:
    def __init__(self):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.supabase = supabase_client.get_client()
        self.model = "text-embedding-3-small"
    
    def get_articles_without_issue(self) -> List[Dict[str, Any]]:
        """issue_id가 null인 기사들을 가져옵니다."""
        try:
            response = self.supabase.table("articles").select("*").is_("issue_id", "null").execute()
            return response.data
        except Exception as e:
            console.print(f"[bold red]기사 조회 중 오류 발생: {e}[/bold red]")
            return []
    
    def create_embedding(self, text: str) -> List[float]:
        """텍스트를 임베딩 벡터로 변환합니다."""
        try:
            response = self.client.embeddings.create(
                input=text,
                model=self.model
            )
            return response.data[0].embedding
        except Exception as e:
            console.print(f"[bold red]임베딩 생성 중 오류 발생: {e}[/bold red]")
            return []
    
    def process_articles(self) -> List[Dict[str, Any]]:
        """기사들을 임베딩 벡터로 변환합니다."""
        articles = self.get_articles_without_issue()
        console.print(f"[cyan]처리할 기사 수: {len(articles)}[/cyan]")
        
        embeddings_data = []
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console
        ) as progress:
            task = progress.add_task("[bold blue]기사 임베딩 생성", total=len(articles))
            
            for i, article in enumerate(articles):
                # title과 content_full을 결합
                title = article.get('title', '')
                content_full = article.get('content_full', '')
                combined_text = f"{title}\n\n{content_full}".strip()
                
                if not combined_text:
                    progress.update(task, advance=1)
                    continue
                
                # 텍스트 길이 제한 (토큰 제한 고려)
                # 대략적으로 1 토큰 = 4 문자로 계산
                max_chars = 6000  # 1500 토큰 정도로 제한
                if len(combined_text) > max_chars:
                    combined_text = combined_text[:max_chars]
                    console.print(f"[yellow]텍스트가 너무 길어서 {max_chars}자로 잘렸습니다.[/yellow]")
                
                # 임베딩 생성
                embedding = self.create_embedding(combined_text)
                
                if embedding:
                    embeddings_data.append({
                        'article_id': article['id'],
                        'title': title,
                        'embedding': embedding,
                        'text_length': len(combined_text)
                    })
                    progress.update(task, advance=1)
                else:
                    progress.update(task, advance=1)
        
        return embeddings_data
    
    def save_embeddings(self, embeddings_data: List[Dict[str, Any]], filename: str = "article_embeddings.json"):
        """임베딩 데이터를 JSON 파일로 저장합니다."""
        try:
            # numpy array를 리스트로 변환
            for item in embeddings_data:
                item['embedding'] = item['embedding'].tolist() if isinstance(item['embedding'], np.ndarray) else item['embedding']
            
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(embeddings_data, f, ensure_ascii=False, indent=2)
            
            console.print(f"[bold green]✅ 임베딩 데이터가 {filename}에 저장되었습니다.[/bold green]")
            console.print(f"[cyan]총 {len(embeddings_data)}개의 기사 임베딩이 저장되었습니다.[/cyan]")
            
        except Exception as e:
            console.print(f"[bold red]파일 저장 중 오류 발생: {e}[/bold red]")
    
    def run(self):
        """전체 임베딩 프로세스를 실행합니다."""
        console.print("[bold green]=== 기사 임베딩 시작 ===[/bold green]")
        
        embeddings_data = self.process_articles()
        
        if embeddings_data:
            self.save_embeddings(embeddings_data)
            console.print("[bold green]=== 임베딩 완료 ===[/bold green]")
        else:
            console.print("[bold yellow]처리할 기사가 없거나 오류가 발생했습니다.[/bold yellow]")

if __name__ == "__main__":
    embedder = ArticleEmbedder()
    embedder.run() 