# Technical Analysis & Implementation Design: Requirement R2 (Extended Document Format Support & Qdrant Indexing)

**Project:** Discord Multimodal RAG  
**Milestone:** Milestone 2 (R2: Extended Document Format Support & Qdrant Indexing)  
**Agent:** Explorer Subagent (`teamwork_preview_explorer_m2_1`)  
**Date:** 2026-07-24  

---

## 1. Executive Summary & Scope

Requirement **R2** expands the Discord Multimodal RAG system from basic text/PDF/image parsing to full support for **10 rich document formats**:
1. **`.docx`** (Microsoft Word documents)
2. **`.xlsx`** (Microsoft Excel spreadsheets)
3. **`.pptx`** (Microsoft PowerPoint presentations)
4. **`.csv`** (Comma-Separated Values)
5. **`.md`** (Markdown documents)
6. **`.py`** (Python source code)
7. **`.js`** (JavaScript source code)
8. **`.json`** (JSON data files)
9. **`.html`** (HTML web pages/documents)
10. **`.css`** (CSS stylesheets)

In addition to existing format support (**`.pdf`** via PyMuPDF, plain **`.txt`**, and images via Gemini Vision LLM), R2 ensures that text extraction preserves vital **structural cues** (headings, sheet names, slide numbers, code block syntax, table layouts) and enriches the **Qdrant payload metadata schema** to enable structured metadata filtering and context retrieval.

---

## 2. Current Architecture & Gap Analysis

### 2.1 `services/attachments.py`
- **Current State:**
  - `_SUPPORTED_EXTENSIONS` contains `.pdf`, `.txt`, `.md`, `.py`, `.json`, `.csv`, `.log`, `.xml`, `.yaml`, `.yml`, `.html`, `.css`, `.js`, `.ts`, `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.bmp`.
  - PDF extraction (`_extract_text_from_pdf`): Uses `fitz` (PyMuPDF) stream reading.
  - Image extraction (`_describe_image_with_llm`): Uses OpenRouter vision model.
  - Text file extraction (`_extract_text_from_text_file`): Attempts simple `UTF-8` / `latin-1` string decoding.
- **Gaps identified:**
  1. **Binary OpenXML Formats (`.docx`, `.xlsx`, `.pptx`):** If a user uploads a `.docx`, `.xlsx`, or `.pptx` file, `attachments.py` is missing parsers for them. If treated as generic text, `UTF-8` decoding fails or produces raw binary ZIP bytes (`PK\x03\x04...`).
  2. **Tabular & Structured Text (`.csv`, `.xlsx`):** `.csv` is currently read as plain text line-by-line without table layout formatting or column alignment. Excel files are completely unsupported.
  3. **Code Files (`.py`, `.js`, `.json`, `.css`):** Extracted as raw text without code block delimiters (` ```python ... ``` `) or file metadata headers, causing loss of language context during embedding/retrieval.
  4. **Structured Markup (`.html`):** HTML files are decoded as raw text, including `<script>`, `<style>`, and raw HTML tags, which bloat embeddings and introduce noisy tokens.
  5. **Lack of Metadata Return:** `extract_text_from_attachment()` currently returns `str | None` without structural metadata (such as page count, sheet names, slide count, or parsed file type).

### 2.2 `services/chunker.py`
- **Current State:**
  - `chunk_text()` uses recursive text splitting with separators `["\n\n", "\n", " ", ""]`.
  - `build_document_text()` prepends `[Catégorie: ... | Titre: ... | Par: ... | Dans: #... | Date: ...]`.
