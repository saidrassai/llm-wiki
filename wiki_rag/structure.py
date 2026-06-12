#!/usr/bin/env python3
"""
Structure extraction specialists for hybrid pipeline.
Extract document structure (sections, equations, citations, figures) WITHOUT tables.
"""

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Section:
    """A document section."""
    level: str  # "section", "subsection", "subsubsection"
    title: str
    content_start: int = 0  # character offset in clean text


@dataclass
class Equation:
    """A mathematical equation."""
    latex: str
    display: bool  # True for $$...$$, \[...\], \begin{equation}...; False for $...$
    position: int  # character offset in clean text


@dataclass
class Citation:
    """A citation reference."""
    keys: list[str]  # multiple keys from \cite{key1,key2}
    raw: str  # original \cite{...}
    position: int


@dataclass
class CrossRef:
    """A cross-reference."""
    ref_type: str  # "ref", "eqref", "autoref", "cref", "label"
    label: str
    raw: str
    position: int


@dataclass
class Figure:
    """A figure with caption."""
    caption: str
    label: str = ""
    position: int = 0


@dataclass
class Structure:
    """Document structure without tables."""
    title: str = ""
    abstract: str = ""
    sections: list[Section] = field(default_factory=list)
    equations: list[Equation] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    crossrefs: list[CrossRef] = field(default_factory=list)
    figures: list[Figure] = field(default_factory=list)
    clean_text: str = ""  # Full text with table placeholders
    table_placeholders: list[dict] = field(default_factory=list)  # {position, caption, label, env_type}


def _protect_math(text: str) -> tuple[str, list[str]]:
    """Temporarily replace math with placeholders to avoid regex interference."""
    math_parts = []
    # Display math: $$...$$ or \[...\]
    def replace_display(m):
        math_parts.append(m.group(0))
        return f"__MATH_DISPLAY_{len(math_parts)-1}__"
    
    text = re.sub(r'\$\$(.*?)\$\$', replace_display, text, flags=re.DOTALL)
    text = re.sub(r'\\\[(.*?)\\\]', replace_display, text, flags=re.DOTALL)
    text = re.sub(r'\\begin\{equation\*?\}(.*?)\\end\{equation\*?\}', 
                  lambda m: replace_display(m), text, flags=re.DOTALL)
    
    # Inline math: $...$ (not $$)
    def replace_inline(m):
        math_parts.append(m.group(0))
        return f"__MATH_INLINE_{len(math_parts)-1}__"
    
    text = re.sub(r'(?<!\$)\$(?!\$)([^\$\n]+?)(?<!\$)\$(?!\$)', replace_inline, text)
    
    return text, math_parts


def _restore_math(text: str, math_parts: list[str]) -> str:
    """Restore math from placeholders."""
    for i, part in enumerate(math_parts):
        text = text.replace(f"__MATH_DISPLAY_{i}__", part)
        text = text.replace(f"__MATH_INLINE_{i}__", part)
    return text


