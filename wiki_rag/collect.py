"""
Phase 1: Paper collection and extraction.

Downloads TeX or PDF from ArXiv, extracts structured content.
Zero LLM calls — pure Python with no API dependencies.
"""

import json
import re
import urllib.request
import tarfile
from pathlib import Path
from io import BytesIO
from .config import Config

__all__ = ["collect_paper", "collect_batch", "Collector"]


def slugify(arxiv_id: str) -> str:
    """Normalize arxiv id: strip version suffix."""
    return re.sub(r'v\d+$', '', arxiv_id.strip())


def download_source(arxiv_id: str):
    """
    Download paper source from ArXiv.
    Returns (content_bytes, mime_type) or (None, None).
    
    Priority: TeX tar.gz → PDF
    """
    sid = slugify(arxiv_id)
    headers = {'User-Agent': Config.USER_AGENT}
    
    # Try TeX source
    for url in [f"https://arxiv.org/e-print/{sid}", f"https://arxiv.org/src/{sid}"]:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=Config.REQUEST_TIMEOUT) as resp:
                data = resp.read()
            if len(data) > 2 and data[0] == 0x1f and data[1] == 0x8b:
                return data, "tex"
            if len(data) > 4 and data[:4] == b'%PDF':
                return data, "pdf"
        except Exception:
            continue
    
    # Try PDF directly
    try:
        url = f"https://arxiv.org/pdf/{sid}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=Config.REQUEST_TIMEOUT) as resp:
            data = resp.read()
        if len(data) > 4 and data[:4] == b'%PDF':
            return data, "pdf"
    except Exception:
        pass
    
    return None, None


def extract_tex(tar_bytes: bytes) -> str:
    """Extract main .tex file from ArXiv tar.gz."""
    with tarfile.open(fileobj=BytesIO(tar_bytes), mode='r:gz') as tar:
        tex_files = sorted(
            [m for m in tar.getmembers() if m.name.endswith('.tex')],
            key=lambda m: m.size, reverse=True
        )
        if not tex_files:
            return ""
        content = tar.extractfile(tex_files[0]).read().decode('utf-8', errors='replace')
        # If main file is small, concatenate all .tex files
        if len(content) < 2000 and len(tex_files) > 1:
            parts = []
            for tf in tex_files[:5]:
                c = tar.extractfile(tf)
                if c:
                    parts.append(c.read().decode('utf-8', errors='replace'))
            content = '\n\n'.join(parts)
    return content


