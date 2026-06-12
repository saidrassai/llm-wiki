#!/usr/bin/env python3
"""
wiki-rag-collect.py — Deterministic paper collector (zero LLM tokens)

Three-tier pipeline:
  1. TeX source (best) — structure-preserving LaTeX extraction
  2. Digital PDF (fast) — PyMuPDF in-memory text block extraction
  3. Complex PDF (rich) — Docling for tables, images, equations
  4. Scanned PDF — skipped (rare for ArXiv, <5%)

Usage:
  python3 wiki-rag-collect.py --max 5
  python3 wiki-rag-collect.py --max 10 --source papers.json
  python3 wiki-rag-collect.py --retry-skipped
"""

import json, re, sys, tarfile, urllib.request, urllib.error
from datetime import date
from pathlib import Path
from io import BytesIO
import tempfile
import subprocess
from wiki_rag.detect import analyze_tex, analyze_pdf, analyze_html, decide_strategy
from wiki_rag.tables import extract_tables_from_tex, extract_tables_from_pymupdf4llm, extract_tables_from_docling, extract_tables_from_html
from wiki_rag.structure import extract_structure_from_tex, extract_structure_from_html
from wiki_rag.merge import merge_structure_with_tables, build_hybrid_markdown, decide_final_source_type

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
    """Structure-preserving LaTeX to markdown conversion.

    Preserves:
    - Equations: $$...$$ → ```math ... ```, $...$ → $...$
    - Tables: tabular, tabular*, longtable, tabularx with booktabs
    - Citations and cross-references: \cite, \ref, \eqref, etc.
    - Section structure
    """
    # Remove comments
    text = re.sub(r'(?<!\\\\)%.*$', '', text, flags=re.MULTILINE)
    
    # Extract document body
    doc_start = re.search(r'\\begin\{document\}', text)
    doc_end = re.search(r'\\end\{document\}', text)
    if doc_start and doc_end:
        text = text[doc_start.end():doc_end.start()]
    elif doc_start:
        text = text[doc_start.end():]
    
    # Remove preamble
    text = re.sub(r'\\documentclass(\[[^\]]*\])?\{[^}]*\}', '', text)
    text = re.sub(r'\\usepackage(\[[^\]]*\])?\{[^}]*\}', '', text)
    text = re.sub(r'\\(newcommand|renewcommand|def)(\[[^\]]*\])?\{[^}]*\}(\[[^\]]*\])?(\{[^}]*\})?', '', text)
    
    # ===== EQUATIONS: Convert to Markdown math =====
    # Display equations: $$...$$ → ```math ... ```
    text = re.sub(r'\$\$(.*?)\$\$', r'\n```math\n\1\n```\n', text, flags=re.DOTALL)
    # Display equations: \[...\] → ```math ... ```
    text = re.sub(r'\\\[(.*?)\\\]', r'\n```math\n\1\n```\n', text, flags=re.DOTALL)
    # Display equations: \begin{equation}...\end{equation} → ```math ... ```
    text = re.sub(r'\\begin\{equation\*?\}(.*?)\\end\{equation\*?\}', r'\n```math\n\1\n```\n', text, flags=re.DOTALL)
    # Align/eqnarray environments
    text = re.sub(r'\\begin\{(align|eqnarray|gather|multline)\*?\}(.*?)\\end\{(align|eqnarray|gather|multline)\*?\}', 
                  r'\n```math\n\2\n```\n', text, flags=re.DOTALL)
    # Inline equations: $...$ → $...$ (preserve with spacing)
    text = re.sub(r'(?<!\$)\$(?!\$)([^$\n]+?)(?<!\$)\$(?!\$)', r' $\1$ ', text)
    
    # ===== TABLES: Convert LaTeX tables to Markdown =====
    # Handle tabular, tabular*, longtable, tabularx
    text = _convert_latex_tables(text)
    
    # ===== SECTIONS =====
    text = re.sub(r'\\section\*?\{([^}]*)\}', r'\n## \1\n', text)
    text = re.sub(r'\\subsection\*?\{([^}]*)\}', r'\n### \1\n', text)
    text = re.sub(r'\\subsubsection\*?\{([^}]*)\}', r'\n#### \1\n', text)
    
    # ===== FORMATTING =====
    for cmd in ['textbf', 'textit', 'emph', 'underline', 'textsc', 'texttt',
                'mathrm', 'mathit', 'mathbf', 'mathbb', 'mathcal', 'mathfrak', 'text']:
        text = re.sub(r'\\' + cmd + r'\{([^}]*)\}', r'\1', text)
    
    # ===== CITATIONS & CROSS-REFS: Preserve as markdown links =====
    # \cite{key} → [@key]
    text = re.sub(r'\\cite\w*(\[[^\]]*\])?\{([^}]*)\}', r'[@\2]', text)
    # \ref{label} → [#label]
    text = re.sub(r'\\ref\{([^}]*)\}', r'[#\1]', text)
    # \eqref{label} → [Eq. #label]
    text = re.sub(r'\\eqref\{([^}]*)\}', r'[Eq. #\1]', text)
    # \autoref{label} → [@label]
    text = re.sub(r'\\autoref\{([^}]*)\}', r'[@\1]', text)
    # \label{label} → <!-- label: label -->
    text = re.sub(r'\\label\{([^}]*)\}', r'<!-- label: \1 -->', text)
    
    # ===== LINKS =====
    text = re.sub(r'\\url\{([^}]*)\}', r'<\1>', text)
    text = re.sub(r'\\href\{([^}]*)\}\{([^}]*)\}', r'[\2](\1)', text)
    
    # ===== FOOTNOTES =====
    text = re.sub(r'\\footnote\{([^{}]*(\{[^}]*\}[^{}]*)*)\}', r'[^fn]', text)
    
    # ===== CAPTIONS =====
    text = re.sub(r'\\caption\*?\{([^}]*)\}', r'\n**Caption:** \1\n', text)
    
    # ===== REMOVE REMAINING ENVIRONMENTS =====
    for env in ['figure', 'table', 'table*', 'algorithm', 'algorithmic', 'tikzpicture',
                'itemize', 'enumerate', 'description', 'verbatim', 'lstlisting', 'minipage']:
        text = re.sub(r'\\begin\{' + env + r'\}.*?\\end\{' + env + r'\}', '', text, flags=re.DOTALL)
    
    # ===== CLEANUP =====
    # Remove remaining control sequences (but preserve our preserved $...$)
    text = re.sub(r'\\[a-zA-Z]+\*?(?:\[[^\]]*\])?(?:\{[^}]*\})?', '', text)
    text = re.sub(r'\\[a-zA-Z]+\b', '', text)
    
    # Remove braces but preserve math braces
    # Temporarily protect $...$ content
    math_parts = re.findall(r'(\$[^$\n]+\$)', text)
    for i, part in enumerate(math_parts):
        text = text.replace(part, f'__MATH_{i}__')
    text = re.sub(r'[{}]', '', text)
    for i, part in enumerate(math_parts):
        text = text.replace(f'__MATH_{i}__', part)
    
    # Cleanup whitespace
    text = re.sub(r' {3,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text.strip()


def _convert_latex_tables(text: str) -> str:
    """Convert LaTeX tables (tabular, tabular*, longtable, tabularx) to Markdown.
    Also handles table and table* wrapper environments."""
    # Pattern to match various table environments
    # FIRST: handle table/table* wrapper environments (extract tabular from inside)
    table_wrapper_pattern = (r'\\begin\{table\*?\}\[?[^\]]*\]?', r'\\end\{table\*?\}')
    text = _convert_single_table_env(text, *table_wrapper_pattern)
    
    # THEN: handle direct tabular environments
    table_patterns = [
        (r'\\begin\{tabular\*?\}', r'\\end\{tabular\*?\}'),
        (r'\\begin\{longtable\}', r'\\end\{longtable\}'),
        (r'\\begin\{tabularx\}', r'\\end\{tabularx\}'),
    ]
    
    for start_pat, end_pat in table_patterns:
        text = _convert_single_table_env(text, start_pat, end_pat)
    
    return text


def _convert_single_table_env(text: str, start_pat: str, end_pat: str) -> str:
    """Convert a single table environment to Markdown."""
    
    def replace_table(m):
        content = m.group(1)
        
        # For table/table* wrapper environments, extract tabular inside
        if 'table' in start_pat and 'tabular' not in start_pat:
            # Extract tabular environment from inside table wrapper
            tabular_match = re.search(r'\\begin\{tabular\*?\}(.*?)\\end\{tabular\*?\}', content, flags=re.DOTALL)
            if not tabular_match:
                return ''  # No tabular found inside table wrapper
            content = tabular_match.group(1)
        
        # Remove booktabs commands
        content = re.sub(r'\\toprule\s*', '', content)
        content = re.sub(r'\\midrule\s*', '', content)
        content = re.sub(r'\\bottomrule\s*', '', content)
        content = re.sub(r'\\cmidrule(\[[^\]]*\])?\{[^}]*\}', '', content)
        content = re.sub(r'\\addlinespace(\[\w+\])?', '', content)
        
        # Remove hline
        content = re.sub(r'\\hline', '', content)
        
        # Remove positioning commands from table wrapper
        content = re.sub(r'\\centering', '', content)
        content = re.sub(r'\[[htbp!]+\]', '', content)  # [h], [t], [b], [p], [!]
        
        # Remove hline
        content = re.sub(r'\\hline', '', content)
        
        # Split rows
        rows = re.sub(r'\\\\', '\n', content)
        lines = [l.strip() for l in rows.split('\n') if l.strip()]
        if not lines:
            return ''
        
        md = []
        for line in lines:
            # Handle multicolumn
            line = _convert_multicolumn(line)
            # Convert & to |
            line = re.sub(r'\s*&\s*', ' | ', line.strip('&').strip())
            md.append(f'| {line} |')
        
        if len(md) > 1:
            cols = md[0].count('|') - 1
            md.insert(1, '|' + ' --- |' * cols)
        
        return '\n' + '\n'.join(md) + '\n'
    
    # Replace table environment
    pattern = start_pat + r'(.*?)' + end_pat
    return re.sub(pattern, replace_table, text, flags=re.DOTALL)


def _convert_multicolumn(line: str) -> str:
    """Convert \multicolumn{N}{c}{text} to repeated cells."""
    # \multicolumn{N}{c}{text} → repeat text N times
    def replace_mc(m):
        n = int(m.group(1))
        text = m.group(2)
        return ' | '.join([text] * n)
    return re.sub(r'\\multicolumn\{(\d+)\}\{[^}]*\}\{([^}]*)\}', replace_mc, line)


def _clean_table_markdown(text: str) -> str:
    """Clean up pymupdf4llm table markdown: replace <br> with spaces, fix headers."""
    # Replace <br> with space in table rows (within |...|)
    lines = text.split('\n')
    cleaned = []
    for line in lines:
        if line.strip().startswith('|') and line.strip().endswith('|'):
            # This looks like a table row - replace <br> with space
            line = line.replace('<br>', ' ')
            line = line.replace('<br/>', ' ')
            line = line.replace('<br />', ' ')
        cleaned.append(line)
    return '\n'.join(cleaned)


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

# ── PyMuPDF + pymupdf4llm Pipeline (Primary) ────────────────────────

def is_digital_pdf(pdf_bytes: bytes) -> bool:
    if not pdf_bytes or len(pdf_bytes) < 100:
        return False
    try:
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if len(doc) == 0:
            doc.close()
            return False
        total_pages = len(doc)
        text_pages = 0
        for page in doc:
            if len(page.get_text().strip()) > 100:
                text_pages += 1
        doc.close()
        return text_pages / total_pages > 0.7
    except:
        return False


def extract_pdf_structure(pdf_bytes: bytes) -> dict:
    """
    Primary PDF extractor using pymupdf4llm (official, fast, clean markdown).
    Returns structured dict with markdown, tables, equations, metadata.
    """
    try:
        import pymupdf4llm
        import fitz
    except ImportError:
        # Fallback to basic PyMuPDF if pymupdf4llm not available
        return extract_pdf_structure_fallback(pdf_bytes)
    
    try:
        # Open PDF with fitz and pass Document object to pymupdf4llm
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        
        # Call 1: Get full markdown with tables, equations (no chunking)
        full_markdown = pymupdf4llm.to_markdown(
            doc,
            page_chunks=False,
            ignore_headers=True,
            ignore_footers=True,
            use_ocr=True,
            force_ocr=False,
            ignore_images=False,
            ignore_graphics=False,
            fontsize_limit=3,
            write_images=False,
            embed_images=False,
        )
        
        # Call 2: Get page chunks for TOC and metadata
        chunks = pymupdf4llm.to_markdown(
            doc,
            page_chunks=True,
            ignore_headers=True,
            ignore_footers=True,
            use_ocr=True,
            force_ocr=False,
            ignore_images=False,
            ignore_graphics=False,
            fontsize_limit=3,
        )
        
        doc.close()
        
        # full_markdown should be a string when page_chunks=False
        if not isinstance(full_markdown, str):
            # Unexpected format, fallback
            full_markdown = "\n\n".join(chunk.get("text", "") for chunk in chunks)
        
        # Count tables from markdown (pipe table lines)
        tables_count = full_markdown.count('|') // 2  # rough estimate
        
        # First chunk metadata
        first_chunk = chunks[0] if chunks else {}
        toc_items = first_chunk.get("toc_items", [])
        
        return {
            "markdown": full_markdown,
            "source_type": "pdf-pymupdf4llm",
            "pages": len(chunks),
            "tables_count": full_markdown.count('|') // 2,
            "images_count": 0,
            "toc_items": chunks[0].get("toc_items", []) if chunks else [],
            "chunks": chunks,
        }
    except Exception as e:
        # Fallback on any error
        if 'doc' in locals() and not doc.is_closed:
            doc.close()
        return extract_pdf_structure_fallback(pdf_bytes)

def extract_pdf_structure_fallback(pdf_bytes: bytes) -> dict:
    """Basic PyMuPDF text extraction (original logic)."""
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


def extract_with_docling(pdf_bytes: bytes, arxiv_id: str) -> dict:
    """
    Fallback for papers with tables/figures/equations that PyMuPDF can't handle well.
    Uses Docling CLI for rich markdown extraction with tables, images, equations.
    """
    try:
        import fitz
        import subprocess
        import tempfile
        from pathlib import Path
    except ImportError:
        return {"success": False, "error": "Missing dependencies"}
    
    # Quick heuristic: check if PyMuPDF text suggests complex content
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    first_pages_text = "\n".join(p.get_text() for p in doc[:min(3, len(doc))])
    doc.close()
    
    has_tables = any(kw in first_pages_text.lower() for kw in ["table 1", "table 2", "table 3", "figure 1", "figure 2", "figure 3"])
    has_pipe_tables = "|" in first_pages_text and first_pages_text.count("|") > 10
    has_equations = "$" in first_pages_text or "\\begin{equation}" in first_pages_text or "\\begin{align}" in first_pages_text
    
    # Only use Docling if complex content detected
    if not (has_tables or has_pipe_tables or has_equations):
        return {"success": False, "reason": "No complex content detected"}
    
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "input.pdf"
        pdf_path.write_bytes(pdf_bytes)
        output_dir = Path(tmpdir) / "output"
        
        # Run Docling CLI (no-ocr for digital PDFs, markdown output)
        try:
            result = subprocess.run([
                "docling", str(pdf_path),
                "--to", "md",
                "--output", str(output_dir),
                "--no-ocr"
            ], capture_output=True, timeout=300)
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Docling timeout"}
        except FileNotFoundError:
            return {"success": False, "error": "Docling not installed"}
        
        if result.returncode != 0:
            return {"success": False, "error": f"Docling failed: {result.stderr.decode()[:500]}"}
        
        # Find generated markdown file
        md_files = list(output_dir.rglob("*.md"))
        if not md_files:
            return {"success": False, "error": "No markdown output"}
        
        markdown = md_files[0].read_text(encoding="utf-8")
        
        # Verify it has more structure than plain text
        if len(markdown) < len(first_pages_text) * 0.5:
            return {"success": False, "reason": "Output too short"}
        
        return {
            "success": True,
            "markdown": markdown,
            "source_type": "pdf-docling",
            "has_tables": "|" in markdown and markdown.count("|") > 10,
            "has_images": "data:image" in markdown,
            "has_equations": "$$" in markdown or "\\begin" in markdown
        }


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


def download_html(arxiv_id: str):
    """Download ArXiv HTML version (available for papers since ~2023)."""
    sid = slugify(arxiv_id)
    for url in [f"https://arxiv.org/html/{sid}", f"https://arxiv.org/html/{sid}/index.html"]:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'wiki-rag/1.0'})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
            # Check if it's actually HTML (not a redirect to PDF)
            if data.startswith(b'<') or data.startswith(b'<!DOCTYPE'):
                return data.decode('utf-8', errors='replace'), "html"
        except:
            continue
    return None, "failed"


