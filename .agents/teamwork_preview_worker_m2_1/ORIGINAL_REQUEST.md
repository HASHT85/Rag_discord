## 2026-07-24T17:45:28Z
You are a Worker subagent assigned to implement Requirement R2 (Extended Document Format Support & Qdrant Indexing) for the Discord Multimodal RAG project.

Your working directory for metadata/reports is: c:\Projet\Rag_discord\.agents\teamwork_preview_worker_m2_1

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Your Tasks:
1. Dependencies:
   - Add `python-docx`, `openpyxl`, `python-pptx`, `pandas`, `beautifulsoup4` to `requirements.txt`.
   - Run `venv\Scripts\pip.exe install -r requirements.txt` (or install dependencies into virtual environment).

2. Implement Rich Document Extractors in `services/attachments.py`:
   - `.docx`: `_extract_text_from_docx` using `docx.Document` (extract paragraphs and tables).
   - `.xlsx`: `_extract_text_from_xlsx` using `openpyxl` (extract sheet names, headers, rows).
   - `.pptx`: `_extract_text_from_pptx` using `pptx.Presentation` (extract slide numbers, titles, text shapes).
   - `.csv`: `_extract_text_from_csv` using `csv.reader` (format structured table rows).
   - `.md`: `_extract_text_from_markdown` (preserve headers and list structure).
   - Code files (`.py`, `.js`, `.css`): wrap with syntax language code blocks ` ```lang ... ``` `.
   - `.json`: `_extract_text_from_json` (pretty-printed formatted JSON string).
   - `.html`: `_extract_text_from_html` using `BeautifulSoup` (extract readable text from HTML body).
   - Update file extension routing map in `extract_text_from_attachment` / `extract_attachment_content`.

3. Update `services/chunker.py`:
   - Update separator list to `separators = ["\n\n--- ", "\n\n# ", "\n\n```", "\n\n", "\n", " ", ""]` to prevent splitting code blocks, headings, or sheet dividers.

4. Update `cogs/indexer.py` and `services/vectorstore.py`:
   - Include metadata fields (`file_type`, `file_ext`, `source`, `page_or_sheet_count`, `attachment_name`, `attachment_url`, `chunk_index`, `total_chunks`) when creating vector payload.

5. Implement Comprehensive Test Suite:
   - `tests/test_extended_parsers.py`: Unit tests generating dynamic test files (.docx, .xlsx, .pptx, .csv, .md, .py, .js, .json, .html, .css) and verifying text extraction content, structure, and corrupt file error handling.
   - `tests/test_qdrant_indexing.py`: Integration tests verifying Qdrant chunk payload construction and metadata completeness.

6. Verification:
   - Execute `venv\Scripts\python.exe -m py_compile bot.py cogs/indexer.py services/attachments.py services/chunker.py services/vectorstore.py`
   - Execute `venv\Scripts\python.exe -m pytest -v tests/`
   - Ensure all tests pass.

7. Write report to `c:\Projet\Rag_discord\.agents\teamwork_preview_worker_m2_1\changes.md` and `handoff.md` and send a message back to parent.