- **Gaps identified:**
  - Standard recursive chunking does not prioritize Markdown headings (`# `, `## `), section breaks (`---`), or code block boundaries (```). A chunk split can break in the middle of a code block or table row.
  - Prioritized separators in `chunk_text()` should include `\n\n--- `, `\n\n# `, and `\n\n``` ` to preserve structural units.

### 2.3 `services/vectorstore.py`
- **Current State:**
  - Implements hybrid search (Dense 3072d + Sparse BM25 via `fastembed.SparseTextEmbedding("Qdrant/bm25")`) with RRF fusion query.
  - Payload stored: `{"text": text, "metadata": metadata, "original_id": doc_id}`.
- **Gaps identified:**
  - Metadata payload lacks granular file tracking attributes required by R2: `file_type`, `file_ext`, `source` ("attachment" vs "message_body"), and `page_or_sheet_count`.
  - No query helper method for payload filtering by `file_ext` or `file_type`.

### 2.4 `cogs/indexer.py` & `cogs/rag.py`
- **Current State:**
  - `cogs/indexer.py` attaches basic metadata (`message_id`, `channel_id`, `author`, `category`, `title`, `timestamp`, `has_attachment`, `attachment_name`, `attachment_url`, `chunk_index`, `total_chunks`).
  - `cogs/rag.py` extracts `attachment_url` and `attachment_name` for display in Discord embeds.
- **Gaps identified:**
  - Need to populate the newly designed metadata schema (`file_type`, `file_ext`, `source`, `page_or_sheet_count`).
  - Embed response should indicate file format context when answering from extended formats (e.g. `[Feuille: Sheet1]` or `[Code: Python]`).

### 2.5 `requirements.txt` & Environment Status
- **Installed in `venv`:** `PyMuPDF` (fitz), `qdrant-client`, `fastembed`, `discord.py`, `openai`, `python-dotenv`, `aiohttp`, `flashrank`.
- **Missing in `venv` & `requirements.txt`:**
  - `python-docx` (for `.docx`)
  - `openpyxl` (for `.xlsx`)
  - `python-pptx` (for `.pptx`)
  - `pandas` (for advanced tabular processing if needed)
  - `beautifulsoup4` (for `.html` parsing)

---

## 3. Dependency Requirements Update (`requirements.txt`)

To support all 10 document formats robustly, the following packages must be added to `requirements.txt`:

```text
# Existing
discord.py>=2.3.0
qdrant-client>=1.9.0
flashrank>=0.2.0
openai>=1.40.0
python-dotenv>=1.0.0
PyMuPDF>=1.24.0
aiohttp>=3.9.0
fastembed>=0.3.0

# Added for Requirement R2 (Extended Document Formats)
python-docx>=1.1.0
openpyxl>=3.1.0
python-pptx>=0.6.23
pandas>=2.0.0
beautifulsoup4>=4.12.0
```

---

## 4. Extended Extractor Architecture (`services/attachments.py`)

### 4.1 Parser Registry & File Type Mapping

| Extension | File Type Identifier | Extractor Function | Library Used |
| :--- | :--- | :--- | :--- |
| `.pdf` | `pdf` | `_extract_text_from_pdf` | `fitz` (PyMuPDF) |
| `.docx` | `word` | `_extract_text_from_docx` | `python-docx` |
| `.xlsx` | `spreadsheet` | `_extract_text_from_xlsx` | `openpyxl` |
| `.pptx` | `presentation` | `_extract_text_from_pptx` | `python-pptx` |
| `.csv` | `csv` | `_extract_text_from_csv` | Built-in `csv` + `io` |
| `.md` | `markdown` | `_extract_text_from_markdown` | Built-in text / regex |
| `.py` | `code` | `_extract_text_from_code` | Built-in text |
| `.js`, `.ts` | `code` | `_extract_text_from_code` | Built-in text |
| `.css` | `code` | `_extract_text_from_code` | Built-in text |
| `.json` | `json` | `_extract_text_from_json` | `json` (built-in) |
| `.html`, `.htm` | `html` | `_extract_text_from_html` | `beautifulsoup4` |
| `.txt`, `.log`, `.yaml`, `.yml`, `.xml` | `text` | `_extract_text_from_text_file` | Built-in text |
| `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.bmp` | `image` | `_describe_image_with_llm` | OpenRouter Vision LLM |

### 4.2 Detailed Technical Specifications for Extractors

#### 4.2.1 `.docx` Extractor (`_extract_text_from_docx`)
- **Input:** `data: bytes`, `filename: str`
- **Logic:**
  1. Wrap bytes in `io.BytesIO(data)` and load via `docx.Document(stream)`.
  2. Iterate over elements in order (paragraphs and tables).
  3. Paragraph formatting:
     - Check paragraph style name. If `Heading 1` -> `# Title`, `Heading 2` -> `## Subtitle`, `Heading 3` -> `### Section`.
     - Bullet points (`List Bullet`) -> `- item text`.
  4. Table formatting:
     - Iterate through table rows and cells.
     - Convert cells into a formatted Markdown table:
       ```markdown
       | Header 1 | Header 2 |
       | --- | --- |
       | Val 1 | Val 2 |
       ```
  5. Prefix document with metadata header: `[Document Word: {filename}]`.
- **Return:** Formatted Markdown text string + structural metadata dict `{"page_or_sheet_count": None, "paragraph_count": N, "table_count": M}`.

#### 4.2.2 `.xlsx` Extractor (`_extract_text_from_xlsx`)
- **Input:** `data: bytes`, `filename: str`
- **Logic:**
  1. Wrap bytes in `io.BytesIO(data)` and load workbook via `openpyxl.load_workbook(stream, data_only=True)`.
  2. Iterate over `wb.worksheets`:
     - Add sheet divider: `\n\n--- Feuille: {sheet.title} ---\n`.
     - Extract non-empty rows using `sheet.iter_rows(values_only=True)`.
     - Format row values into a Markdown table layout or tab-delimited grid, filtering out fully `None` rows.
     - Cap max rows per sheet (e.g. first 500 rows) with truncation indicator `[... X lignes tronquées ...]`.
  3. Prefix with `[Classeur Excel: {filename} ({len(sheets)} feuille(s))]`.
- **Return:** Formatted text string + structural metadata dict `{"page_or_sheet_count": len(sheets)}`.

#### 4.2.3 `.pptx` Extractor (`_extract_text_from_pptx`)
- **Input:** `data: bytes`, `filename: str`
- **Logic:**
  1. Wrap bytes in `io.BytesIO(data)` and load presentation via `pptx.Presentation(stream)`.
  2. Iterate over `prs.slides` with 1-based index `slide_num`:
     - Extract slide title (from `slide.shapes.title.text` or first shape text).
     - Divider header: `\n\n--- Diapositive {slide_num}: {slide_title} ---\n`.
     - Extract text from all text frames and table shapes.
     - Check for speaker notes: if `slide.has_notes_slide` and notes text exists, add `\n[Notes du présentateur: {notes_text}]`.
  3. Prefix with `[Présentation PowerPoint: {filename} ({len(slides)} diapositive(s))]`.
- **Return:** Formatted text string + structural metadata dict `{"page_or_sheet_count": len(slides)}`.

#### 4.2.4 `.csv` Extractor (`_extract_text_from_csv`)
- **Input:** `data: bytes`, `filename: str`
- **Logic:**
  1. Decode bytes using `utf-8` with fallback to `latin-1`.
  2. Use `csv.reader` (sniffing delimiter `,`, `;`, `\t`).
  3. Format rows into Markdown table structure:
     - Row 0: Header `| Col1 | Col2 | ... |`
     - Header separator: `| --- | --- | ... |`
     - Rows 1..N: Data rows formatted cleanly.
  4. Prefix with `[Fichier CSV: {filename} ({row_count} lignes, {col_count} colonnes)]`.
- **Return:** Formatted Markdown table text string + metadata dict `{"page_or_sheet_count": None}`.

#### 4.2.5 `.md` Extractor (`_extract_text_from_markdown`)
- **Input:** `data: bytes`, `filename: str`
- **Logic:**
  1. Decode text safely (UTF-8 / latin-1).
  2. Preserve Markdown structures (# headings, list items, blockquotes, code blocks).
  3. Prefix with `[Document Markdown: {filename}]\n\n`.
- **Return:** Formatted text string.

#### 4.2.6 Code Extractors (`.py`, `.js`, `.ts`, `.css`) (`_extract_text_from_code`)
- **Input:** `data: bytes`, `filename: str`, `ext: str`
- **Logic:**
  1. Decode text safely.
  2. Map extension to code block language tag (`py` -> `python`, `js` -> `javascript`, `ts` -> `typescript`, `css` -> `css`).
  3. Count lines `line_count = len(text.splitlines())`.
  4. Format output:
     ```markdown
     [Code Source: {filename} ({lang_name}, {line_count} lignes)]
     ```{lang_tag}
     {code_content}
     ```
     ```
- **Return:** Code block wrapped text string.

#### 4.2.7 `.json` Extractor (`_extract_text_from_json`)
- **Input:** `data: bytes`, `filename: str`
- **Logic:**
  1. Decode bytes to string.
  2. Attempt `parsed_json = json.loads(text)`.
  3. If valid JSON:
     - Re-format with indent: `formatted = json.dumps(parsed_json, indent=2, ensure_ascii=False)`.
     - Extract top-level keys summary if dict.
     - Format:
       ```markdown
       [Fichier JSON: {filename}]
       ```json
       {formatted}
       ```
       ```
  4. If invalid JSON, fallback to code block formatted raw string.
- **Return:** Formatted JSON text string.

#### 4.2.8 `.html` Extractor (`_extract_text_from_html`)
- **Input:** `data: bytes`, `filename: str`
- **Logic:**
  1. Decode string and parse using `bs4.BeautifulSoup(html_text, 'html.parser')`.
  2. Remove non-content tags: `<script>`, `<style>`, `<noscript>`, `<svg>`, `<iframe>`.
  3. Extract page title `<title>` if present.
  4. Convert HTML structural tags into Markdown equivalents:
     - `<h1>` .. `<h6>` -> `#` .. `######`
     - `<p>` -> paragraph text
     - `<ul>`/`<ol>` + `<li>` -> bullet points `- `
     - `<table>` -> Markdown table
     - `<code>`/`<pre>` -> ``` code blocks
  5. Prefix with `[Page HTML: {filename} | Titre: {html_title}]`.
- **Return:** Clean extracted structural text string.

---

## 5. Structural Cue Preservation & Chunking Strategy

### 5.1 Text Preservation Rules
To prevent context fragmentation when text is processed by `chunk_text()`, extractors output text with standard structural section markers:
- **Sheet divider:** `\n\n--- Feuille: SheetName ---\n`
- **Slide divider:** `\n\n--- Diapositive N: SlideTitle ---\n`
- **Markdown Header:** `\n\n# Heading Title\n`
- **Code Block Boundary:** `\n\n```python\n...\n```\n`

### 5.2 Updated Chunking Separators (`services/chunker.py`)
Update recursive chunker `_split_text_recursive` separators priority list:

```python
SEPARATORS = [
    "\n\n--- ",     # Section / Sheet / Slide dividers
    "\n\n# ",       # Heading level 1
    "\n\n## ",      # Heading level 2
    "\n\n```",      # Code block boundaries
    "\n\n",         # Paragraph breaks
    "\n",           # Line breaks
    " ",            # Word breaks
    "",             # Character fallback
]
```

This ordering guarantees that sheet/slide dividers, Markdown headers, and code block boundaries take precedence during text splitting, preserving document context integrity.

---

## 6. Enhanced Qdrant Metadata Schema Design

Each indexed chunk point stored in Qdrant will carry a comprehensive metadata dictionary in its payload (`payload["metadata"]`).

### 6.1 Payload Field Specification

| Field Name | Type | Description | Example Value |
| :--- | :--- | :--- | :--- |
| `message_id` | `str` | Discord message ID | `"123456789012345678"` |
| `channel_id` | `str` | Discord channel ID | `"987654321098765432"` |
| `author` | `str` | Username of author | `"hachh"` |
| `category` | `str` | RAG category | `"Documentation"` |
| `title` | `str` | Document title | `"Guide Architecture"` |
| `timestamp` | `str` | Creation timestamp | `"2026-07-24 19:44:00"` |
| `has_attachment` | `bool` | True if attachment present | `True` |
| `attachment_name` | `str \| None` | Filename of attachment | `"rapport.xlsx"` |
| `attachment_url` | `str \| None` | Discord CDN URL | `"https://cdn.discordapp.com/..."` |
| `source` | `str` | Origin of text chunk | `"attachment"` or `"message_body"` |
| `file_type` | `str` | Extended file category | `"spreadsheet"`, `"word"`, `"presentation"`, `"code"`, `"csv"`, `"json"`, `"html"`, `"pdf"`, `"text"`, `"image"` |
| `file_ext` | `str` | Normalized file extension | `".xlsx"`, `".docx"`, `".pptx"`, `".py"`, `".csv"`, `".pdf"`, etc. |
| `chunk_index` | `int` | Index of chunk (0-based) | `0` |
| `total_chunks` | `int` | Total number of chunks | `4` |
| `page_or_sheet_count`| `int \| None`| Slide/sheet/page count | `3` (3 sheets/slides) |

### 6.2 Filtering Helper in `services/vectorstore.py`
Add search filtering support to `VectorStore.query()`:

```python
def query(
    self,
    query_embedding: list[float],
    query_text: str = "",
    n_results: int = TOP_K,
    file_ext_filter: str | None = None,
    file_type_filter: str | None = None,
) -> dict[str, Any]:
    # Builds Qdrant FilterSelector matching metadata.file_ext or metadata.file_type
```

---

## 7. Comprehensive Testing Plan

Two dedicated test suites will validate Requirement R2:
1. `tests/test_extended_parsers.py` (Unit Tests)
2. `tests/test_qdrant_indexing.py` (Integration Tests)

### 7.1 Unit Tests (`tests/test_extended_parsers.py`)

| Test Case | Target Format | Verification Objective |
| :--- | :--- | :--- |
| `test_extract_docx_paragraphs_and_tables` | `.docx` | Verify headings converted to `#`, tables rendered as Markdown tables. |
| `test_extract_xlsx_multi_sheet` | `.xlsx` | Verify sheet headers (`--- Feuille: Sheet1 ---`) and row cell formatting. |
| `test_extract_pptx_slides_and_notes` | `.pptx` | Verify slide titles, text boxes, and speaker notes extracted. |
| `test_extract_csv_table_formatting` | `.csv` | Verify delimiter detection, header row, and Markdown table output. |
| `test_extract_markdown_preservation` | `.md` | Verify headers, lists, and code blocks preserved without corruption. |
| `test_extract_code_python` | `.py` | Verify language block ` ```python ` wrapping and line header. |
| `test_extract_code_javascript` | `.js` | Verify language block ` ```javascript ` wrapping. |
| `test_extract_code_css` | `.css` | Verify language block ` ```css ` wrapping. |
| `test_extract_json_formatting` | `.json` | Verify valid JSON re-formatted with indent 2 inside ` ```json `. |
| `test_extract_html_stripping_and_structure` | `.html` | Verify `<script>`/`<style>` stripped, headings & text preserved. |
| `test_extract_corrupted_file_handling` | All formats | Pass arbitrary invalid bytes to each extractor; verify returns `None` without unhandled crash. |
| `test_extract_empty_file_handling` | All formats | Pass 0-byte stream; verify graceful `None` or empty return. |

### 7.2 Integration Tests (`tests/test_qdrant_indexing.py`)

| Test Case | Verification Objective |
| :--- | :--- |
| `test_extended_document_indexing_pipeline` | Index sample `.docx`, `.xlsx`, `.pptx`, `.py`, `.csv` attachments via `IndexerCog` logic. Verify document text chunks created and pushed to Qdrant vector store. |
| `test_qdrant_payload_metadata_schema` | Inspect Qdrant stored points. Verify payload contains `file_type`, `file_ext`, `source`, `chunk_index`, `total_chunks`, `page_or_sheet_count`. |
| `test_qdrant_hybrid_search_extended_formats` | Execute hybrid search query targeting indexed spreadsheet / code data. Verify RRF retrieval returns relevant chunks with accurate metadata. |
| `test_qdrant_delete_by_metadata_extension` | Call `vector_store.delete_by_metadata("file_ext", ".xlsx")`. Verify only `.xlsx` points are purged. |

---

## 8. Implementation Guidance for Worker Agent

When implementing Milestone 2 (R2):

1. **Update `requirements.txt`**: Add `python-docx`, `openpyxl`, `python-pptx`, `pandas`, `beautifulsoup4`.
2. **Update `services/attachments.py`**:
   - Add new extractor helper functions (`_extract_text_from_docx`, `_extract_text_from_xlsx`, `_extract_text_from_pptx`, `_extract_text_from_csv`, `_extract_text_from_markdown`, `_extract_text_from_code`, `_extract_text_from_json`, `_extract_text_from_html`).
   - Enhance `extract_text_from_attachment()` to dispatch to appropriate extractors based on file extension and return structured payload info.
   - Implement graceful error logging for corrupt files.
3. **Update `services/chunker.py`**:
   - Update `_split_text_recursive` separators list to include structural delimiters (`--- `, `# `, ` ``` `).
4. **Update `services/vectorstore.py`**:
   - Ensure payload stores all enhanced metadata fields.
   - Add optional filtering parameters (`file_ext_filter`, `file_type_filter`) to `query()`.
5. **Update `cogs/indexer.py`**:
   - Construct and pass complete metadata schema during document indexing.
6. **Implement Test Suites**:
   - Write `tests/test_extended_parsers.py` (with synthetic file builders for docx, xlsx, pptx, csv, md, code, json, html).
   - Write `tests/test_qdrant_indexing.py` (for end-to-end integration and Qdrant payload verification).
