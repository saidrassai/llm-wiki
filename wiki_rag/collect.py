#!/usr/bin/env python3
"""
wiki-rag-collect.py — Deterministic paper collector (zero LLM tokens)

Three-tier pipeline:
  1. TeX source (best) — structure-preserving LaTeX extraction
  2. Digital PDF (fast) — PyMuPDF in-memory text block extraction
  3. Scanned PDF — skipped (rare for ArXiv, <5%)

Usage:
  python3 wiki-rag-collect.py --max 5
  python3 wiki-rag-collect.py --max 10 --source papers.json
  python3 wiki-rag-collect.py --retry-skipped
"""

import json, re, sys, tarfile, urllib.request, urllib.error
from datetime import date
from pathlib import Path
from io import BytesIO

# ── Config ────────────────────────────────────────────────────────
WIKI_PATH = Path.home() / "wiki-rag"
RAW_DIR = WIKI_PATH / "raw" / "papers"
MANIFEST_PATH = WIKI_PATH / "manifest.json"
SCHEMA_PATH = WIKI_PATH / "SCHEMA.md"

# ── Helpers ───────────────────────────────────────────────────────

def slugify(arxiv_id: str) -> str:
    return re.sub(r'v\d+$', '', arxiv_id.strip())

def load_schema_tags() -> list:
    """Load valid tags from SCHEMA.md."""
    tags = []
    if not SCHEMA_PATH.exists():
        return tags
    for line in SCHEMA_PATH.read_text().split('\n'):
        stripped = line.strip()
        if stripped.startswith('- ') and not stripped.startswith('- ##'):
            tag = stripped[2:].strip()
            if tag and not tag.startswith('#'):
                tags.append(tag)
    return tags

def load_manifest_index() -> tuple:
    """Load manifest and return (manifest_list, id_set, skipped_ids)."""
    if not MANIFEST_PATH.exists():
        return [], set(), set()
    manifest = json.loads(MANIFEST_PATH.read_text())
    id_set = set()
    skipped_ids = set()
    for entry in manifest:
        sid = slugify(entry.get("arxiv_id", ""))
        id_set.add(sid)
        if entry.get("skipped"):
            skipped_ids.add(sid)
    return manifest, id_set, skipped_ids

# ── TeX Pipeline ──────────────────────────────────────────────────

def strip_latex(text: str) -> str:
    """Structure-preserving LaTeX to markdown conversion."""
    text = re.sub(r'(?<!\\)%.*$', '', text, flags=re.MULTILINE)
    
    doc_start = re.search(r'\\begin\{document\}', text)
    doc_end = re.search(r'\\end\{document\}', text)
    if doc_start and doc_end:
        text = text[doc_start.end():doc_end.start()]
    elif doc_start:
        text = text[doc_start.end():]
    
    text = re.sub(r'\\documentclass(\[[^\]]*\])?\{[^}]*\}', '', text)
    text = re.sub(r'\\usepackage(\[[^\]]*\])?\{[^}]*\}', '', text)
    text = re.sub(r'\\(newcommand|renewcommand|def)(\[[^\]]*\])?\{[^}]*\}(\[[^\]]*\])?(\{[^}]*\})?', '', text)
    text = _convert_tabular(text)
    
    for env in ['figure', 'table', 'table*', 'algorithm', 'algorithmic', 'tikzpicture',
                'itemize', 'enumerate', 'description', 'verbatim', 'lstlisting', 'minipage']:
        text = re.sub(r'\\begin\{' + env + r'\}.*?\\end\{' + env + r'\}', '', text, flags=re.DOTALL)
    
    text = re.sub(r'\\section\*?\{([^}]*)\}', r'\n## \1\n', text)
    text = re.sub(r'\\subsection\*?\{([^}]*)\}', r'\n### \1\n', text)
    text = re.sub(r'\\subsubsection\*?\{([^}]*)\}', r'\n#### \1\n', text)
    
    for cmd in ['textbf', 'textit', 'emph', 'underline', 'textsc', 'texttt',
                'mathrm', 'mathit', 'mathbf', 'mathbb', 'mathcal', 'mathfrak', 'text']:
        text = re.sub(r'\\' + cmd + r'\{([^}]*)\}', r'\1', text)
    
    text = re.sub(r'\\(label|ref|eqref|autoref|pageref|cite\w*|nocite|parencite|textcite)\*?(\[[^\]]*\])?\{[^}]*\}', '', text)
    text = re.sub(r'\\url\{([^}]*)\}', r'\1', text)
    text = re.sub(r'\\href\{[^}]*\}\{([^}]*)\}', r'\1', text)
    text = re.sub(r'\\footnote\{[^{}]*(\{[^}]*\}[^{}]*)*\}', '', text)
    text = re.sub(r'\\caption\*?\{([^}]*)\}', r'\n**Caption:** \1\n', text)
    text = re.sub(r'\\[a-zA-Z]+\*?(?:\[[^\]]*\])?(?:\{[^}]*\})?', '', text)
    text = re.sub(r'\\[a-zA-Z]+\b', '', text)
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

