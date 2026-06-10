"""
GitHub repo and metadata collection for ArXiv papers.

Extracts repository links, stars, and related metadata from:
1. HuggingFace Papers (hf.co/papers)
2. ArXiv HTML pages (fallback)
3. GitHub search API (last resort)

Zero LLM calls — pure HTTP + HTML parsing.
"""

import json
import re
import urllib.request
import urllib.error
from pathlib import Path
from html.parser import HTMLParser

__all__ = ["extract_github_repos", "get_hf_paper_metadata", "get_github_stars"]


def get_hf_paper_metadata(arxiv_id: str) -> dict:
    """
    Fetch paper metadata from HuggingFace Papers.
    
    HF Papers includes: GitHub repo, stars, models, datasets, Spaces.
    URL format: https://huggingface.co/papers/{arxiv_id}
    
    Returns:
        {
            "github_repo": str | None,  # e.g., "facebookresearch/fairseq"
            "github_stars": int | None,
            "hf_paper_url": str,
            "models": list,
            "datasets": list,
            "spaces": list,
            "found": bool
        }
    """
    result = {
        "github_repo": None,
        "github_stars": None,
        "hf_paper_url": f"https://huggingface.co/papers/{arxiv_id}",
        "models": [],
        "datasets": [],
        "spaces": [],
        "found": False
    }
    
    try:
        url = f"https://huggingface.co/papers/{arxiv_id}"
        req = urllib.request.Request(url, headers={'User-Agent': 'wiki-rag/1.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode('utf-8', errors='replace')
        
        # Check if paper exists (404 returns different content)
        if "404" in html[:500] or "not found" in html[:500].lower():
            return result
        
        result["found"] = True
        
        # Extract GitHub repo link
        # Pattern: href="https://github.com/owner/repo"
        github_match = re.search(
            r'href="(https://github\.com/([^/\"]+/[^/\"]+))"',
            html
        )
        if github_match:
            result["github_repo"] = github_match.group(2)
        
        # Extract stars count
        # Pattern: "stars": 1234 or "stargazers_count": 1234
        stars_match = re.search(r'"stargazers_count":\s*(\d+)', html)
        if not stars_match:
            stars_match = re.search(r'"stars":\s*(\d+)', html)
        if stars_match:
            result["github_stars"] = int(stars_match.group(1))
        
        # Extract linked models
        for m in re.finditer(r'href="/([^"]+)"[^>]*>[^<]*model[^<]*</a>', html, re.IGNORECASE):
            result["models"].append(m.group(1))
        
        # Extract linked datasets
        for m in re.finditer(r'href="/datasets/([^"]+)"', html):
            result["datasets"].append(m.group(1))
        
    except urllib.error.HTTPError as e:
        if e.code == 404:
            pass  # Paper not on HF
        else:
            raise
    except Exception:
        pass
    
    return result


def extract_github_repos_from_html(html: str) -> list:
    """
    Extract GitHub repo links from ArXiv HTML page.
    
    Returns:
        List of {"url": str, "owner": str, "repo": str}
    """
    repos = []
    seen = set()
    
    # Match github.com/owner/repo patterns
    for match in re.finditer(
        r'https://github\.com/([^/\s\)]+/[^/\s\)\]]+)',
        html
    ):
        url = match.group(0)
        # Clean trailing punctuation
        url = url.rstrip('.,;:\'\"')
        
        # Extract owner/repo
        parts = url.replace('https://github.com/', '').split('/')
        if len(parts) >= 2:
            owner, repo = parts[0], parts[1]
            # Filter out common non-repo paths
            if owner and repo and not any(x in repo for x in ['blob', 'tree', 'pull', 'issues', 'wiki']):
                key = f"{owner}/{repo}"
                if key not in seen:
                    seen.add(key)
                    repos.append({"url": url, "owner": owner, "repo": repo})
    
    return repos


def get_arxiv_html_metadata(arxiv_id: str) -> dict:
    """
    Fetch ArXiv HTML page and extract GitHub links + metadata.
    
    Returns:
        {
            "github_repos": list,
            "project_page": str | None,
            "found": bool
        }
    """
    result = {"github_repos": [], "project_page": None, "found": False}
    
    try:
        url = f"https://arxiv.org/abs/{arxiv_id}"
        req = urllib.request.Request(url, headers={'User-Agent': 'wiki-rag/1.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode('utf-8', errors='replace')
        
        result["found"] = True
        
        # Extract GitHub repos
        result["github_repos"] = extract_github_repos_from_html(html)
        
        # Extract project page (common in ML papers)
        project_match = re.search(
            r'href="(https://(?:github\.com|gitlab\.com|bitbucket\.org)/[^"]+)"',
            html
        )
        if project_match:
            result["project_page"] = project_match.group(1)
        
    except Exception:
        pass
    
    return result


def get_github_stars(repo: str) -> int | None:
    """
    Get star count for a GitHub repo.
    
    Args:
        repo: "owner/repo" format
    
    Returns:
        Star count or None if not found
    """
    try:
        url = f"https://api.github.com/repos/{repo}"
        req = urllib.request.Request(url, headers={
            'User-Agent': 'wiki-rag/1.0',
            'Accept': 'application/vnd.github.v3+json'
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        return data.get("stargazers_count")
    except Exception:
        return None


def enrich_paper_with_repos(arxiv_id: str) -> dict:
    """
    Full enrichment pipeline for a paper.
    
    Tries multiple sources in order:
    1. HuggingFace Papers (best — includes stars, models, datasets)
    2. ArXiv HTML page (fallback — GitHub links in paper)
    3. GitHub search (last resort)
    
    Returns:
        {
            "arxiv_id": str,
            "github_repo": str | None,      # Best repo found
            "github_stars": int | None,
            "github_url": str | None,
            "hf_paper_url": str | None,
            "models": list,
            "datasets": list,
            "all_repos": list,               # All repos found
            "source": str                    # Where we found it
        }
    """
    result = {
        "arxiv_id": arxiv_id,
        "github_repo": None,
        "github_stars": None,
        "github_url": None,
        "hf_paper_url": None,
        "models": [],
        "datasets": [],
        "all_repos": [],
        "source": None
    }
    
    # Source 1: HuggingFace Papers
    hf = get_hf_paper_metadata(arxiv_id)
    if hf["found"] and hf["github_repo"]:
        result["github_repo"] = hf["github_repo"]
        result["github_stars"] = hf["github_stars"]
        result["github_url"] = f"https://github.com/{hf['github_repo']}"
        result["hf_paper_url"] = hf["hf_paper_url"]
        result["models"] = hf["models"]
        result["datasets"] = hf["datasets"]
        result["source"] = "huggingface"
        
        # If no stars from HF page, fetch from GitHub API
        if result["github_stars"] is None:
            result["github_stars"] = get_github_stars(hf["github_repo"])
    
    # Source 2: ArXiv HTML page
    arxiv = get_arxiv_html_metadata(arxiv_id)
    if arxiv["found"] and arxiv["github_repos"]:
        result["all_repos"] = arxiv["github_repos"]
        
        # If we didn't find a repo from HF, use the first one from ArXiv
        if result["github_repo"] is None:
            first_repo = arxiv["github_repos"][0]
            result["github_repo"] = f"{first_repo['owner']}/{first_repo['repo']}"
            result["github_url"] = first_repo["url"]
            result["source"] = "arxiv_html"
            
            # Fetch stars
            result["github_stars"] = get_github_stars(result["github_repo"])
    
    return result
