#!/usr/bin/env python3
"""
wiki-rag-collect.py — Deterministic paper collector (zero LLM tokens)

Three-tier pipeline:
  1. TeX source (best) — structure-preserving LaTeX extraction
  2. Digital PDF (fast) — PyMuPDF in-memory text block extraction
  3. Scanned PDF — skipped (rare for ArXiv, <5%)

Run: python3 ~/.hermes/scripts/wiki-rag-collect.py [--max 5]
"""

import json, re, sys, tarfile, urllib.request, urllib.error
from datetime import date
from pathlib import Path
from io import BytesIO

# ── Config ────────────────────────────────────────────────────────
WIKI_PATH = Path("/home/ubuntu/wiki-rag")
RAW_DIR = WIKI_PATH / "raw" / "papers"
MANIFEST_FILE = WIKI_PATH / "manifest.json"
PAPERS_JSON = WIKI_PATH / "categorized_papers_2024_2026.json"

# ── Helpers ───────────────────────────────────────────────────────

def slugify(arxiv_id: str) -> str:
    return re.sub(r'v\d+$', '', arxiv_id.strip())

def load_manifest_index() -> tuple:
    """Load manifest and return (manifest_list, id_set, raw_stem_set, skipped_ids) for O(1) lookups."""
    if not MANIFEST_FILE.exists():
        return [], set(), set(), set()
    manifest = json.loads(MANIFEST_FILE.read_text())
    id_set = set()
    raw_stem_set = set()
    skipped_ids = set()
    for entry in manifest:
        sid = slugify(entry.get("arxiv_id", ""))
        id_set.add(sid)
        id_set.add(entry.get("arxiv_id", ""))
        raw_fn = entry.get("raw_filename", "")
        if raw_fn:
            raw_stem_set.add(Path(raw_fn).stem)
        if entry.get("skipped") and not entry.get("ingested"):
            skipped_ids.add(sid)
    return manifest, id_set, raw_stem_set, skipped_ids

def already_collected(sid: str, raw_stem: str, id_set: set, raw_stem_set: set, skipped_ids: set = None) -> bool:
    """O(1) check if paper already collected or skipped."""
    if skipped_ids and sid in skipped_ids:
        return True
    return sid in id_set or raw_stem in raw_stem_set

# ── TeX Pipeline ──────────────────────────────────────────────────