def extract_tex_structure(tex: str) -> dict:
    """Extract structured data from TeX."""
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

# ── PyMuPDF Pipeline (in-memory) ──────────────────────────────────

def is_digital_pdf(pdf_bytes: bytes) -> bool:
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
    except:
        return False

def extract_pdf_structure(pdf_bytes: bytes) -> dict:
    try:
        import fitz
    except ImportError:
        return None
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

# ── Download ───────────────────────────────────────────────────────

def download_tex(arxiv_id: str):
    sid = slugify(arxiv_id)
    for url in [f"https://arxiv.org/e-print/{sid}", f"https://arxiv.org/src/{sid}"]:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'wiki-rag/1.0'})
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
            if len(data) > 2 and data[0] == 0x1f and data[1] == 0x8b:
                with tarfile.open(fileobj=BytesIO(data), mode='r:gz') as tar:
                    tex_files = sorted([m for m in tar.getmembers() if m.name.endswith('.tex')],
                                       key=lambda m: m.size, reverse=True)
                    if tex_files:
                        content = tar.extractfile(tex_files[0]).read().decode('utf-8', errors='replace')
                        if len(content) > 500:
                            return content, "tex"
        except:
            continue
    return None, "failed"

def download_pdf(arxiv_id: str):
    sid = slugify(arxiv_id)
    for url in [f"https://arxiv.org/e-print/{sid}", f"https://arxiv.org/pdf/{sid}"]:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'wiki-rag/1.0'})
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
            if len(data) > 4 and data[:4] == b'%PDF':
                return data, "pdf"
        except:
            continue
    return None, "failed"

# ── Main Pipeline ─────────────────────────────────────────────────

def process_paper(arxiv_id, title="", authors="", abstract="", category=""):
    sid = slugify(arxiv_id)
    result = {"arxiv_id": arxiv_id, "source_type": None, "markdown": "", "json": {}, "success": False}
    
    tex, st = download_tex(arxiv_id)
    if tex:
        result["source_type"] = "tex"
        clean = strip_latex(tex)
        structure = extract_tex_structure(tex)
        structure["title"] = title or structure.get("title", "")
        structure["abstract"] = abstract or structure.get("abstract", "")
        md = ["---", f"source_url: https://arxiv.org/abs/{sid}",
              f"ingested: {date.today().isoformat()}", "---",
              "", f"# {title}", "", f"**Authors:** {authors}",
              f"**arXiv:** {sid}", "**Source:** tex", "", "## Abstract", "", abstract, "", clean]
        result["markdown"] = "\n".join(md)
        result["json"] = structure
        result["success"] = True
        print(f"    ✓ TeX ({len(clean)} chars, {len(structure['sections'])} sections)")
        return result
    
    pdf_bytes, st = download_pdf(arxiv_id)
    if pdf_bytes and is_digital_pdf(pdf_bytes):
        result["source_type"] = "pdf"
        structure = extract_pdf_structure(pdf_bytes)
        if structure:
            structure["title"] = title or structure.get("title", "")
            structure["abstract"] = abstract or structure.get("abstract", "")
            md = ["---", f"source_url: https://arxiv.org/abs/{sid}",
                  f"ingested: {date.today().isoformat()}", "---",
                  "", f"# {title}", "", f"**Authors:** {authors}",
                  f"**arXiv:** {sid}", "**Source:** pdf", ""]
            if structure.get("abstract"):
                md += ["## Abstract", "", structure["abstract"], ""]
            for page in structure.get("pages", []):
                md += [f"## Page {page['page_num']}", "", page["text"], ""]
            result["markdown"] = "\n".join(md)
            result["json"] = structure
            result["success"] = True
            pages = len(structure.get("pages", []))
            print(f"    ✓ PDF ({pages} pages)")
            return result
    
    print(f"    ✗ Skipped (no TeX, no digital PDF)")
    result["source_type"] = "skipped"
    return result

# ── Entry Point ───────────────────────────────────────────────────

