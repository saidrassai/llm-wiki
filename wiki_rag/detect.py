#!/usr/bin/env python3
"""
Content detection and complexity analysis for hybrid extraction.
"""

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class ContentProfile:
    """Profile of a paper's content characteristics."""
    has_tables: bool = False
    table_complexity: str = "none"  # "none", "simple", "complex", "cross_page"
    has_equations: bool = False
    has_figures: bool = False
    has_complex_layout: bool = False
    recommended_extractor: str = "basic"  # "tex", "tex+pymupdf4llm", "tex+pymupdf4llm+docling", "pymupdf4llm", "docling", "html", "basic"
    num_tables: int = 0
    num_equations: int = 0
    num_figures: int = 0
    details: dict = None


def analyze_tex(tex: str) -> ContentProfile:
    """Analyze TeX source for content complexity."""
    if not tex:
        return ContentProfile()
    
    profile = ContentProfile(details={"source": "tex"})
    
    # Detect tables
    table_envs = [
        r'\\begin\{tabular\*?\}',
        r'\\begin\{longtable\}',
        r'\\begin\{tabularx\}',
        r'\\begin\{table\*?\}',
    ]
    table_matches = []
    for pattern in table_envs:
        table_matches.extend(re.findall(pattern, tex))
    
    profile.num_tables = len(table_matches)
    profile.has_tables = profile.num_tables > 0
    
    if profile.has_tables:
        # Check for complex table features
        complex_indicators = [
            (r'\\multirow', "multirow"),
            (r'\\multicolumn', "multicolumn"),
            (r'\\cmidrule', "cmidrule"),
            (r'\\begin\{tabular\*?\}[^}]*@\{.*@\}', "complex_colspec"),
            (r'\\begin\{tabular\*?\}[^}]*\|', "vertical_lines"),
            (r'\\begin\{longtable\}', "longtable"),
            (r'\\begin\{tabularx\}', "tabularx"),
            (r'\\hline.*\\hline', "multi_hline"),
            (r'\\cline', "cline"),
        ]
        
        complexity_score = 0
        found_features = []
        for pattern, name in complex_indicators:
            matches = len(re.findall(pattern, tex, flags=re.DOTALL))
            if matches:
                complexity_score += matches
                found_features.append(f"{name}:{matches}")
        
        profile.details["table_features"] = found_features
        
        if complexity_score >= 3:
            profile.table_complexity = "complex"
        elif profile.num_tables > 0:
            profile.table_complexity = "simple"
        
        # Check for longtable (cross-page indicator)
        if re.search(r'\\begin\{longtable\}', tex):
            profile.table_complexity = "cross_page"
    
    # Detect equations
    eq_patterns = [
        r'\$\$.*?\$\$',           # $$...$$
        r'\\\\[.*?\\\\]',           # \[...\]
        r'\\begin\{equation\*?\}', # \begin{equation}
        r'\\begin\{align\*?\}',   # \begin{align}
        r'\\begin\{gather\*?\}',  # \begin{gather}
        r'\\begin\{multline\*?\}', # \begin{multline}
    ]
    eq_count = 0
    for pattern in eq_patterns:
        eq_count += len(re.findall(pattern, tex, flags=re.DOTALL))
    
    profile.num_equations = eq_count
    profile.has_equations = eq_count > 0
    
    # Detect figures
    fig_matches = len(re.findall(r'\\begin\{figure\*?\}', tex))
    profile.num_figures = fig_matches
    profile.has_figures = fig_matches > 0
    
    # Detect complex layout
    layout_indicators = [
        r'\\begin\{minipage\}',
        r'\\begin\{wrapfigure\}',
        r'\\begin\{sideways',
        r'\\rotatebox',
        r'\\includegraphics',
    ]
    layout_score = sum(len(re.findall(p, tex)) for p in layout_indicators)
    profile.has_complex_layout = layout_score > 2
    profile.details["layout_score"] = layout_score
    
    # Determine recommended extractor
    if not profile.has_tables and not profile.has_complex_layout:
        profile.recommended_extractor = "tex"
    elif profile.table_complexity == "cross_page" or profile.has_complex_layout:
        profile.recommended_extractor = "tex+pymupdf4llm+docling"
    elif profile.has_tables:
        profile.recommended_extractor = "tex+pymupdf4llm"
    
    return profile


def analyze_pdf(pdf_bytes: bytes) -> ContentProfile:
    """Analyze PDF for content complexity using pymupdf4llm."""
    if not pdf_bytes or len(pdf_bytes) < 100:
        return ContentProfile()
    
    try:
        import pymupdf4llm
        import fitz
    except ImportError:
        return ContentProfile(details={"error": "pymupdf4llm not available"})
    
    profile = ContentProfile(details={"source": "pdf"})
    
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        
        # Quick text analysis from first few pages
        sample_pages = min(5, len(doc))
        sample_text = ""
        for i in range(sample_pages):
            sample_text += doc[i].get_text()
        
        # Detect tables (pipe tables in text)
        pipe_count = sample_text.count('|')
        if pipe_count > 10:
            profile.has_tables = True
            profile.num_tables = pipe_count // 4  # rough estimate
            
            # Check for cross-page tables
            try:
                chunks = pymupdf4llm.to_markdown(
                    doc, page_chunks=True, ignore_headers=True, ignore_footers=True
                )
                for chunk in chunks:
                    for table in chunk.get("tables", []):
                        if table.get("row_count", 0) == 1 and table.get("col_count", 0) > 15:
                            profile.table_complexity = "cross_page"
                            break
                    if profile.table_complexity == "cross_page":
                        break
            except:
                pass
            
            if profile.table_complexity != "cross_page":
                profile.table_complexity = "simple"
        
        # Detect equations
        eq_indicators = sample_text.count('$') + sample_text.count('\\begin{equation}') + sample_text.count('\\begin{align}')
        if eq_indicators > 0:
            profile.has_equations = True
            profile.num_equations = eq_indicators // 2
        
        # Detect figures
        fig_indicators = sample_text.lower().count('figure') + sample_text.lower().count('fig.')
        if fig_indicators > 0:
            profile.has_figures = True
            profile.num_figures = fig_indicators
        
        # Check total pages for complexity
        if len(doc) > 20:
            profile.has_complex_layout = True
        
        doc.close()
        
    except Exception as e:
        profile.details["error"] = str(e)
    
    # Determine recommended extractor
    if profile.table_complexity == "cross_page":
        profile.recommended_extractor = "docling"
    elif profile.has_tables:
        profile.recommended_extractor = "pymupdf4llm"
    elif profile.has_equations or profile.has_figures:
        profile.recommended_extractor = "pymupdf4llm"
    else:
        profile.recommended_extractor = "basic"
    
    return profile