def strip_latex(text: str) -> str:
    """Structure-preserving LaTeX to markdown conversion."""
    # Remove comments
    text = re.sub(r'(?<!\\)%.*$', '', text, flags=re.MULTILINE)
    
    # Keep only \begin{document}...\end{document}
    doc_start = re.search(r'\\begin\{document\}', text)
    doc_end = re.search(r'\\end\{document\}', text)
    if doc_start and doc_end:
        text = text[doc_start.end():doc_end.start()]
    elif doc_start:
        text = text[doc_start.end():]
    
    # Preamble
    text = re.sub(r'\\documentclass(\[[^\]]*\])?\{[^}]*\}', '', text)
    text = re.sub(r'\\usepackage(\[[^\]]*\])?\{[^}]*\}', '', text)
    text = re.sub(r'\\(newcommand|renewcommand|def)(\[[^\]]*\])?\{[^}]*\}(\[[^\]]*\])?(\{[^}]*\})?', '', text)
    
    # Tables: convert tabular → markdown
    text = convert_tabular_to_markdown(text)
    
    # Remove environments (preserve equations)
    for env in ['figure', 'table', 'table*', 'algorithm', 'algorithmic', 'tikzpicture',
                'itemize', 'enumerate', 'description', 'verbatim', 'lstlisting',
                'minipage', 'center', 'flushleft', 'flushright']:
        text = re.sub(r'\\begin\{' + env + r'\}.*?\\end\{' + env + r'\}', '', text, flags=re.DOTALL)
    
    # Sections → markdown headers
    text = re.sub(r'\\section\*?\{([^}]*)\}', r'\n## \1\n', text)
    text = re.sub(r'\\subsection\*?\{([^}]*)\}', r'\n### \1\n', text)
    text = re.sub(r'\\subsubsection\*?\{([^}]*)\}', r'\n#### \1\n', text)
    
    # Formatting: keep content
    for cmd in ['textbf', 'textit', 'emph', 'underline', 'textsc', 'texttt',
                'mathrm', 'mathit', 'mathbf', 'mathbb', 'mathcal', 'mathfrak',
                'text', 'textsf', 'textsl', 'textup', 'textrm']:
        text = re.sub(r'\\' + cmd + r'\{([^}]*)\}', r'\1', text)
    
    # Citations/refs
    text = re.sub(r'\\(label|ref|eqref|autoref|pageref|cite\w*|nocite|parencite|textcite)\*?(\[[^\]]*\])?\{[^}]*\}', '', text)
    
    # URLs
    text = re.sub(r'\\url\{([^}]*)\}', r'\1', text)
    text = re.sub(r'\\href\{[^}]*\}\{([^}]*)\}', r'\1', text)
    
    # Footnotes, captions
    text = re.sub(r'\\footnote\{[^{}]*(\{[^}]*\}[^{}]*)*\}', '', text)
    text = re.sub(r'\\caption\*?\{([^}]*)\}', r'\n**Caption:** \1\n', text)
    
    # Layout
    text = re.sub(r'\\(vspace|hspace|vfill|hfill|newline|linebreak|pagebreak|noindent|indent|centering|raggedright|raggedleft|hline|toprule|midrule|bottomrule|cline)\*?\{[^}]*\}', '', text)
    
    # Inline math: preserve with $...$
    # (already in good shape from source)
    
    # Itemize
    text = re.sub(r'\\item\b', '- ', text)
    
    # Special chars
    text = re.sub(r'\~', ' ', text)
    text = re.sub(r'\\&', '&', text)
    text = re.sub(r'\\%', '%', text)
    text = re.sub(r'\\#', '#', text)
    text = re.sub(r'\\_', '_', text)
    
    # Remaining commands
    text = re.sub(r'\\[a-zA-Z]+\*?(?:\[[^\]]*\])?(?:\{[^}]*\})?', '', text)
    text = re.sub(r'\\[a-zA-Z]+\*?(?:\[[^\]]*\])?', '', text)
    text = re.sub(r'\\[a-zA-Z]+\b', '', text)
    
    # Stray brackets
    text = re.sub(r'\[figure\]|\[table\]|\[h\]|\[t\]|\[b\]|\[p\]|\[H\]|\[!\w+\]', '', text)
    text = re.sub(r'[{}]', '', text)
    
    # Whitespace
    text = re.sub(r' {3,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'^\s+', '', text, flags=re.MULTILINE)
    
    return text.strip()

def convert_tabular_to_markdown(text: str) -> str:
    """Convert LaTeX tabular → markdown table."""
    def replace_tabular(m):
        content = m.group(1)
        rows = re.sub(r'\\\\', '\n', content)
        rows = re.sub(r'\\hline', '', rows)
        lines = [l.strip() for l in rows.split('\n') if l.strip()]
        if not lines:
            return ''
        md_lines = []
        for line in lines:
            line = line.strip('&').strip()
            line = re.sub(r'\s*&\s*', ' | ', line)
            md_lines.append(f'| {line} |')
        if len(md_lines) > 1:
            cols = md_lines[0].count('|') - 1
            md_lines.insert(1, '|' + ' --- |' * cols)
        return '\n' + '\n'.join(md_lines) + '\n'
    
    return re.sub(r'\\begin\{tabular\}\{[^}]*\}(.*?)\\end\{tabular\}', replace_tabular, text, flags=re.DOTALL)

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

# ── PyMuPDF Pipeline (in-memory, no /tmp) ──────────────────────────

def is_digital_pdf(pdf_bytes: bytes) -> bool:
    """Check if PDF has extractable text. In-memory, no disk I/O."""
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
    except Exception:
        return False

def extract_pdf_structure(pdf_bytes: bytes) -> dict:
    """Extract structured text from digital PDF. In-memory, no disk I/O."""
    try:
        import fitz
    except ImportError:
        return None
    
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    structure = {"title": "", "abstract": "", "sections": [], "pages": []}
    
    for i, page in enumerate(doc):
        text = page.get_text()
        blocks = page.get_text("blocks")
        
        structure["pages"].append({
            "page_num": i + 1,
            "text": text,
            "block_count": len(blocks)
        })
        
        # Title: first page, top blocks
        if i == 0:
            top = sorted(blocks, key=lambda b: b[1])[:3] if blocks else []
            for b in top:
                if len(b) > 4 and len(b[4].strip()) > 10:
                    structure["title"] = b[4].strip()
                    break
            
            # Abstract: find "Abstract" heading, extract until next section
            if 'abstract' in text.lower():
                abs_idx = text.lower().index('abstract')
                abs_text = text[abs_idx:abs_idx + 1500]
                # End at next section header or double newline after 200+ chars
                end = re.search(r'\n\s*\n\s*\n|\n## |\n\d+\.\s+[A-Z]', abs_text[200:])
                if end:
                    structure["abstract"] = abs_text[:end.start() + 200].strip()
                else:
                    structure["abstract"] = abs_text.strip()
        
        # Section headers: numbered short lines
        for b in blocks:
            if len(b) > 4:
                bt = b[4].strip()
                if re.match(r'^\d+\.?\s+[A-Z]', bt) and len(bt) < 80 and not bt.endswith('.'):
                    structure["sections"].append({"title": bt, "page": i + 1})
    
    doc.close()
    return structure

# ── Download ───────────────────────────────────────────────────────

def download_tex(arxiv_id: str):
    """Download TeX. Returns (content, 'tex') or (None, 'failed')."""
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
        except Exception as e:
            print(f"    DEBUG tex: {e}")
    return None, "failed"

def download_pdf(arxiv_id: str):
    """Download PDF. Returns (bytes, 'pdf') or (None, 'failed')."""
    sid = slugify(arxiv_id)
    for url in [f"https://arxiv.org/e-print/{sid}", f"https://arxiv.org/pdf/{sid}"]:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'wiki-rag/1.0'})
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
            if len(data) > 4 and data[:4] == b'%PDF':
                return data, "pdf"
        except Exception as e:
            print(f"    DEBUG pdf: {e}")
    return None, "failed"