def extract_structure_from_tex(tex: str) -> Structure:
    """Extract document structure from TeX (sections, equations, citations, figures). NO tables."""
    if not tex:
        return Structure()
    
    struct = Structure()
    
    # Extract document body
    doc_start = re.search(r'\\begin\{document\}', tex)
    doc_end = re.search(r'\\end\{document\}', tex)
    
    if doc_start and doc_end:
        body = tex[doc_start.end():doc_end.start()]
    elif doc_start:
        body = tex[doc_start.end():]
    else:
        body = tex
    
    # Title (can be in preamble)
    title_match = re.search(r'\\title\{([^}]*)\}', tex)
    if title_match:
        struct.title = title_match.group(1).strip()
    
    # Abstract
    abstract_match = re.search(r'\\begin\{abstract\}(.*?)\\end\{abstract\}', body, flags=re.DOTALL)
    if abstract_match:
        struct.abstract = abstract_match.group(1).strip()
    
    # Protect math during processing
    protected_body, math_parts = _protect_math(body)
    
    # Remove preamble commands
    protected_body = re.sub(r'\\documentclass(\[[^\]]*\])?\{[^}]*\}', '', protected_body)
    protected_body = re.sub(r'\\usepackage(\[[^\]]*\])?\{[^}]*\}', '', protected_body)
    protected_body = re.sub(r'\\(newcommand|renewcommand|def)(\[[^\]]*\])?\{[^}]*\}(\[[^\]]*\])?(\{[^}]*\})?', '', protected_body)
    
    # ===== SECTIONS =====
    section_pattern = r'\\(section|subsection|subsubsection)\*?\{([^}]*)\}'
    for match in re.finditer(section_pattern, protected_body):
        struct.sections.append(Section(
            level=match.group(1),
            title=match.group(2).strip(),
            content_start=match.end()
        ))
    
    # ===== EQUATIONS (find in original body) =====
    # Display equations: $$...$$
    for match in re.finditer(r'\$\$(.*?)\$\$', body, flags=re.DOTALL):
        struct.equations.append(Equation(
            latex=match.group(1).strip(),
            display=True,
            position=match.start()
        ))
    # Display equations: \[...\]
    for match in re.finditer(r'\\\[(.*?)\\\]', body, flags=re.DOTALL):
        struct.equations.append(Equation(
            latex=match.group(1).strip(),
            display=True,
            position=match.start()
        ))
    # \begin{equation}...\end{equation}
    for match in re.finditer(r'\\begin\{equation\*?\}(.*?)\\end\{equation\*?\}', body, flags=re.DOTALL):
        struct.equations.append(Equation(
            latex=match.group(1).strip(),
            display=True,
            position=match.start()
        ))
    # \begin{align}...\end{align} etc.
    for match in re.finditer(r'\\begin\{(align|eqnarray|gather|multline)\*?\}(.*?)\\end\{(align|eqnarray|gather|multline)\*?\}', body, flags=re.DOTALL):
        struct.equations.append(Equation(
            latex=match.group(2).strip(),
            display=True,
            position=match.start()
        ))
    # Inline equations: $...$
    for match in re.finditer(r'(?<!\$)\$(?!\$)([^\$\n]+?)(?<!\$)\$(?!\$)', body):
        struct.equations.append(Equation(
            latex=match.group(1).strip(),
            display=False,
            position=match.start()
        ))
    
    # ===== CITATIONS =====
    cite_pattern = r'\\cite\w*(\[[^\]]*\])?\{([^}]*)\}'
    for match in re.finditer(cite_pattern, protected_body):
        keys = [k.strip() for k in match.group(2).split(',')]
        struct.citations.append(Citation(
            keys=keys,
            raw=match.group(0),
            position=match.start()
        ))
    
    # ===== CROSS-REFERENCES =====
    ref_patterns = [
        (r'\\ref\{([^}]*)\}', "ref"),
        (r'\\eqref\{([^}]*)\}', "eqref"),
        (r'\\autoref\{([^}]*)\}', "autoref"),
        (r'\\cref\{([^}]*)\}', "cref"),
        (r'\\label\{([^}]*)\}', "label"),
    ]
    for pattern, ref_type in ref_patterns:
        for match in re.finditer(pattern, protected_body):
            struct.crossrefs.append(CrossRef(
                ref_type=ref_type,
                label=match.group(1),
                raw=match.group(0),
                position=match.start()
            ))
    
    # ===== FIGURES =====
    fig_pattern = r'\\begin\{figure\*?\}(.*?)\\end\{figure\*?\}'
    for match in re.finditer(fig_pattern, body, flags=re.DOTALL):
        fig_content = match.group(1)
        caption = ""
        label = ""
        
        cap_match = re.search(r'\\caption\*?\{([^}]*)\}', fig_content)
        if cap_match:
            caption = cap_match.group(1).strip()
        
        label_match = re.search(r'\\label\{([^}]*)\}', fig_content)
        if label_match:
            label = label_match.group(1).strip()
        
        struct.figures.append(Figure(
            caption=caption,
            label=label,
            position=match.start()
        ))
    
    # ===== TABLE PLACEHOLDERS (for later merging) =====
    # Only track OUTERMOST table environments (wrappers): table*, table, longtable, tabularx
    # Do NOT track inner tabular/tabular* environments
    wrapper_envs = [
        (r'\\begin\{table\*?\}(?:\[[^\]]*\])?(.*?)\\end\{table\*?\}', "table"),
        (r'\\begin\{longtable\}(.*?)\\end\{longtable\}', "longtable"),
        (r'\\begin\{tabularx\}(.*?)\\end\{tabularx\}', "tabularx"),
    ]
    
    for pattern, env_type in wrapper_envs:
        for match in re.finditer(pattern, body, flags=re.DOTALL):
            content = match.group(1)
            caption = ""
            label = ""
            
            cap_match = re.search(r'\\caption\*?\{([^}]*)\}', content)
            if cap_match:
                caption = cap_match.group(1).strip()
            
            label_match = re.search(r'\\label\{([^}]*)\}', content)
            if label_match:
                label = label_match.group(1).strip()
            
            struct.table_placeholders.append({
                "position": match.start(),
                "caption": caption,
                "label": label,
                "env_type": env_type,
                "raw_content": content[:200]  # First 200 chars for matching
            })
    
    # ===== CLEAN TEXT (for markdown output) =====
    clean = _strip_latex_for_structure(body)
    struct.clean_text = _restore_math(clean, math_parts)
    
    return struct