def analyze_html(html: str) -> ContentProfile:
    """Analyze ArXiv HTML for content complexity."""
    if not html:
        return ContentProfile()
    
    profile = ContentProfile(details={"source": "html"})
    
    # Detect tables
    table_matches = html.count('<table') + html.count('<tbody') + html.count('<thead')
    profile.num_tables = table_matches
    profile.has_tables = table_matches > 0
    
    if profile.has_tables:
        # Check for complex tables
        if re.search(r'rowspan|colspan', html, re.IGNORECASE):
            profile.table_complexity = "complex"
        elif re.search(r'thead.*tbody', html, flags=re.DOTALL | re.IGNORECASE):
            profile.table_complexity = "cross_page"
        else:
            profile.table_complexity = "simple"
    
    # Detect equations (MathML or LaTeX in HTML)
    eq_patterns = [
        r'<math',
        r'class="math"',
        r'\\$.*?\\$',
        r'\\begin\{',
    ]
    eq_count = sum(len(re.findall(p, html, flags=re.DOTALL)) for p in eq_patterns)
    profile.num_equations = eq_count
    profile.has_equations = eq_count > 0
    
    # Detect figures
    fig_count = html.count('<figure') + html.count('<img')
    profile.num_figures = fig_count
    profile.has_figures = fig_count > 0
    
    # Determine recommended extractor
    if profile.table_complexity == "cross_page":
        profile.recommended_extractor = "docling"
    elif profile.has_tables:
        profile.recommended_extractor = "html"
    elif profile.has_equations:
        profile.recommended_extractor = "html"
    else:
        profile.recommended_extractor = "html"
    
    return profile


def decide_strategy(tex_profile: Optional[ContentProfile], 
                    pdf_profile: Optional[ContentProfile],
                    html_profile: Optional[ContentProfile]) -> str:
    """
    Decide the best extraction strategy based on available sources and their profiles.
    
    Priority: TeX + pymupdf4llm hybrid > pymupdf4llm > Docling > HTML > TeX-only > basic
    """
    has_tex = tex_profile and tex_profile.has_tables is not None
    has_pdf = pdf_profile and pdf_profile.has_tables is not None
    has_html = html_profile and html_profile.has_tables is not None
    
    # If we have TeX, prefer hybrid approaches
    if has_tex:
        if pdf_profile:
            # Both TeX and PDF available - use hybrid
            if tex_profile.table_complexity == "cross_page":
                return "tex+pymupdf4llm+docling"
            elif tex_profile.has_tables or pdf_profile.has_tables:
                return "tex+pymupdf4llm"
            else:
                return "tex_only"
        else:
            # Only TeX
            return "tex_only"
    
    # No TeX, use PDF
    if has_pdf:
        if pdf_profile.table_complexity == "cross_page":
            return "docling"
        elif pdf_profile.has_tables or pdf_profile.has_equations:
            return "pymupdf4llm"
        else:
            return "basic"
    
    # Fallback to HTML
    if has_html:
        return "html"
    
    return "basic"


# Convenience function for full analysis
def analyze_all_sources(tex: str = None, pdf_bytes: bytes = None, html: str = None) -> dict:
    """Analyze all available sources and return decision."""
    tex_profile = analyze_tex(tex) if tex else None
    pdf_profile = analyze_pdf(pdf_bytes) if pdf_bytes else None
    html_profile = analyze_html(html) if html else None
    
    strategy = decide_strategy(tex_profile, pdf_profile, html_profile)
    
    return {
        "strategy": strategy,
        "tex_profile": tex_profile,
        "pdf_profile": pdf_profile,
        "html_profile": html_profile,
    }


if __name__ == "__main__":
    # Quick test
    import sys
    if len(sys.argv) > 1:
        arxiv_id = sys.argv[1]
        # Test with a known paper
        from pathlib import Path
        import urllib.request
        
        # Try to download TeX
        try:
            url = f"https://arxiv.org/e-print/{arxiv_id}"
            req = urllib.request.Request(url, headers={'User-Agent': 'wiki-rag/1.0'})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
            if data[:2] == b'\x1f\x8b':
                import tarfile, io
                with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as tar:
                    tex_files = [m for m in tar.getmembers() if m.name.endswith('.tex')]
                    if tex_files:
                        tex = tar.extractfile(tex_files[0]).read().decode('utf-8', errors='replace')
                        profile = analyze_tex(tex)
                        print(f"TeX Profile: {profile}")
        except Exception as e:
            print(f"Error: {e}")