def has_complex_tex_tables(tex: str) -> bool:
    """Detect complex table features in TeX that our strip_latex can't handle well."""
    if not tex:
        return False
    
    # Look for complex table features in TeX
    complex_indicators = [
        r'\\multirow',           # Multi-row cells
        r'\\multicolumn',         # Multi-column cells (beyond simple)
        r'\\cmidrule',           # Partial horizontal rules
        r'\\begin\{tabular\*?\}[^}]*@\{.*@\}',  # Complex column specs with @{}
        r'\\begin\{tabular\*?\}[^}]*\|',  # Vertical lines in column spec
        r'\\begin\{longtable\}',  # Long tables
        r'\\begin\{tabularx\}',   # Tabularx environment
        r'\\hline.*\\hline',      # Multiple consecutive hlines
        r'\\cline',               # Partial horizontal rules
    ]
    
    # Count occurrences
    score = 0
    for pattern in complex_indicators:
        matches = len(re.findall(pattern, tex, flags=re.DOTALL))
        score += matches
    
    # Consider complex if 3+ indicators found
    return score >= 3


# ── Main Pipeline ─────────────────────────────────────────────────

def process_paper(arxiv_id, title="", authors="", abstract="", category=""):
    sid = slugify(arxiv_id)
    result = {"arxiv_id": arxiv_id, "source_type": None, "markdown": "", "json": {}, "success": False}
    
    # 1. Download ALL available sources
    tex, _ = download_tex(arxiv_id)
    pdf_bytes, _ = download_pdf(arxiv_id)
    html, _ = download_html(arxiv_id)
    
    # 2. Analyze each source
    tex_profile = analyze_tex(tex) if tex else None
    pdf_profile = analyze_pdf(pdf_bytes) if pdf_bytes else None
    html_profile = analyze_html(html) if html else None
    
    # 3. Decide strategy
    strategy = decide_strategy(tex_profile, pdf_profile, html_profile)
    print(f"    Strategy: {strategy} (TeX: {tex_profile.recommended_extractor if tex_profile else 'none'}, PDF: {pdf_profile.recommended_extractor if pdf_profile else 'none'}, HTML: {html_profile.recommended_extractor if html_profile else 'none'})")
    
    # 4. Execute strategy
    fallback_used = False
    
    if strategy == "tex_only":
        # TeX handles everything
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
        result["source_type"] = "tex"
        result["success"] = True
        print(f"    ✓ TeX-only ({len(clean)} chars, {len(structure['sections'])} sections)")
        return result
    
    elif strategy == "tex+pymupdf4llm":
        # HYBRID: TeX for structure, pymupdf4llm for tables
        if not tex or not pdf_bytes:
            print(f"    ⚠ Missing source for hybrid, falling back")
            # Fall through
        else:
            struct = extract_structure_from_tex(tex)
            tables = extract_tables_from_pymupdf4llm(pdf_bytes)
            
            # Merge tables into structure
            merged_struct = merge_structure_with_tables(struct, tables)
            
            # Build markdown
            source_type = decide_final_source_type(tex_profile, pdf_profile, strategy, fallback_used)
            markdown = build_hybrid_markdown(
                merged_struct, source_type, arxiv_id, title, authors, abstract, tables
            )
            
            result["markdown"] = markdown
            result["json"] = {
                "title": title,
                "abstract": abstract,
                "sections": [{"level": s.level, "title": s.title} for s in merged_struct.sections],
                "equations": len(merged_struct.equations),
                "citations": len(merged_struct.citations),
                "figures": len(merged_struct.figures),
                "tables_count": len(tables),
            }
            result["source_type"] = source_type
            result["success"] = True
            print(f"    ✓ TeX+pymupdf4llm hybrid ({len(tables)} tables merged)")
            return result
    
    elif strategy == "tex+pymupdf4llm+docling":
        # HYBRID with Docling fallback for complex tables
        if not tex or not pdf_bytes:
            print(f"    ⚠ Missing source for hybrid, falling back")
            # Fall through
        else:
            struct = extract_structure_from_tex(tex)
            tables = extract_tables_from_pymupdf4llm(pdf_bytes)
            
            # Check if any tables need Docling
            docling_tables = []
            remaining_tables = list(tables)
            
            for table in tables:
                if table.row_count == 1 and table.col_count > 15:  # cross-page
                    docling_result = extract_tables_from_docling(pdf_bytes)
                    if docling_result:
                        docling_tables.extend(docling_result)
                        fallback_used = True
            
            all_tables = tables + docling_tables
            merged_struct = merge_structure_with_tables(struct, all_tables)
            
            source_type = decide_final_source_type(tex_profile, pdf_profile, strategy, fallback_used)
            markdown = build_hybrid_markdown(
                merged_struct, source_type, arxiv_id, title, authors, abstract, all_tables
            )
            
            result["markdown"] = markdown
            result["json"] = {
                "title": title,
                "abstract": abstract,
                "sections": [{"level": s.level, "title": s.title} for s in merged_struct.sections],
                "equations": len(merged_struct.equations),
                "citations": len(merged_struct.citations),
                "figures": len(merged_struct.figures),
                "tables_count": len(all_tables),
            }
            result["source_type"] = source_type
            result["success"] = True
            print(f"    ✓ TeX+pymupdf4llm+Docling hybrid ({len(all_tables)} tables, fallback={fallback_used})")
            return result
    
    elif strategy == "pymupdf4llm":
        # PDF only, use pymupdf4llm
        if not pdf_bytes:
            print(f"    ⚠ No PDF for pymupdf4llm, falling back")
        else:
            pdf_result = extract_pdf_structure(pdf_bytes)
            if pdf_result and pdf_result.get("markdown"):
                md_text = _clean_table_markdown(pdf_result["markdown"])
                
                md = ["---", f"source_url: https://arxiv.org/abs/{sid}",
                      f"ingested: {date.today().isoformat()}", "---",
                      "", f"# {title}", "", f"**Authors:** {authors}",
                      f"**arXiv:** {sid}", "**Source:** pdf-pymupdf4llm", ""]
                if abstract:
                    md += ["## Abstract", "", abstract, ""]
                md += [md_text]
                
                result["markdown"] = "\n".join(md)
                result["json"] = {
                    "title": title,
                    "abstract": abstract,
                    "sections": pdf_result.get("toc_items", []),
                    "tables_count": pdf_result.get("tables_count", 0),
                    "images_count": pdf_result.get("images_count", 0),
                }
                result["source_type"] = "pdf-pymupdf4llm"
                result["success"] = True
                print(f"    ✓ PDF-pymupdf4llm ({pdf_result.get('pages', 0)} pages)")
                return result
    
    elif strategy == "docling":
        # PDF only, use Docling
        if not pdf_bytes:
            print(f"    ⚠ No PDF for Docling, falling back")
        else:
            docling_result = extract_with_docling(pdf_bytes, arxiv_id)
            if docling_result.get("success"):
                md = ["---", f"source_url: https://arxiv.org/abs/{sid}",
                      f"ingested: {date.today().isoformat()}", "---",
                      "", f"# {title}", "", f"**Authors:** {authors}",
                      f"**arXiv:** {sid}", "**Source:** pdf-docling", ""]
                if abstract:
                    md += ["## Abstract", "", abstract, ""]
                md += [docling_result["markdown"]]
                
                result["markdown"] = "\n".join(md)
                result["source_type"] = "pdf-docling"
                result["success"] = True
                print(f"    ✓ PDF-docling")
                return result
    
    elif strategy == "html":
        # HTML fallback
        if not html:
            print(f"    ⚠ No HTML, falling back")
        else:
            struct = extract_structure_from_html(html)
            tables = extract_tables_from_html(html)
            merged_struct = merge_structure_with_tables(struct, tables)
            
            md = ["---", f"source_url: https://arxiv.org/abs/{sid}",
                  f"ingested: {date.today().isoformat()}", "---",
                  "", f"# {title}", "", f"**Authors:** {authors}",
                  f"**arXiv:** {sid}", "**Source:** html", ""]
            if abstract:
                md += ["## Abstract", "", abstract, ""]
            md += [merged_struct.clean_text]
            
            result["markdown"] = "\n".join(md)
            result["json"] = {
                "title": title,
                "abstract": abstract,
                "sections": [{"level": s.level, "title": s.title} for s in merged_struct.sections],
                "tables_count": len(tables),
            }
            result["source_type"] = "html"
            result["success"] = True
            print(f"    ✓ HTML ({len(tables)} tables)")
            return result
    
    # Fallback to basic PDF text extraction
    if pdf_bytes and is_digital_pdf(pdf_bytes):
        result["source_type"] = "pdf"
        structure = extract_pdf_structure_fallback(pdf_bytes)
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
            print(f"    ✓ PDF fallback ({pages} pages)")
            return result
    
    print(f"    ✗ Skipped (no viable source)")
    result["source_type"] = "skipped"
    return result
    result["source_type"] = "skipped"
    return result

# ── Entry Point ───────────────────────────────────────────────────

def main():
    # Parse args
    max_papers = 5
    source_list = None
    
    if "--max" in sys.argv:
        idx = sys.argv.index("--max")
        if idx + 1 < len(sys.argv):
            max_papers = int(sys.argv[idx + 1])
    
    if "--source" in sys.argv:
        idx = sys.argv.index("--source")
        if idx + 1 < len(sys.argv):
            source_list = Path(sys.argv[idx + 1])
    
    retry_skipped = "--retry-skipped" in sys.argv
    
    # Default source list
    if source_list is None:
        source_list = WIKI_PATH / "categorized_papers_2024_2026.json"
    
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
    if not source_list.exists():
        print(f"Source list not found: {source_list}")
        sys.exit(1)
    
    papers_data = json.loads(source_list.read_text())
    
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