def _strip_latex_for_structure(text: str) -> str:
    """Simplified LaTeX to markdown for structure (sections, formatting), NO tables."""
    # Remove comments
    text = re.sub(r'(?<!\\)%.*$', '', text, flags=re.MULTILINE)
    
    # Remove environments we don't want inline
    for env in ['figure', 'algorithm', 'algorithmic', 'tikzpicture',
                'itemize', 'enumerate', 'description', 'verbatim', 'lstlisting', 'minipage']:
        text = re.sub(r'\\begin\{' + env + r'\}.*?\\end\{' + env + r'\}', '', text, flags=re.DOTALL)
    
    # Replace OUTERMOST table environments with placeholders
    # First pass: match and replace table*, table, longtable, tabularx (wrappers)
    # These contain inner tabular environments
    wrapper_envs = ['table*', 'table', 'longtable', 'tabularx']
    for env in wrapper_envs:
        text = re.sub(r'\\begin\{' + env + r'\}(?:\[[^\]]*\])?.*?\\end\{' + env + r'\}', 
                      '[TABLE_PLACEHOLDER]', text, flags=re.DOTALL)
    
    # Second pass: match standalone tabular/tabular* (not inside wrappers, since wrappers removed)
    # Now .*? won't cross the removed wrapper boundaries
    standalone_tabulars = ['tabular*', 'tabular']
    for env in standalone_tabulars:
        text = re.sub(r'\\begin\{' + env + r'\}(?:\[[^\]]*\])?.*?\\end\{' + env + r'\}', 
                      '[TABLE_PLACEHOLDER]', text, flags=re.DOTALL)
    
    # Sections
    text = re.sub(r'\\section\*?\{([^}]*)\}', r'\n## \1\n', text)
    text = re.sub(r'\\subsection\*?\{([^}]*)\}', r'\n### \1\n', text)
    text = re.sub(r'\\subsubsection\*?\{([^}]*)\}', r'\n#### \1\n', text)
    
    # Formatting
    for cmd in ['textbf', 'textit', 'emph', 'underline', 'textsc', 'texttt',
                'mathrm', 'mathit', 'mathbf', 'mathbb', 'mathcal', 'mathfrak', 'text']:
        text = re.sub(r'\\' + cmd + r'\{([^}]*)\}', r'\1', text)
    
    # Citations
    text = re.sub(r'\\cite\w*(\[[^\]]*\])?\{([^}]*)\}', r'[@\2]', text)
    text = re.sub(r'\\ref\{([^}]*)\}', r'[#\1]', text)
    text = re.sub(r'\\eqref\{([^}]*)\}', r'[Eq. #\1]', text)
    text = re.sub(r'\\autoref\{([^}]*)\}', r'[@\1]', text)
    text = re.sub(r'\\label\{([^}]*)\}', r'<!-- label: \1 -->', text)
    
    # Links
    text = re.sub(r'\\url\{([^}]*)\}', r'<\1>', text)
    text = re.sub(r'\\href\{([^}]*)\}\{([^}]*)\}', r'[\2](\1)', text)
    
    # Footnotes
    text = re.sub(r'\\footnote\{([^{}]*(\{[^}]*\}[^{}]*)*)\}', r'[^fn]', text)
    
    # Captions
    text = re.sub(r'\\caption\*?\{([^}]*)\}', r'\n**Caption:** \1\n', text)
    
    # Remove remaining control sequences (but preserve math)
    text = re.sub(r'\\[a-zA-Z]+\*?(?:\[[^\]]*\])?(?:\{[^}]*\})?', '', text)
    text = re.sub(r'\\[a-zA-Z]+\b', '', text)
    
    # Cleanup
    text = re.sub(r' {3,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text.strip()


def extract_structure_from_html(html: str) -> Structure:
    """Extract document structure from ArXiv HTML."""
    struct = Structure()
    
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return struct
    
    soup = BeautifulSoup(html, 'html.parser')
    
    # Title
    title_tag = soup.find('title') or soup.find('h1')
    if title_tag:
        struct.title = title_tag.get_text(strip=True)
    
    # Abstract
    abstract_tag = soup.find('abstract') or soup.find(class_='abstract')
    if abstract_tag:
        struct.abstract = abstract_tag.get_text(strip=True)
    
    # Sections
    for h_tag in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
        level = h_tag.name
        level_map = {'h1': 'section', 'h2': 'subsection', 'h3': 'subsubsection'}
        struct.sections.append(Section(
            level=level_map.get(level, level),
            title=h_tag.get_text(strip=True)
        ))
    
    # Equations (MathML or LaTeX in HTML)
    for math_tag in soup.find_all('math'):
        mathml = str(math_tag)
        struct.equations.append(Equation(
            latex=mathml,  # Could convert MathML to LaTeX
            display=True,
            position=0
        ))
    
    # Equations in LaTeX format
    for tag in soup.find_all(class_=re.compile(r'math|equation')):
        text = tag.get_text(strip=True)
        if text and ('$' in text or '\\' in text):
            struct.equations.append(Equation(
                latex=text,
                display='display' in tag.get('class', []) or '$$' in text,
                position=0
            ))
    
    # Citations
    for cite_tag in soup.find_all(class_=re.compile(r'cite|reference')):
        keys = cite_tag.get_text(strip=True)
        struct.citations.append(Citation(
            keys=[keys],
            raw=keys,
            position=0
        ))
    
    # Figures
    for fig_tag in soup.find_all('figure'):
        caption = ""
        caption_tag = fig_tag.find('figcaption') or fig_tag.find('caption')
        if caption_tag:
            caption = caption_tag.get_text(strip=True)
        
        img = fig_tag.find('img')
        label = img.get('id', '') if img else ""
        
        struct.figures.append(Figure(caption=caption, label=label))
    
    # Clean text
    struct.clean_text = soup.get_text(separator='\n', strip=True)
    
    return struct


def merge_structure_with_tables(struct: Structure, tables: list, 
                                match_by: str = "caption") -> Structure:
    """
    Merge extracted tables back into structure at placeholder positions.
    
    Returns new Structure with tables replaced in clean_text.
    """
    if not tables or not struct.table_placeholders:
        return struct
    
    # Match tables to placeholders
    matched = {}
    used_tables = set()
    
    for i, placeholder in enumerate(struct.table_placeholders):
        best_match = None
        best_score = 0
        
        for j, table in enumerate(tables):
            if j in used_tables:
                continue
            
            score = 0
            if match_by == "caption" and placeholder["caption"] and table.caption:
                # Simple word overlap score
                p_words = set(placeholder["caption"].lower().split())
                t_words = set(table.caption.lower().split())
                if p_words and t_words:
                    score = len(p_words & t_words) / max(len(p_words), len(t_words))
            elif placeholder["label"] and table.label:
                score = 1.0 if placeholder["label"] == table.label else 0
            elif placeholder["position"] and table.page_hint:
                # Can't easily match position, use lower score
                score = 0.3
            else:
                # Positional matching
                score = 0.2
            
            if score > best_score:
                best_score = score
                best_match = j
        
        if best_match is not None and best_score > 0.3:
            matched[i] = best_match
            used_tables.add(best_match)
    
    # Build new clean_text with tables inserted
    # Sort placeholders by position
    sorted_placeholders = sorted(enumerate(struct.table_placeholders), key=lambda x: x[1]["position"])
    
    new_text = struct.clean_text
    offset_delta = 0
    
    for orig_idx, placeholder in sorted_placeholders:
        if orig_idx in matched:
            table_idx = matched[orig_idx]
            table_md = tables[table_idx].markdown
            
            # Find and replace placeholder in new_text
            placeholder_marker = "[TABLE_PLACEHOLDER]"
            pos = new_text.find(placeholder_marker, placeholder["position"] + offset_delta)
            if pos >= 0:
                new_text = new_text[:pos] + "\n\n" + table_md + "\n\n" + new_text[pos + len(placeholder_marker):]
                offset_delta += len(table_md) + 4 - len(placeholder_marker)
    
    struct.clean_text = new_text
    return struct


if __name__ == "__main__":
    import sys
    sys.path.insert(0, '/home/ubuntu/wiki-rag-package')
    
    sample_tex = r"""
    \documentclass{article}
    \begin{document}
    \title{Test Paper}
    \begin{abstract}This is an abstract with $E=mc^2$ inline math.\end{abstract}
    \section{Introduction}
    Some text with a citation \cite{author2024}.
    \begin{equation}
    x = y + z
    \end{equation}
    \begin{figure}
    \centering
    \caption{Test figure}
    \label{fig:test}
    \end{figure}
    \begin{table}
    \caption{Test table}
    \label{tab:test}
    \begin{tabular}{cc}
    A & B \\
    1 & 2 \\
    \end{tabular}
    \end{table}
    \end{document}
    """
    
    from wiki_rag.structure import extract_structure_from_tex
    struct = extract_structure_from_tex(sample_tex)
    print(f"Title: {struct.title}")
    print(f"Abstract: {struct.abstract[:50]}...")
    print(f"Sections: {[(s.level, s.title) for s in struct.sections]}")
    print(f"Equations: {len(struct.equations)} ({[e.display for e in struct.equations]})")
    print(f"Citations: {len(struct.citations)}")
    print(f"Figures: {len(struct.figures)}")
    print(f"Table placeholders: {len(struct.table_placeholders)}")
    print(f"Clean text preview: {struct.clean_text[:200]}...")