# ── Main Pipeline ─────────────────────────────────────────────────

def process_paper(arxiv_id, title, authors, abstract, category):
    """Three-tier pipeline: TeX → digital PDF → skip."""
    sid = slugify(arxiv_id)
    result = {"arxiv_id": arxiv_id, "source_type": None, "markdown": "", "json": {}, "success": False}
    
    # Tier 1: TeX
    tex, st = download_tex(arxiv_id)
    if tex:
        result["source_type"] = "tex"
        clean = strip_latex(tex)
        structure = extract_tex_structure(tex)
        structure["title"] = title or structure.get("title", "")
        structure["abstract"] = abstract or structure.get("abstract", "")
        
        md = [
            "---", f"source_url: https://arxiv.org/abs/{sid}",
            f"ingested: {date.today().isoformat()}", "sha256: pending", "---",
            "", f"# {title}", "", f"**Authors:** {authors}",
            f"**arXiv:** {sid}", "**Source:** tex", "", "## Abstract", "", abstract, "",
            clean
        ]
        result["markdown"] = "\n".join(md)
        result["json"] = structure
        result["success"] = True
        print(f"    ✓ TeX ({len(clean)} chars, {len(structure['sections'])} sections)")
        return result
    
    # Tier 2: Digital PDF (in-memory)
    pdf_bytes, st = download_pdf(arxiv_id)
    if pdf_bytes and is_digital_pdf(pdf_bytes):
        result["source_type"] = "pdf"
        structure = extract_pdf_structure(pdf_bytes)
        if structure:
            structure["title"] = title or structure.get("title", "")
            structure["abstract"] = abstract or structure.get("abstract", "")
            
            md = [
                "---", f"source_url: https://arxiv.org/abs/{sid}",
                f"ingested: {date.today().isoformat()}", "sha256: pending", "---",
                "", f"# {title}", "", f"**Authors:** {authors}",
                f"**arXiv:** {sid}", "**Source:** pdf", ""
            ]
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
    
    # Tier 3: Skip (scanned or unavailable)
    print(f"    ✗ Skipped (no TeX, no digital PDF)")
    result["source_type"] = "skipped"
    return result

