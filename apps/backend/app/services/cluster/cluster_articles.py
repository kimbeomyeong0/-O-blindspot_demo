import json
import numpy as np
from typing import List, Dict, Any
from sklearn.cluster import DBSCAN
from sklearn.metrics.pairwise import cosine_similarity
import sys
import os
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
import argparse
import matplotlib.pyplot as plt
from sklearn.metrics import silhouette_score

# 프로젝트 루트 경로 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))))

# rich 콘솔
console = Console()

class ArticleClusterer:
    def __init__(self, eps: float = 1.2, min_samples: int = 2):
        self.eps = eps
        self.min_samples = min_samples
        self.clusterer = DBSCAN(eps=eps, min_samples=min_samples, metric='cosine')
    
    def load_embeddings(self, filename: str = "article_embeddings.json") -> List[Dict[str, Any]]:
        """저장된 임베딩 데이터를 불러옵니다."""
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                data = json.load(f)
            console.print(f"[cyan]임베딩 데이터 로드 완료: {len(data)}개 기사[/cyan]")
            return data
        except FileNotFoundError:
            console.print(f"[bold red]파일을 찾을 수 없습니다: {filename}[/bold red]")
            return []
        except Exception as e:
            console.print(f"[bold red]파일 로드 중 오류 발생: {e}[/bold red]")
            return []
    
    def prepare_vectors(self, embeddings_data: List[Dict[str, Any]]) -> tuple[np.ndarray, List[str]]:
        """임베딩 데이터에서 벡터만 추출하여 numpy 배열로 변환합니다."""
        vectors = []
        article_ids = []
        
        for item in embeddings_data:
            if 'embedding' in item and item['embedding']:
                vectors.append(item['embedding'])
                article_ids.append(item['article_id'])
        
        if not vectors:
            console.print("[bold red]유효한 임베딩 벡터가 없습니다.[/bold red]")
            return np.array([]), []
        
        return np.array(vectors), article_ids
    
    def perform_clustering(self, vectors: np.ndarray) -> np.ndarray:
        """DBSCAN 클러스터링을 수행합니다."""
        if len(vectors) == 0:
            console.print("[bold red]클러스터링할 벡터가 없습니다.[/bold red]")
            return np.array([])
        
        console.print(f"[cyan]클러스터링 시작: {len(vectors)}개 벡터[/cyan]")
        console.print(f"[cyan]파라미터: eps={self.eps}, min_samples={self.min_samples}[/cyan]")
        
        # 코사인 유사도 기반 클러스터링
        cluster_labels = self.clusterer.fit_predict(vectors)
        
        # 클러스터 통계
        unique_labels = np.unique(cluster_labels)
        n_clusters = len(unique_labels) - (1 if -1 in cluster_labels else 0)
        n_noise = list(cluster_labels).count(-1)
        
        console.print(f"[bold green]클러스터링 완료:[/bold green]")
        console.print(f"[cyan]  - 총 클러스터 수: {n_clusters}[/cyan]")
        console.print(f"[cyan]  - 노이즈 포인트 수: {n_noise}[/cyan]")
        console.print(f"[cyan]  - 클러스터 라벨: {unique_labels}[/cyan]")
        
        return cluster_labels
    
    def create_cluster_results(self, embeddings_data: List[Dict[str, Any]], cluster_labels: np.ndarray, article_ids: List[str]) -> List[Dict[str, Any]]:
        """클러스터링 결과를 정리합니다."""
        if len(cluster_labels) == 0:
            return []
        
        # article_id와 cluster_label 매핑
        id_to_label = dict(zip(article_ids, cluster_labels))
        
        cluster_results = []
        
        for item in embeddings_data:
            article_id = item['article_id']
            if article_id in id_to_label:
                cluster_results.append({
                    'article_id': article_id,
                    'title': item.get('title', ''),
                    'cluster_id': int(id_to_label[article_id]),
                    'text_length': item.get('text_length', 0)
                })
        
        return cluster_results
    
    def analyze_clusters(self, cluster_results: List[Dict[str, Any]]):
        """클러스터 분석 결과를 출력합니다."""
        if not cluster_results:
            return
        
        # 클러스터별 통계
        cluster_stats = {}
        for item in cluster_results:
            cluster_id = item['cluster_id']
            if cluster_id not in cluster_stats:
                cluster_stats[cluster_id] = {
                    'count': 0,
                    'titles': []
                }
            cluster_stats[cluster_id]['count'] += 1
            cluster_stats[cluster_id]['titles'].append(item['title'][:50])
        
        console.print("\n[bold green]=== 클러스터 분석 ===[/bold green]")
        for cluster_id, stats in sorted(cluster_stats.items()):
            if cluster_id == -1:
                console.print(f"[yellow]노이즈 클러스터 (-1): {stats['count']}개 기사[/yellow]")
            else:
                console.print(f"[bold blue]클러스터 {cluster_id}: {stats['count']}개 기사[/bold blue]")
                console.print(f"[cyan]  대표 제목들:[/cyan]")
                for title in stats['titles'][:3]:  # 처음 3개만 표시
                    console.print(f"    - {title}...")
                if len(stats['titles']) > 3:
                    console.print(f"    ... 외 {len(stats['titles']) - 3}개")
                console.print()
    
    def save_cluster_results(self, cluster_results: List[Dict[str, Any]], filename: str = "cluster_results.json"):
        """클러스터링 결과를 JSON 파일로 저장합니다."""
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(cluster_results, f, ensure_ascii=False, indent=2)
            
            console.print(f"[bold green]✅ 클러스터링 결과가 {filename}에 저장되었습니다.[/bold green]")
            console.print(f"[cyan]총 {len(cluster_results)}개의 기사가 클러스터링되었습니다.[/cyan]")
            
        except Exception as e:
            console.print(f"[bold red]파일 저장 중 오류 발생: {e}[/bold red]")

