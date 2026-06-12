#!/usr/bin/env python3
"""
Table extraction specialists for hybrid pipeline.
Each function extracts clean markdown tables from a specific source.
"""

import re
from dataclasses import dataclass
from typing import Optional
from pathlib import Path


@dataclass
class Table:
    """A single extracted table with metadata."""
    markdown: str
    caption: str = ""
    label: str = ""
    page_hint: Optional[int] = None
    source: str = "unknown"  # "pymupdf4llm", "tex", "docling", "html"
    bbox: Optional[tuple] = None  # (x0, y0, x1, y1) if available
    row_count: int = 0
    col_count: int = 0


def _clean_table_markdown(text: str) -> str:
    """Clean up pymupdf4llm table markdown: replace <br> with spaces."""
    lines = text.split('\n')
    cleaned = []
    for line in lines:
        if line.strip().startswith('|') and line.strip().endswith('|'):
            line = line.replace('<br>', ' ')
            line = line.replace('<br/>', ' ')
            line = line.replace('<br />', ' ')
        cleaned.append(line)
    return '\n'.join(cleaned)


def _parse_markdown_table(table_md: str) -> tuple[int, int]:
    """Parse markdown table to count rows and columns."""
    lines = [l for l in table_md.strip().split('\n') if l.strip().startswith('|') and l.strip().endswith('|')]
    if not lines:
        return 0, 0
    row_count = len(lines) - 1  # minus header separator
    col_count = lines[0].count('|') - 1
    return row_count, col_count


def extract_tables_from_pymupdf4llm(pdf_bytes: bytes) -> list[Table]:
    """Extract tables from PDF using pymupdf4llm (fast, clean markdown)."""
    tables = []
    
    try:
        import pymupdf4llm
        import fitz
    except ImportError:
        return tables
    
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        
        # Get full markdown with tables
        full_markdown = pymupdf4llm.to_markdown(
            doc,
            page_chunks=False,
            ignore_headers=True,
            ignore_footers=True,
            use_ocr=True,
            force_ocr=False,
        )
        full_markdown = _clean_table_markdown(full_markdown) if isinstance(full_markdown, str) else ""
        
        # Also get page chunks for page mapping
        chunks = pymupdf4llm.to_markdown(
            doc,
            page_chunks=True,
            ignore_headers=True,
            ignore_footers=True,
            use_ocr=True,
            force_ocr=False,
        )
        
        doc.close()
        
        if not full_markdown:
            return tables
        
        # Extract all table captions from full markdown with their positions
        caption_matches = list(re.finditer(r'(Table\s+\d+[.:]\s*[^\n]+)', full_markdown, re.IGNORECASE))
        captions = [(m.start(), m.group(1).strip()) for m in caption_matches]
        
        # Extract all pipe tables from full markdown
        table_blocks = re.split(r'\n\s*\n', full_markdown)
        pipe_tables = []
        for block in table_blocks:
            block = block.strip()
            if block.startswith('|') and block.endswith('|') and block.count('|') >= 4:
                rc, cc = _parse_markdown_table(block)
                if rc >= 1 and cc >= 2:
                    block_pos = full_markdown.find(block)
                    pipe_tables.append({
                        "markdown": block,
                        "position": block_pos,
                        "row_count": rc,
                        "col_count": cc,
                    })
        
        # Match tables to captions by proximity
        for table in pipe_tables:
            table_pos = table["position"]
            best_caption = ""
            best_dist = float('inf')
            
            for cap_pos, cap_text in captions:
                dist = abs(table_pos - cap_pos)
                if dist < best_dist and dist < 500:  # within 500 chars
                    best_dist = dist
                    best_caption = cap_text
            
            # Find page hint from chunks
            page_hint = 0
            for chunk in chunks:
                chunk_text = chunk.get("text", "")
                if table["markdown"][:50] in chunk_text:
                    page_hint = chunk.get("metadata", {}).get("page", 0)
                    break
            
            tables.append(Table(
                markdown=table["markdown"],
                caption=best_caption,
                label="",
                page_hint=page_hint,
                source="pymupdf4llm",
                bbox=None,
                row_count=table["row_count"],
                col_count=table["col_count"],
            ))
        
    except Exception as e:
        print(f"pymupdf4llm table extraction error: {e}")
    
    return tables