# ── Entry Point ───────────────────────────────────────────────────

def main():
    max_papers = 5
    if "--max" in sys.argv:
        idx = sys.argv.index("--max")
        if idx + 1 < len(sys.argv):
            max_papers = int(sys.argv[idx + 1])
    
    if not PAPERS_JSON.exists():
        print(f"ERROR: {PAPERS_JSON} not found"); sys.exit(1)
    
    # Load manifest index once — O(1) lookups
    manifest, id_set, raw_stem_set, skipped_ids = load_manifest_index()
    
    # Flatten paper list
    papers_data = json.loads(PAPERS_JSON.read_text())
    all_papers = []
    for cat, papers in papers_data.items():
        for p in papers:
            p["_category"] = cat
            all_papers.append(p)
    
    # Filter using O(1) set lookups
    to_collect = []
    for p in all_papers:
        sid = slugify(p["id"])
        raw_stem = f"{date.today().isoformat()}-{sid}"
        if not already_collected(sid, raw_stem, id_set, raw_stem_set, skipped_ids):
            to_collect.append(p)
    
    print(f"Papers to collect: {len(to_collect)} (max: {max_papers})")
    
    collected = skipped = failed = 0
    
    # Check for --retry-skipped flag
    retry_skipped = "--retry-skipped" in sys.argv
    if retry_skipped:
        # Reset skipped papers to uningested
        reset_count = 0
        for entry in manifest:
            if entry.get("skipped") and not entry.get("ingested"):
                entry["skipped"] = False
                entry["source_type"] = None
                reset_count += 1
        if reset_count:
            print(f"Reset {reset_count} skipped papers for retry")
            MANIFEST_FILE.write_text(json.dumps(manifest, indent=2))
            print("Run again without --retry-skipped to collect the reset papers")
        sys.exit(0)
    
    for paper in to_collect[:max_papers]:
        arxiv_id = paper["id"]
        print(f"  [{paper['_category']}] {arxiv_id}: {paper.get('title','')[:60]}...")
        
        result = process_paper(
            arxiv_id, paper.get("title",""), paper.get("authors",""),
            paper.get("summary",""), paper["_category"]
        )
        
        if result["success"]:
            sid = slugify(arxiv_id)
            today = date.today().isoformat()
            
            # Save markdown
            md_path = RAW_DIR / f"{today}-{sid}.md"
            md_path.write_text(result["markdown"], encoding="utf-8")
            
            # Save JSON
            json_path = RAW_DIR / f"{today}-{sid}.json"
            json_path.write_text(json.dumps(result["json"], indent=2), encoding="utf-8")
            
            # Update manifest
            manifest.append({
                "arxiv_id": arxiv_id, "title": paper.get("title",""),
                "authors": paper.get("authors",""), "abstract": paper.get("summary","")[:500],
                "category": paper["_category"], "raw_path": str(md_path),
                "json_path": str(json_path), "source_type": result["source_type"],
                "collected_at": today, "ingested": False, "skipped": False
            })
            collected += 1
        elif result["source_type"] == "skipped":
            skipped += 1
            # Add to manifest as skipped so it blocks the queue
            manifest.append({
                "arxiv_id": arxiv_id, "title": paper.get("title",""),
                "authors": paper.get("authors",""), "abstract": paper.get("summary","")[:500],
                "category": paper["_category"], "source_type": "skipped",
                "collected_at": date.today().isoformat(), "ingested": False, "skipped": True
            })
        else:
            failed += 1
    
    MANIFEST_FILE.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nDone: {collected} collected, {skipped} skipped, {failed} failed")
    print(f"Manifest: {len(manifest)} total entries")

if __name__ == "__main__":
    main()