def compute_k_distance(vectors: np.ndarray, k: int) -> np.ndarray:
    from sklearn.neighbors import NearestNeighbors
    nbrs = NearestNeighbors(n_neighbors=k).fit(vectors)
    distances, _ = nbrs.kneighbors(vectors)
    # k번째 이웃 거리만 추출
    k_distances = np.sort(distances[:, k-1])
    return k_distances

def plot_k_distance(vectors: np.ndarray, k: int, save_path: str):
    k_distances = compute_k_distance(vectors, k)
    plt.figure(figsize=(10, 5))
    plt.plot(range(1, len(k_distances)+1), k_distances)
    plt.xlabel('Points sorted by distance')
    plt.ylabel(f'{k}-th Nearest Neighbor Distance')
    plt.title(f'k-distance Plot (k={k})')
    plt.grid(True)
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    plt.savefig(save_path)
    plt.close()
    console.print(f"[bold green]k-distance plot이 {save_path}에 저장되었습니다.[/bold green]")

def grid_search_dbscan(vectors: np.ndarray, eps_list, min_samples_list) -> tuple:
    best_score = -1
    best_params = None
    best_labels = None
    for eps in eps_list:
        for min_samples in min_samples_list:
            clusterer = DBSCAN(eps=eps, min_samples=min_samples, metric='cosine')
            labels = clusterer.fit_predict(vectors)
            n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
            n_noise = list(labels).count(-1)
            if n_clusters < 2 or n_clusters == len(vectors):
                continue  # 실루엣 점수 계산 불가
            try:
                score = silhouette_score(vectors, labels, metric='cosine')
            except Exception:
                score = -1
            if score > best_score:
                best_score = score
                best_params = (eps, min_samples, n_clusters, n_noise)
                best_labels = labels
    return best_score, best_params, best_labels

def main():
    parser = argparse.ArgumentParser(description="기사 클러스터링")
    parser.add_argument('--eps', type=float, default=0.15, help='DBSCAN eps')
    parser.add_argument('--min_samples', type=int, default=5, help='DBSCAN min_samples')
    parser.add_argument('--grid-search', action='store_true', help='여러 파라미터 조합 실험')
    parser.add_argument('--k', type=int, default=5, help='k-distance plot용 k')
    parser.add_argument('--plot-k-distance', action='store_true', help='k-distance plot 저장')
    parser.add_argument('--embeddings', type=str, default='article_embeddings.json', help='임베딩 파일 경로')
    args = parser.parse_args()

    clusterer = ArticleClusterer(eps=args.eps, min_samples=args.min_samples)
    embeddings_data = clusterer.load_embeddings(args.embeddings)
    if not embeddings_data:
        return
    vectors, article_ids = clusterer.prepare_vectors(embeddings_data)
    if len(vectors) == 0:
        return

    if args.plot_k_distance:
        plot_k_distance(vectors, args.k, 'reports/k_distance.png')
        return

    if args.grid_search:
        eps_list = [0.10, 0.15, 0.20, 0.25]
        min_samples_list = [3, 5, 7]
        best_score, best_params, best_labels = grid_search_dbscan(vectors, eps_list, min_samples_list)
        if best_params:
            eps, min_samples, n_clusters, n_noise = best_params
            console.print(f"[bold green]최고 실루엣 점수: {best_score:.4f}")
            console.print(f"[bold green]최적 파라미터: eps={eps}, min_samples={min_samples}")
            console.print(f"[cyan]클러스터 수: {n_clusters}, 노이즈 수: {n_noise}[/cyan]")
        else:
            console.print("[red]유효한 클러스터링 결과가 없습니다.[/red]")
        return

    # 일반 클러스터링 실행
    cluster_labels = clusterer.perform_clustering(vectors)
    if len(cluster_labels) == 0:
        return
    n_clusters = len(set(cluster_labels)) - (1 if -1 in cluster_labels else 0)
    n_noise = list(cluster_labels).count(-1)
    if n_clusters > 1:
        try:
            sil_score = silhouette_score(vectors, cluster_labels, metric='cosine')
        except Exception:
            sil_score = -1
    else:
        sil_score = -1
    console.print(f"[bold green]실루엣 점수: {sil_score:.4f}")
    console.print(f"[cyan]클러스터 수: {n_clusters}, 노이즈 비율: {n_noise/len(vectors):.2%}[/cyan]")
    cluster_results = clusterer.create_cluster_results(embeddings_data, cluster_labels, article_ids)
    clusterer.analyze_clusters(cluster_results)
    clusterer.save_cluster_results(cluster_results)
    console.print("[bold green]=== 클러스터링 완료 ===[/bold green]")

if __name__ == "__main__":
    main() 