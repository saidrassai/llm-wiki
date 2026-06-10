"""
GitHub repo search for ArXiv papers.

Two approaches:
1. GitHub API (structured, requires token for higher rate limits)
2. Web Search (fuzzy, no token needed)

Uses API first, falls back to web search.
"""

import json
import re
import urllib.request
import urllib.error
from typing import Optional

__all__ = ["search_github_repo", "GitHubSearcher"]


def search_github_repo(
    paper_title: str,
    arxiv_id: str = None,
    github_token: str = None,
    use_web_fallback: bool = True,
) -> dict:
    """
    Search GitHub for a paper's repository.
    
    Tries GitHub API first, then web search as fallback.
    
    Args:
        paper_title: Title of the paper
        arxiv_id: ArXiv ID (optional, for more precise search)
        github_token: GitHub personal access token (optional, increases rate limit)
        use_web_fallback: Whether to try web search if API fails
    
    Returns:
        {
            "found": bool,
            "repo": str | None,      # e.g., "owner/repo"
            "url": str | None,       # e.g., "https://github.com/owner/repo"
            "stars": int | None,
            "description": str | None,
            "source": str            # "github_api" or "web_search"
        }
    """
    result = {"found": False, "repo": None, "url": None, "stars": None, "description": None, "source": None}
    
    # Try GitHub API first
    api_result = _search_github_api(paper_title, arxiv_id, github_token)
    if api_result["found"]:
        return api_result
    
    # Fallback to web search
    if use_web_fallback:
        web_result = _search_web(paper_title, arxiv_id)
        if web_result["found"]:
            return web_result
    
    return result


def _search_github_api(paper_title: str, arxiv_id: str = None, github_token: str = None) -> dict:
    """Search GitHub API for repositories."""
    result = {"found": False, "repo": None, "url": None, "stars": None, "description": None, "source": "github_api"}
    
    # Build search query
    # Clean title for search — remove special characters, keep key words
    clean_title = re.sub(r'[^\w\s-]', '', paper_title)
    clean_title = re.sub(r'\s+', ' ', clean_title).strip()
    
    # Search strategies in order of precision
    queries = []
    if arxiv_id:
        queries.append(f"arxiv:{arxiv_id} in:name,description,readme")
        queries.append(f"{arxiv_id} in:name,description,readme")
    queries.append(f"{clean_title} in:name,description,readme")
    # Shorter query if title is long
    if len(clean_title.split()) > 3:
        short_title = " ".join(clean_title.split()[:3])
        queries.append(f"{short_title} in:name,description,readme")
    
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "wiki-rag/1.0",
    }
    if github_token:
        headers["Authorization"] = f"token {github_token}"
    
    for query in queries:
        try:
            encoded_query = urllib.request.quote(query)
            url = f"https://api.github.com/search/repositories?q={encoded_query}&sort=stars&order=desc&per_page=5"
            
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            
            if data.get("items"):
                # Return the best match (highest stars)
                best = data["items"][0]
                result["found"] = True
                result["repo"] = best["full_name"]
                result["url"] = best["html_url"]
                result["stars"] = best["stargazers_count"]
                result["description"] = best.get("description", "")
                return result
                
        except urllib.error.HTTPError as e:
            if e.code == 403:  # Rate limit
                break
            continue
        except Exception:
            continue
    
    return result


def _search_web(paper_title: str, arxiv_id: str = None) -> dict:
    """Search the web for GitHub repo links."""
    result = {"found": False, "repo": None, "url": None, "stars": None, "description": None, "source": "web_search"}
    
    # Build search query
    query = f"{paper_title} github repository arxiv"
    if arxiv_id:
        query = f"{arxiv_id} github repository"
    
    try:
        # Use DuckDuckGo (no API key needed)
        encoded_query = urllib.request.quote(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded_query}"
        
        req = urllib.request.Request(url, headers={"User-Agent": "wiki-rag/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        
        # Extract GitHub links from results
        github_links = re.findall(
            r'href="(https://github\.com/([^/\"]+/[^/\"]+))"',
            html
        )
        
        if github_links:
            # Filter out common non-repo paths
            for url, repo in github_links:
                if not any(x in repo.lower() for x in ["blob", "tree", "pull", "issues", "wiki", "releases"]):
                    result["found"] = True
                    result["repo"] = repo
                    result["url"] = url
                    break
                    
    except Exception:
        pass
    
    return result


class GitHubSearcher:
    """Stateful GitHub searcher with caching."""
    
    def __init__(self, github_token: str = None, cache_path: str = None):
        self.github_token = github_token
        self.cache_path = cache_path
        self.cache = self._load_cache()
    
    def _load_cache(self) -> dict:
        if self.cache_path:
            try:
                with open(self.cache_path) as f:
                    return json.load(f)
            except:
                pass
        return {}
    
    def _save_cache(self):
        if self.cache_path:
            with open(self.cache_path, "w") as f:
                json.dump(self.cache, f, indent=2)
    
    def search(self, paper_title: str, arxiv_id: str = None) -> dict:
        """Search with caching."""
        cache_key = arxiv_id or paper_title
        
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        result = search_github_repo(
            paper_title, arxiv_id,
            github_token=self.github_token,
            use_web_fallback=True
        )
        
        self.cache[cache_key] = result
        self._save_cache()
        
        return result
    
    def batch_search(self, papers: list) -> list:
        """Search for multiple papers. Returns list of results."""
        return [self.search(p.get("title", ""), p.get("id", p.get("arxiv_id"))) for p in papers]