def main():
    # Parse args
    max_papers = 5
    source_list = Path(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else None
    
    if "--max" in sys.argv:
        idx = sys.argv.index("--max")
        if idx + 1 < len(sys.argv):
            max_papers = int(sys.argv[idx + 1])
    
    if "--source" in sys.argv:
        idx = sys.argv.index("--source")
        if idx + 1 < len(sys.argv):
            source_list = Path(sys.argv[idx + 1])
    
    retry_skipped = "--retry-skipped" in sys.argv
    
    # Load manifest
    manifest, id_set, skipped_ids = load_manifest_index()
    
    # Handle --retry-skipped
    if retry_skipped:
        reset_count = 0
        for entry in manifest:
            if entry.get("skipped"):
                entry["skipped"] = False
                reset_count += 1
        if reset_count:
            print(f"Reset {reset_count} skipped papers")
            MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))
        sys.exit(0)
    
    # Load paper list
    if source_list and source_list.exists():
        papers_data = json.loads(source_list.read_text())
    else:
        print("No source list. Use: wiki-rag-collect --source papers.json")
        sys.exit(1)
    
    # Filter already collected
    to_collect = []
    for p in papers_data:
        sid = slugify(p.get("id", p.get("arxiv_id", "")))
        if sid and sid not in id_set:
            to_collect.append(p)
    
    print(f"Papers to collect: {len(to_collect)} (max: {max_papers})")
    
    collected = skipped = failed = 0
    
    for paper in to_collect[:max_papers]:
        arxiv_id = paper.get("id", paper.get("arxiv_id", ""))
        title = paper.get("title", "")
        authors = paper.get("authors", "")
        abstract = paper.get("abstract", paper.get("summary", ""))
        category = paper.get("category", "unknown")
        
        print(f"  [{category}] {arxiv_id}: {title[:60]}...")
        result = process_paper(arxiv_id, title, authors, abstract, category)
        
        if result["success"]:
            sid = slugify(arxiv_id)
            today = date.today().isoformat()
            md_path = RAW_DIR / f"{today}-{sid}.md"
            json_path = RAW_DIR / f"{today}-{sid}.json"
            md_path.parent.mkdir(parents=True, exist_ok=True)
            md_path.write_text(result["markdown"], encoding="utf-8")
            json_path.write_text(json.dumps(result["json"], indent=2), encoding="utf-8")
            manifest.append({
                "arxiv_id": arxiv_id, "title": title, "authors": authors,
                "abstract": abstract[:500], "category": category,
                "raw_path": str(md_path), "json_path": str(json_path),
                "source_type": result["source_type"], "collected_at": today,
                "ingested": False, "skipped": False
            })
            collected += 1
        elif result["source_type"] == "skipped":
            skipped += 1
            manifest.append({
                "arxiv_id": arxiv_id, "title": title, "authors": authors,
                "abstract": abstract[:500], "category": category,
                "source_type": "skipped", "collected_at": date.today().isoformat(),
                "ingested": False, "skipped": True
            })
        else:
            failed += 1
    
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nDone: {collected} collected, {skipped} skipped, {failed} failed")


class Collector:
    """Stateful collector with manifest tracking."""
    
    def __init__(self, wiki_path: Path = None):
        self.wiki_path = wiki_path or Path.home() / "wiki-rag"
        self.raw_dir = self.wiki_path / "raw" / "papers"
        self.manifest_path = self.wiki_path / "manifest.json"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.manifest = self._load_manifest()
    
    def _load_manifest(self) -> list:
        if self.manifest_path.exists():
            return json.loads(self.manifest_path.read_text())
        return []
    
    def _save_manifest(self):
        self.manifest_path.write_text(json.dumps(self.manifest, indent=2), encoding="utf-8")
    
    def _is_collected(self, arxiv_id: str) -> bool:
        sid = slugify(arxiv_id)
        return any(
            slugify(e.get("arxiv_id", "")) == sid 
            for e in self.manifest 
            if not e.get("skipped")
        )
    
    def collect(self, arxiv_id: str, title: str = "", authors: str = "", abstract: str = "", category: str = "") -> dict:
        """Collect and save a paper. Updates manifest."""
        if self._is_collected(arxiv_id):
            return {"arxiv_id": arxiv_id, "success": False, "error": "Already collected"}
        
        result = process_paper(arxiv_id, title, authors, abstract, category)
        
        if result["success"]:
            sid = slugify(arxiv_id)
            today = date.today().isoformat()
            md_path = self.raw_dir / f"{today}-{sid}.md"
            json_path = self.raw_dir / f"{today}-{sid}.json"
            md_path.write_text(result["markdown"], encoding="utf-8")
            json_path.write_text(json.dumps(result["json"], indent=2), encoding="utf-8")
            self.manifest.append({
                "arxiv_id": arxiv_id, "title": title, "authors": authors,
                "abstract": abstract[:500], "category": category,
                "raw_path": str(md_path), "json_path": str(json_path),
                "source_type": result["source_type"], "collected_at": today,
                "ingested": False, "skipped": False
            })
            self._save_manifest()
        elif result["source_type"] == "skipped":
            # Track skipped papers so they don't block the queue
            self.manifest.append({
                "arxiv_id": arxiv_id, "title": title, "authors": authors,
                "abstract": abstract[:500], "category": category,
                "source_type": "skipped", "collected_at": date.today().isoformat(),
                "ingested": False, "skipped": True
            })
            self._save_manifest()
        
        return result
    
    def get_skipped(self) -> list:
        """Get all skipped papers."""
        return [e for e in self.manifest if e.get("skipped")]
    
    def retry_skipped(self, max_papers: int = 5) -> list:
        """Retry skipped papers. Returns list of results."""
        skipped = self.get_skipped()
        results = []
        for entry in skipped[:max_papers]:
            # Reset skipped flag
            entry["skipped"] = False
            result = self.collect(
                entry["arxiv_id"], entry.get("title", ""),
                entry.get("authors", ""), entry.get("abstract", ""),
                entry.get("category", "unknown")
            )
            results.append(result)
        return results


if __name__ == "__main__":
    main()
