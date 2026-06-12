#!/usr/bin/env python3
"""
Hybrid merger - combines TeX structure with pymupdf4llm/Docling tables.
"""

from typing import Optional
from wiki_rag.structure import Structure
from wiki_rag.tables import Table
from wiki_rag.detect import ContentProfile


def match_tables_to_placeholders(
    placeholders: list[dict], 
    tables: list[Table],
    match_by: str = "caption"
) -> dict[int, int]:
    """
    Match extracted tables to TeX table placeholders.
    
    Returns dict: {placeholder_index -> table_index}
    """
    if not placeholders or not tables:
        return {}
    
    matched = {}
    used_tables = set()
    
    for i, placeholder in enumerate(placeholders):
        best_match = None
        best_score = 0
        
        for j, table in enumerate(tables):
            if j in used_tables:
                continue
            
            score = 0
            
            if match_by == "caption" and placeholder["caption"] and table.caption:
                # Word overlap score
                p_words = set(placeholder["caption"].lower().split())
                t_words = set(table.caption.lower().split())
                if p_words and t_words:
                    overlap = len(p_words & t_words)
                    score = overlap / max(len(p_words), len(t_words))
            
            elif placeholder["label"] and table.label:
                score = 1.0 if placeholder["label"] == table.label else 0
            
            elif placeholder.get("position") and table.page_hint:
                # Page proximity (approximate)
                score = 0.3
            
            else:
                # Positional fallback (first with first)
                score = 0.2
            
            if score > best_score:
                best_score = score
                best_match = j
        
        if best_match is not None and best_score > 0.3:
            matched[i] = best_match
            used_tables.add(best_match)
    
    return matched


def merge_structure_with_tables(struct: Structure, tables: list[Table], 
                                match_by: str = "caption") -> Structure:
    """
    Merge extracted tables back into structure at placeholder positions.
    """
    if not tables or not struct.table_placeholders:
        return struct
    
    matched = match_tables_to_placeholders(struct.table_placeholders, tables, match_by)
    
    # Find all [TABLE_PLACEHOLDER] markers in clean_text
    import re
    placeholder_positions = [m.start() for m in re.finditer(r'\[TABLE_PLACEHOLDER\]', struct.clean_text)]
    
    if len(placeholder_positions) != len(struct.table_placeholders):
        print(f"Warning: {len(placeholder_positions)} markers in text vs {len(struct.table_placeholders)} placeholders")
    
    # Process in REVERSE order (highest position first) so earlier replacements don't shift later positions
    # placeholder_positions is already in ascending order; reverse it
    reversed_positions = list(reversed(placeholder_positions))
    reversed_placeholders = list(reversed(struct.table_placeholders))
    
    new_text = struct.clean_text
    
    for i, (orig_idx, placeholder) in enumerate(reversed(list(enumerate(struct.table_placeholders)))):
        if orig_idx in matched:
            table_idx = matched[orig_idx]
            table_md = tables[table_idx].markdown
            
            # Use reversed positional mapping
            if i < len(reversed_positions):
                pos = reversed_positions[i]
                new_text = (new_text[:pos] + 
                           "\n\n" + table_md + "\n\n" + 
                           new_text[pos + len("[TABLE_PLACEHOLDER]"):])
    
    struct.clean_text = new_text
    return struct


def build_hybrid_markdown(
    struct: Structure,
    source_type: str,
    arxiv_id: str,
    title: str,
    authors: str,
    abstract: str,
    tables: list[Table]
) -> str:
    """
    Build final markdown from merged structure.
    """
    md_parts = [
        "---",
        f"source_url: https://arxiv.org/abs/{arxiv_id}",
        f"ingested: {{date.today().isoformat()}}",
        "---",
        "",
        f"# {title}",
        "",
        f"**Authors:** {authors}",
        f"**arXiv:** {arxiv_id}",
        f"**Source:** {source_type}",
        "",
    ]
    
    if abstract:
        md_parts += ["## Abstract", "", abstract, ""]
    
    # Use merged clean_text which has tables inserted
    if struct.clean_text:
        md_parts.append(struct.clean_text)
    else:
        # Fallback: sections + equations
        if struct.sections:
            for sec in struct.sections:
                md_parts.append(f"## {sec.title}")
                md_parts.append("")
        if struct.equations:
            md_parts.append("## Equations")
            md_parts.append("")
            for eq in struct.equations:
                if eq.display:
                    md_parts.append(f"```math\n{eq.latex}\n```")
                else:
                    md_parts.append(f"${eq.latex}$")
                md_parts.append("")
    
    return "\n".join(md_parts)


def decide_final_source_type(
    tex_profile: Optional[ContentProfile],
    pdf_profile: Optional[ContentProfile],
    strategy: str,
    fallback_used: bool = False
) -> str:
    """
    Determine the final source_type string for metadata.
    """
    source_parts = []
    
    if "tex" in strategy:
        source_parts.append("tex")
    if "pymupdf4llm" in strategy:
        source_parts.append("pymupdf4llm")
    if "docling" in strategy:
        source_parts.append("docling")
    if "html" in strategy:
        source_parts.append("html")
    
    if fallback_used:
        source_parts.append("fallback")
    
    return "+".join(source_parts) if source_parts else "basic"


def assess_table_quality(tables: list[Table]) -> dict:
    """
    Assess quality of extracted tables.
    """
    if not tables:
        return {"quality": "none", "issues": ["No tables extracted"]}
    
    issues = []
    for i, table in enumerate(tables):
        if not table.markdown or not table.markdown.strip():
            issues.append(f"Table {i}: Empty markdown")
        elif table.row_count < 2:
            issues.append(f"Table {i}: Only {table.row_count} row(s)")
        elif table.col_count < 2:
            issues.append(f"Table {i}: Only {table.col_count} column(s)")
        elif "<br>" in table.markdown:
            issues.append(f"Table {i}: Contains <br> tags (not cleaned)")
    
    if not issues:
        quality = "good"
    elif len(issues) < len(tables):
        quality = "partial"
    else:
        quality = "poor"
    
    return {"quality": quality, "issues": issues}


if __name__ == "__main__":
    # Test matching
    from wiki_rag.tables import Table
    from wiki_rag.structure import Structure
    
    # Mock structure with placeholders
    struct = Structure()
    struct.table_placeholders = [
        {"position": 100, "caption": "Test table", "label": "tab:test"},
        {"position": 200, "caption": "Results", "label": "tab:results"},
    ]
    struct.clean_text = "Intro\n\n[TABLE_PLACEHOLDER]\n\nMiddle\n\n[TABLE_PLACEHOLDER]\n\nEnd"
    
    # Mock tables
    tables = [
        Table(
            markdown="| A | B |\n|---|\n| 1 | 2 |\n",
            caption="Test table",
            label="tab:test",
            source="pymupdf4llm"
        ),
        Table(
            markdown="| X | Y |\n|---|\n| a | b |\n",
            caption="Results",
            label="tab:results",
            source="pymupdf4llm"
        ),
    ]
    
    merged = merge_structure_with_tables(struct, tables)
    print("Merged text:")
    print(merged.clean_text)