def extract_tables_from_tex(tex: str) -> list[Table]:
    """Extract tables from TeX source using regex (handles tabular, longtable, tabularx)."""
    tables = []
    
    if not tex:
        return tables
    
    # Find all table environments (table, table*, tabular, tabular*, longtable, tabularx)
    # Strategy: find table wrappers first, then extract tabular inside
    
    def extract_from_tabular(content: str, env_name: str, page_hint: int = None) -> Table:
        """Convert a single tabular environment to markdown."""
        # Remove booktabs commands
        content = re.sub(r'\\toprule\s*', '', content)
        content = re.sub(r'\\midrule\s*', '', content)
        content = re.sub(r'\\bottomrule\s*', '', content)
        content = re.sub(r'\\cmidrule(\[[^\]]*\])?\{[^}]*\}', '', content)
        content = re.sub(r'\\addlinespace(\[\w+\])?', '', content)
        content = re.sub(r'\\hline', '', content)
        content = re.sub(r'\\centering', '', content)
        content = re.sub(r'\[[htbp!]+\]', '', content)  # [h], [t], [b], [p], [!]
        content = re.sub(r'\\hline', '', content)
        
        # Split rows
        rows = re.sub(r'\\\\', '\n', content)
        lines = [l.strip() for l in rows.split('\n') if l.strip()]
        if not lines:
            return None
        
        md = []
        for line in lines:
            # Handle multicolumn
            line = _convert_multicolumn(line)
            # Convert & to |
            line = re.sub(r'\s*&\s*', ' | ', line.strip('&').strip())
            md.append(f'| {line} |')
        
        if len(md) < 2:
            return None
        
        cols = md[0].count('|') - 1
        md.insert(1, '|' + ' --- |' * cols)
        
        markdown = '\n' + '\n'.join(md) + '\n'
        rc, cc = _parse_markdown_table(markdown)
        
        return Table(
            markdown=markdown,
            source=f"tex-{env_name}",
            page_hint=page_hint,
            row_count=rc,
            col_count=cc,
        )
    
    def _convert_multicolumn(line: str) -> str:
        """Convert \multicolumn{N}{c}{text} to repeated cells."""
        def replace_mc(m):
            n = int(m.group(1))
            text = m.group(2)
            return ' | '.join([text] * n)
        return re.sub(r'\\multicolumn\{(\d+)\}\{[^}]*\}\{([^}]*)\}', replace_mc, line)
    
    # Find table/table* wrappers and extract tabular inside
    table_wrapper_pattern = r'\\begin\{table\*?\}(?:\[[^\]]*\])?(.*?)\\end\{table\*?\}'
    for match in re.finditer(table_wrapper_pattern, tex, flags=re.DOTALL):
        wrapper_content = match.group(1)
        # Find tabular inside wrapper
        tabular_match = re.search(r'\\begin\{tabular\*?\}(.*?)\\end\{tabular\*?\}', wrapper_content, flags=re.DOTALL)
        if tabular_match:
            table = extract_from_tabular(tabular_match.group(1), "table")
            if table:
                # Try to find caption
                cap_match = re.search(r'\\caption\*?\{([^}]*)\}', wrapper_content)
                if cap_match:
                    table.caption = cap_match.group(1).strip()
                # Try to find label
                label_match = re.search(r'\\label\{([^}]*)\}', wrapper_content)
                if label_match:
                    table.label = label_match.group(1).strip()
                tables.append(table)
    
    # Find standalone tabular environments (not inside table wrapper)
    tabular_patterns = [
        (r'\\begin\{tabular\*?\}(.*?)\\end\{tabular\*?\}', "tabular"),
        (r'\\begin\{longtable\}(.*?)\\end\{longtable\}', "longtable"),
        (r'\\begin\{tabularx\}(.*?)\\end\{tabularx\}', "tabularx"),
    ]
    
    for pattern, env_name in tabular_patterns:
        for match in re.finditer(pattern, tex, flags=re.DOTALL):
            # Check if already captured inside table wrapper
            start = match.start()
            already_in_wrapper = False
            for w_match in re.finditer(table_wrapper_pattern, tex, flags=re.DOTALL):
                if w_match.start() < start < w_match.end():
                    already_in_wrapper = True
                    break
            
            if not already_in_wrapper:
                table = extract_from_tabular(match.group(1), env_name)
                if table:
                    # Try to find nearby caption/label
                    context = tex[max(0, start-500):start]
                    cap_match = re.search(r'\\caption\*?\{([^}]*)\}', context)
                    if cap_match:
                        table.caption = cap_match.group(1).strip()
                    label_match = re.search(r'\\label\{([^}]*)\}', context)
                    if label_match:
                        table.label = label_match.group(1).strip()
                    tables.append(table)
    
    return tables


def extract_tables_from_docling(pdf_bytes: bytes) -> list[Table]:
    """Extract tables from PDF using Docling (slow, accurate for complex tables)."""
    tables = []
    
    try:
        import subprocess
        import tempfile
        from pathlib import Path
    except ImportError:
        return tables
    
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "input.pdf"
        pdf_path.write_bytes(pdf_bytes)
        output_dir = Path(tmpdir) / "output"
        
        try:
            result = subprocess.run([
                "docling", str(pdf_path),
                "--to", "md",
                "--output", str(output_dir),
                "--no-ocr"
            ], capture_output=True, timeout=300)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return tables
        
        if result.returncode != 0:
            return tables
        
        # Find generated markdown file
        md_files = list(output_dir.rglob("*.md"))
        if not md_files:
            return tables
        
        markdown = md_files[0].read_text(encoding="utf-8")
        
        # Parse markdown for tables (Docling outputs standard markdown tables)
        # Split by double newline and find pipe tables
        blocks = re.split(r'\n\s*\n', markdown)
        
        for block in blocks:
            block = block.strip()
            if block.startswith('|') and block.endswith('|') and block.count('|') >= 4:
                rc, cc = _parse_markdown_table(block)
                if rc >= 1 and cc >= 2:
                    tables.append(Table(
                        markdown=block,
                        source="docling",
                        row_count=rc,
                        col_count=cc,
                    ))
    
    return tables