def strip_latex(text: str) -> str:
    """Convert LaTeX to plain markdown text."""
    text = re.sub(r'(?<!\\)%.*$', '', text, flags=re.MULTILINE)
    
    doc_start = re.search(r'\\begin\{document\}', text)
    doc_end = re.search(r'\\end\{document\}', text)
    if doc_start and doc_end:
        text = text[doc_start.end():doc_end.start()]
    elif doc_start:
        text = text[doc_start.end():]
    
    # Tables
    text = _convert_tabular(text)
    
    # Remove environments
    for env in ['figure', 'table', 'table*', 'algorithm', 'algorithmic', 'tikzpicture',
                'itemize', 'enumerate', 'description', 'minipage']:
        text = re.sub(r'\\begin\{' + env + r'\}.*?\\end\{' + env + r'\}', '', text, flags=re.DOTALL)
    
    # Sections → markdown
    text = re.sub(r'\\section\*?\{([^}]*)\}', r'\n## \1\n', text)
    text = re.sub(r'\\subsection\*?\{([^}]*)\}', r'\n### \1\n', text)
    text = re.sub(r'\\subsubsection\*?\{([^}]*)\}', r'\n#### \1\n', text)
    
    # Formatting
    for cmd in ['textbf', 'textit', 'emph', 'textsc', 'texttt']:
        text = re.sub(r'\\' + cmd + r'\{([^}]*)\}', r'\1', text)
    
    # Citations
    text = re.sub(r'\\(cite\w*|ref|label)\*?(\[[^\]]*\])?\{[^}]*\}', '', text)
    
    # Remaining commands
    text = re.sub(r'\\[a-zA-Z]+\*?(?:\[[^\]]*\])?(?:\{[^}]*\})?', '', text)
    text = re.sub(r'\\[a-zA-Z]+\b', '', text)
    
    # Clean
    text = re.sub(r'\$[^$]+\$', '', text)
    text = re.sub(r'[{}]', '', text)
    text = re.sub(r' {3,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text.strip()


def _convert_tabular(text: str) -> str:
    """Convert LaTeX tabular to markdown table."""
    def replace(m):
        content = m.group(1)
        rows = re.sub(r'\\\\', '\n', content)
        rows = re.sub(r'\\hline', '', rows)
        lines = [l.strip() for l in rows.split('\n') if l.strip()]
        if not lines:
            return ''
        md = []
        for line in lines:
            line = re.sub(r'\s*&\s*', ' | ', line.strip('&').strip())
            md.append(f'| {line} |')
        if len(md) > 1:
            cols = md[0].count('|') - 1
            md.insert(1, '|' + ' --- |' * cols)
        return '\n' + '\n'.join(md) + '\n'
    
    return re.sub(r'\\begin\{tabular\}\{[^}]*\}(.*?)\\end\{tabular\}', replace, text, flags=re.DOTALL)


def extract_structure(tex: str) -> dict:
    """Extract structured data from TeX content."""
    s = {"title": "", "abstract": "", "sections": [], "equations": [], "tables": [], "figures": []}
    
    m = re.search(r'\\title\{([^}]*)\}', tex)
    if m: s["title"] = m.group(1).strip()
    
    m = re.search(r'\\begin\{abstract\}(.*?)\\end\{abstract\}', tex, re.DOTALL)
    if m: s["abstract"] = m.group(1).strip()
    
    for m in re.finditer(r'\\(section|subsection|subsubsection)\*?\{([^}]*)\}', tex):
        s["sections"].append({"level": m.group(1), "title": m.group(2).strip()})
    
    for m in re.finditer(r'\$\$(.*?)\$\$', tex, re.DOTALL):
        s["equations"].append(m.group(1).strip())
    
    for m in re.finditer(r'\\begin\{tabular\}\{[^}]*\}(.*?)\\end\{tabular\}', tex, re.DOTALL):
        s["tables"].append(m.group(1).strip()[:500])
    
    for m in re.finditer(r'\\begin\{figure\}.*?\\caption\{([^}]*)\}', tex, re.DOTALL):
        s["figures"].append(m.group(1).strip())
    
    return s


def is_digital_pdf(pdf_bytes: bytes) -> bool:
    """Check if PDF has extractable text (not scanned)."""
    if not pdf_bytes or len(pdf_bytes) < 100:
        return False
    try:
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if len(doc) == 0:
            doc.close()
            return False
        text_pages = sum(1 for p in doc if len(p.get_text().strip()) > 100)
        doc.close()
        return text_pages / len(doc) > 0.7
    except ImportError:
        return False
    except Exception:
        return False


def extract_pdf_text(pdf_bytes: bytes) -> dict:
    """Extract text from digital PDF. In-memory, no disk I/O."""
    import fitz
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    structure = {"title": "", "abstract": "", "sections": [], "pages": []}
    
    for i, page in enumerate(doc):
        text = page.get_text()
        structure["pages"].append({"page_num": i + 1, "text": text})
        
        if i == 0:
            structure["title"] = text.split('\n')[0].strip() if text else ""
            if 'abstract' in text.lower():
                idx = text.lower().index('abstract')
                abs_text = text[idx:idx+1500]
                end = re.search(r'\n\s*\n\s*\n|\n\d+\.\s+[A-Z]', abs_text[200:])
                structure["abstract"] = abs_text[:end.start()+200].strip() if end else abs_text.strip()
    
    doc.close()
    return structure


def collect_paper(arxiv_id: str) -> dict:
    """
    Collect a single paper. Phase 1 of the pipeline.
    
    Returns:
        {
            "arxiv_id": str,
            "source_type": "tex" | "pdf" | None,
            "markdown": str,
            "json": dict,
            "success": bool,
            "error": str | None
        }
    """
    result = {"arxiv_id": arxiv_id, "source_type": None, "markdown": "", "json": {}, "success": False, "error": None}
    sid = slugify(arxiv_id)
    
    data, mime = download_source(arxiv_id)
    if not data:
        result["error"] = "Could not download paper"
        return result
    
    if mime == "tex":
        result["source_type"] = "tex"
        tex = extract_tex(data)
        if not tex:
            result["error"] = "No TeX files found in archive"
            return result
        
        markdown = strip_latex(tex)
        structure = extract_structure(tex)
        
        result["markdown"] = f"# Paper {sid}\n\n**Source:** tex\n\n{markdown}"
        result["json"] = structure
        result["success"] = True
        
    elif mime == "pdf":
        if not is_digital_pdf(data):
            result["error"] = "PDF is scanned (no extractable text)"
            return result
        
        result["source_type"] = "pdf"
        structure = extract_pdf_text(data)
        
        md_lines = [f"# Paper {sid}", "", "**Source:** pdf", ""]
        for page in structure.get("pages", []):
            md_lines += [f"## Page {page['page_num']}", "", page["text"], ""]
        
        result["markdown"] = "\n".join(md_lines)
        result["json"] = structure
        result["success"] = True
    
    return result


def collect_batch(arxiv_ids: list, max_workers: int = 3) -> list:
    """Collect multiple papers. Returns list of results."""
    return [collect_paper(aid) for aid in arxiv_ids[:max_workers]]


class Collector:
    """Stateful collector with manifest tracking."""
    
    def __init__(self, wiki_path: Path = None):
        self.config = Config()
        if wiki_path:
            self.config.WIKI_PATH = Path(wiki_path)
        self.config.ensure_dirs()
        self.manifest = self._load_manifest()
    
    def _load_manifest(self) -> list:
        if self.config.MANIFEST_PATH.exists():
            return json.loads(self.config.MANIFEST_PATH.read_text())
        return []
    
    def _save_manifest(self):
        self.config.MANIFEST_PATH.write_text(json.dumps(self.manifest, indent=2))
    
    def _is_collected(self, arxiv_id: str) -> bool:
        sid = slugify(arxiv_id)
        return any(slugify(e.get("arxiv_id", "")) == sid for e in self.manifest)
    
    def collect(self, arxiv_id: str, title: str = "", authors: str = "", abstract: str = "") -> dict:
        """Collect and save a paper. Updates manifest."""
        if self._is_collected(arxiv_id):
            return {"arxiv_id": arxiv_id, "success": False, "error": "Already collected"}
        
        result = collect_paper(arxiv_id)
        
        if result["success"]:
            sid = slugify(arxiv_id)
            today = date.today().isoformat()
            
            # Save files
            md_path = self.config.RAW_DIR / f"{today}-{sid}.md"
            json_path = self.config.RAW_DIR / f"{today}-{sid}.json"
            md_path.write_text(result["markdown"], encoding="utf-8")
            json_path.write_text(json.dumps(result["json"], indent=2), encoding="utf-8")
            
            # Update manifest
            self.manifest.append({
                "arxiv_id": arxiv_id, "title": title, "authors": authors,
                "abstract": abstract[:500], "raw_path": str(md_path),
                "json_path": str(json_path), "source_type": result["source_type"],
                "collected_at": today, "ingested": False
            })
            self._save_manifest()
        
        return result
