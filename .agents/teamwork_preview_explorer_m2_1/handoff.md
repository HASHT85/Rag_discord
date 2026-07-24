# Handoff Report: Milestone 2 — R2 (Extended Document Format Support & Qdrant Indexing)

**Agent:** Explorer Subagent (`teamwork_preview_explorer_m2_1`)  
**Role:** Read-Only Investigator & Technical Architect  
**Target:** Milestone 2 (R2: Extended Document Format Support & Qdrant Indexing)  
**Date:** 2026-07-24  

---

## 1. Observation

1. **Current Code Base Structure & Files Examined:**
   - `services/attachments.py` (260 lines): Lines 26–29 define `_TEXT_EXTENSIONS`. Lines 151–178 contain `_extract_text_from_text_file`, which relies on plain UTF-8 / latin-1 string decoding. Lines 215–224 dispatch execution based on extension (`.pdf`, `_IMAGE_EXTENSIONS`, `_TEXT_EXTENSIONS`). Parsers for binary OpenXML formats (`.docx`, `.xlsx`, `.pptx`) are missing.
   - `services/chunker.py` (254 lines): Lines 163 defines `separators = ["\n\n", "\n", " ", ""]` in `chunk_text()`. Does not prioritize Markdown headers (`#`) or code blocks (```).
   - `services/vectorstore.py` (232 lines): Lines 85–89 construct Qdrant payload: `{"text": text, "metadata": metadata, "original_id": str(doc_id)}`.
   - `cogs/indexer.py` (329 lines): Lines 112–124 and 215–227 populate metadata dict with 11 fields (`message_id`, `channel_id`, `author`, `category`, `title`, `timestamp`, `has_attachment`, `attachment_name`, `attachment_url`, `chunk_index`, `total_chunks`). Lacks `file_type`, `file_ext`, `source`, `page_or_sheet_count`.
   - `cogs/rag.py` (433 lines): Lines 152–160 extract `attachment_url` and `attachment_name` from metadata payload.
   - `requirements.txt` (9 lines): Contains `discord.py`, `qdrant-client`, `flashrank`, `openai`, `python-dotenv`, `PyMuPDF`, `aiohttp`, `fastembed`. Lacks `python-docx`, `openpyxl`, `python-pptx`, `pandas`, `beautifulsoup4`.

2. **Environment & Dependency Diagnostics:**
   - Command: `.\venv\Scripts\python.exe -c "import fitz, qdrant_client, fastembed; print('OK')"` -> Returned `OK`.
   - Command: `.\venv\Scripts\python.exe -c "import docx, openpyxl, pptx, pandas, bs4"` -> Returned `ModuleNotFoundError` for `docx`, `openpyxl`, `pptx`, `pandas`, `bs4`.
   - Existing unit tests (`tests/test_conversation_memory.py`, `tests/test_rag_cog_memory.py`): Command `$env:PYTHONPATH="."; .\venv\Scripts\python.exe -m pytest` executed 9 passed tests in 3.35s.

---

## 2. Logic Chain

1. **Observation 1 & 2** show that binary formats (`.docx`, `.xlsx`, `.pptx`) and structured files (`.html`, `.json`) are not currently parsed with specialized libraries, causing raw UTF-8 string decoding to fail on binary files or produce unformatted noise.
2. **Observation 2** confirms that `python-docx`, `openpyxl`, `python-pptx`, `pandas`, and `beautifulsoup4` are missing from the virtual environment and `requirements.txt`. Adding these 5 dependencies will enable clean extraction for `.docx`, `.xlsx`, `.pptx`, `.csv`, `.json`, `.html`, and code files.
3. **Observation 1** shows that `services/chunker.py` uses basic separators `["\n\n", "\n", " ", ""]`. Updating separator priority to `["\n\n--- ", "\n\n# ", "\n\n```", "\n\n", "\n", " ", ""]` guarantees structural section breaks (sheet/slide dividers, Markdown headers, code block syntax) remain intact across chunk boundaries.
4. **Observation 1** shows that Qdrant metadata payload currently omits `file_type`, `file_ext`, `source`, and `page_or_sheet_count`. Enhancing `cogs/indexer.py` and `services/vectorstore.py` to index these fields enables structured metadata filtering and context display in `cogs/rag.py`.
5. Designing comprehensive unit tests (`tests/test_extended_parsers.py`) and integration tests (`tests/test_qdrant_indexing.py`) will allow verifying all 10 document formats + PDF/TXT + images, handling of corrupt files, and Qdrant payload integrity.

---

## 3. Caveats

1. **Third-Party File Dependencies:** Binary test files (`.docx`, `.xlsx`, `.pptx`) in unit tests will be created programmatically using `python-docx`, `openpyxl`, and `python-pptx` inside test fixtures rather than storing static binary files in the repository.
2. **Large Spreadsheet/Presentation Truncation:** Very large Excel files (>500 rows) or PowerPoint files (>50 slides) are capped during extraction to avoid exceeding token limits, adding a `[... X rows truncated ...]` marker.

---

## 4. Conclusion

Requirement R2 implementation is fully mapped and designed. The detailed architecture report has been written to `c:\Projet\Rag_discord\.agents\teamwork_preview_explorer_m2_1\analysis.md`.

**Action Plan for Implementer Subagent:**
1. Update `requirements.txt` with `python-docx`, `openpyxl`, `python-pptx`, `pandas`, `beautifulsoup4` and run `pip install -r requirements.txt`.
2. Implement rich extractors in `services/attachments.py` (`_extract_text_from_docx`, `_extract_text_from_xlsx`, `_extract_text_from_pptx`, `_extract_text_from_csv`, `_extract_text_from_markdown`, `_extract_text_from_code`, `_extract_text_from_json`, `_extract_text_from_html`).
3. Update `services/chunker.py` separators order.
4. Extend metadata schema in `cogs/indexer.py` and `services/vectorstore.py` (`file_type`, `file_ext`, `source`, `page_or_sheet_count`).
5. Create `tests/test_extended_parsers.py` (unit tests for 10 document formats + corruption handling) and `tests/test_qdrant_indexing.py` (integration tests for Qdrant payload and hybrid retrieval).

---

## 5. Verification Method

1. **Verify Report Deliverables:**
   - Inspect `c:\Projet\Rag_discord\.agents\teamwork_preview_explorer_m2_1\analysis.md`
   - Inspect `c:\Projet\Rag_discord\.agents\teamwork_preview_explorer_m2_1\handoff.md`

2. **Verify Execution of Existing Test Suite:**
   ```powershell
   $env:PYTHONPATH="."
   .\venv\Scripts\python.exe -m pytest
   ```
   *Expected result:* 9 passed tests.

3. **Verify Design Coverage against Requirement R2 Prompt:**
   - Check that all 10 extended formats (.docx, .xlsx, .pptx, .csv, .md, .py, .js, .json, .html, .css) are addressed.
   - Check structural cue preservation strategy.
   - Check metadata schema design for Qdrant payload.
   - Check unit and integration test plan for `tests/test_extended_parsers.py` and `tests/test_qdrant_indexing.py`.