def extract_tables_from_html(html: str) -> list[Table]:
    """Extract tables from ArXiv HTML."""
    tables = []
    
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return tables
    
    soup = BeautifulSoup(html, 'html.parser')
    
    for i, table_tag in enumerate(soup.find_all('table')):
        # Extract caption
        caption = ""
        caption_tag = table_tag.find('caption')
        if caption_tag:
            caption = caption_tag.get_text(strip=True)
        else:
            # Look for preceding figure/table caption
            prev = table_tag.find_previous(['figcaption', 'caption'])
            if prev:
                caption = prev.get_text(strip=True)
        
        # Convert HTML table to markdown
        markdown = _html_table_to_markdown(table_tag)
        if markdown:
            rc, cc = _parse_markdown_table(markdown)
            tables.append(Table(
                markdown=markdown,
                caption=caption,
                source="html",
                row_count=rc,
                col_count=cc,
            ))
    
    return tables


def _html_table_to_markdown(table_tag) -> str:
    """Convert HTML table to markdown."""
    rows = []
    
    # Handle thead
    thead = table_tag.find('thead')
    header_cells = []
    if thead:
        for th in thead.find_all(['th', 'td']):
            header_cells.append(th.get_text(strip=True).replace('|', '\\|'))
    else:
        # First row as header
        first_row = table_tag.find('tr')
        if first_row:
            for th in first_row.find_all(['th', 'td']):
                header_cells.append(th.get_text(strip=True).replace('|', '\\|'))
    
    if not header_cells:
        return ""
    
    rows.append('| ' + ' | '.join(header_cells) + ' |')
    rows.append('|' + ' --- |' * len(header_cells))
    
    # Handle tbody
    tbody = table_tag.find('tbody')
    if tbody:
        row_tags = tbody.find_all('tr')
    else:
        # All rows after thead
        row_tags = table_tag.find_all('tr')[1:] if thead else table_tag.find_all('tr')
    
    for tr in row_tags:
        cells = []
        for td in tr.find_all(['td', 'th']):
            # Handle colspan/rowspan (simplified)
            colspan = int(td.get('colspan', 1))
            text = td.get_text(strip=True).replace('|', '\\|')
            for _ in range(colspan):
                cells.append(text)
        if cells:
            rows.append('| ' + ' | '.join(cells) + ' |')
    
    return '\n' + '\n'.join(rows) + '\n'


def merge_table_lists(primary: list[Table], secondary: list[Table], 
                      match_by: str = "caption") -> list[Table]:
    """
    Merge two table lists, preferring primary but filling gaps from secondary.
    Matching by caption similarity, then by order.
    """
    if not secondary:
        return primary
    if not primary:
        return secondary
    
    merged = list(primary)
    used_secondary = set()
    
    for p_table in primary:
        best_match = None
        best_score = 0
        
        for i, s_table in enumerate(secondary):
            if i in used_secondary:
                continue
            
            score = 0
            if match_by == "caption" and p_table.caption and s_table.caption:
                # Simple word overlap score
                p_words = set(p_table.caption.lower().split())
                s_words = set(s_table.caption.lower().split())
                if p_words and s_words:
                    score = len(p_words & s_words) / max(len(p_words), len(s_words))
            elif p_table.page_hint and s_table.page_hint:
                # Page proximity
                if abs(p_table.page_hint - s_table.page_hint) <= 1:
                    score = 0.5
            else:
                # Positional matching
                score = 0.3
            
            if score > best_score:
                best_score = score
                best_match = i
        
        if best_match is not None and best_score > 0.3:
            # Replace with better version from secondary (usually docling)
            if secondary[best_match].source in ("docling", "pymupdf4llm"):
                merged[merged.index(p_table)] = secondary[best_match]
            used_secondary.add(best_match)
    
    # Add any unmatched secondary tables
    for i, s_table in enumerate(secondary):
        if i not in used_secondary:
            merged.append(s_table)
    
    return merged


if __name__ == "__main__":
    import sys
    sys.path.insert(0, '/home/ubuntu/wiki-rag-package')
    
    # Quick test with sample TeX
    sample_tex = r"""
    \begin{table}[ht]
    \centering
    \begin{tabular}{ccc}
    A & B & C \\
    1 & 2 & 3 \\
    \end{tabular}
    \caption{Test table}
    \label{tab:test}
    \end{table}
    """
    
    from wiki_rag.tables import extract_tables_from_tex
    tables = extract_tables_from_tex(sample_tex)
    print(f"Extracted {len(tables)} tables from TeX")
    for t in tables:
        print(f"  Source: {t.source}, Caption: {t.caption}, Label: {t.label}")
        print(f"  Markdown:\n{t.markdown}")