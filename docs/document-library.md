# Document library

The Documents page (`/documents`) provides category navigation, tags, a personal For You collection, organization-public files, a private administrator collection, uploads, filename/full-text/semantic search, original downloads, and extracted-text reading with page/slide/sheet references.

## Visibility

- PRIVATE is the default: uploader, the employee linked to the document through `employees.user_id`, and authorized oversight roles.
- PUBLIC means authenticated members of the same organization, never an anonymous internet link.
- SUPER_PRIVATE can only be set by a superuser or a role with `documents.admin`, using Documents settings. Only the administrator who applies it can access the file, even if another user uploaded it. Other administrators and the employee subject cannot bypass it.
- `documents.read_all` reads ordinary private documents; it does not override Super Private. Existing HR document, equipment document, inventory management, project update, and leave approval permissions provide category-specific oversight. Category names are used for display; see the access service for the explicit permission mapping.
- Source file lists, downloads, catalog facets, extracted text, semantic results, and document-linked audit events apply document visibility. Project report metrics remain visible while unauthorized attachments are hidden.
- Profile pictures, client logos, inventory photos and asset photo/video media retain their existing behavior.

## Storage and indexing

Postgres stores document metadata, ownership, visibility, tags, extraction state, text and referenced chunks. Existing document-bearing records are registered idempotently at application startup. SQLAlchemy transaction hooks register subsequent uploads and invalidate indexes when a source file changes. Direct document uploads are private. Inventory import CSV originals are retained for new imports.

A background worker polls durable PENDING rows. PostgreSQL row locks with SKIP LOCKED coordinate workers, and a crash rolls the job back to PENDING. Text extraction and model inference run off the event loop. Failed or unsupported documents remain downloadable, with a clear status and a reindex action. Existing corrupt PDFs require valid replacements; no fabricated text is indexed.

Supported extraction: text, Markdown, CSV, JSON, HTML/XML, PDF, DOCX, XLS/XLSX, PPTX, RTF and OpenDocument files. Images and image-only PDF pages use local OCR. Arbitrary other formats are accepted as downloads, but unsupported binary formats do not have searchable body text. Password-protected files need an unlocked copy. Extraction is bounded to 300 PDF pages, 2 million text characters, 20,000 spreadsheet rows per sheet, and 100 MB decompressed Office archives.

FAISS IndexFlatIP indexes normalized 384-dimensional BGE-small embeddings from FastEmbed. Index files are written atomically per document below `.document-index/<organization-id>/`. Set DOCUMENT_INDEX_DIR to a persistent private disk location in deployment; all API/worker processes must share that disk. The model downloads once into the index directory. Document content is processed locally, not sent to an embedding API. The implementation follows [FAISS index persistence](https://github.com/facebookresearch/faiss/wiki/Index-IO%2C-cloning-and-hyper-parameter-tuning).

Search fuses PostgreSQL full-text/metadata ranks with semantic document ranks and returns a best matching passage. Only authorized document indexes are opened. File metadata remains searchable when extraction is pending or unsupported. Metadata/category/tag edits are immediately reflected without rebuilding content vectors.

Production Supabase storage uses a separate private `<bucket>-documents` bucket. Startup moves existing document objects out of the public media bucket before serving requests. Photos and logos stay in the original bucket. Migration failures stop startup instead of exposing a public fallback. Private file downloads go through authenticated API responses; the library never returns public storage URLs.

## Setup

Install project dependencies, run `alembic upgrade head`, and restart the API. Startup backfills existing uploads and starts the index worker. Preserve Postgres, uploaded files and DOCUMENT_INDEX_DIR in backups. Local migration and initial indexing were run during implementation. Test environments do not start the background worker automatically.

Legacy files without a recoverable uploader are visible to their employee subject and oversight roles, rather than assigning an invented owner. External document links that were never uploaded are not downloaded or indexed automatically. Historical inventory preview CSVs were not retained by the old platform and cannot be recreated as original files.
