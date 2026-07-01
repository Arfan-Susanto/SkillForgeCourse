# ====================================================================
# SUPPORT RAG (Retrieval-Augmented Generation) SYSTEM
# ====================================================================
# Sistem AI Customer Service SkillForge yang menggunakan RAG:
# 1. RETRIEVAL: Cari dokumen relevan dari knowledge base
# 2. AUGMENTATION: Tambahkan dokumen ke prompt sebagai context
# 3. GENERATION: Panggil AI (Gemini/DeepSeek/Botcahx) dengan context
#
# Flow:
#   User Question → Expand Query → Retrieve Documents (Qdrant/TF-IDF)
#   → Build Prompt with Context → Call AI Provider → Return Answer
#
# Knowledge Base disimpan di Qdrant (vector database) dengan
# embedding semantic (sentence_transformers) untuk search akurat.
# ====================================================================

import os
import re
from collections import Counter
from math import log
from html import unescape
from uuid import uuid5, NAMESPACE_URL

import requests

from .models import SupportKnowledgeDocument


# ====================================================================
# CONFIGURATION: API Keys & Environment Settings
# ====================================================================
# Gemini API (Google) - digunakan jika SUPPORT_AI_PROVIDER = "gemini"
GEMINI_API_URL = os.getenv(
    "GEMINI_API_URL",
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
)
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")  # Model Gemini yang digunakan
GEMINI_TIMEOUT_SECONDS = int(os.getenv("GEMINI_TIMEOUT_SECONDS", "120"))  # Timeout Gemini API (detik)

# Botcahx API (Free AI) - alternative jika Gemini kuota habis
BOTCAHX_API_URL = os.getenv("BOTCAHX_API_URL", "https://api.botcahx.eu.org/api/search/gpt")
BOTCAHX_TIMEOUT_SECONDS = int(os.getenv("BOTCAHX_TIMEOUT_SECONDS", "120"))  # Timeout Botcahx API

# DeepSeek API - alternative AI provider
DEEPSEEK_API_URL = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/chat/completions")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# Pilih provider: "gemini", "deepseek", "botcahx", atau "auto" (auto-select dari API key)
SUPPORT_AI_PROVIDER = os.getenv("SUPPORT_AI_PROVIDER", "").strip().lower()

# ====================================================================
# QDRANT CONFIGURATION (Vector Database untuk Knowledge Base)
# ====================================================================
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "skillforge_support_kb")  # Nama collection di Qdrant
QDRANT_EMBEDDING_MODEL = os.getenv("QDRANT_EMBEDDING_MODEL", "intfloat/multilingual-e5-small")  # Model embedding multilingual

# Global cache untuk embedding model dan Qdrant client (untuk performa)
_EMBEDDING_MODEL = None  # Cached SentenceTransformer model
_QDRANT_CLIENT = None  # Cached QdrantClient instance
_QDRANT_SYNC_SIGNATURE = None  # Last synced knowledge signature (untuk check perubahan data)


# ====================================================================
# TEXT PROCESSING HELPERS
# ====================================================================

def _strip_html_and_markdown(text: str) -> str:
    # Bersihkan HTML tags, markdown code blocks, dan spasi berlebih
    # Digunakan untuk clean knowledge base content sebelum disimpan/display
    cleaned = unescape(text or "")  # Unescape HTML entities (&nbsp; → spasi, dll)
    cleaned = re.sub(r"```[\s\S]*?```", lambda match: match.group(0).strip("`\n"), cleaned)  # Remove markdown code blocks
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)  # Remove HTML tags
    cleaned = re.sub(r"\s+", " ", cleaned)  # Normalize whitespace
    return cleaned.strip()


def _plain_support_message(text: str, fallback: str = "") -> str:
    # Konversi text ke plain text, atau gunakan fallback jika kosong
    cleaned = _strip_html_and_markdown(text)
    return cleaned or fallback


def _tokenize(text: str) -> list[str]:
    # Pecah text menjadi tokens (kata-kata) untuk TF-IDF lexical search
    # Hanya alphanumeric, lowercase, untuk consistency
    return re.findall(r"[a-zA-Z0-9_]+", (text or "").lower())


def _normalize_embedding_text(text: str, mode: str = "passage") -> str:
    # Tambahkan prefix "query:" atau "passage:" untuk embedding model
    # Ini penting untuk Sentence Transformers multilingual model
    # "query:" digunakan saat encode user question
    # "passage:" digunakan saat encode dokumen di knowledge base
    cleaned = (text or "").strip()
    if mode == "query":
        return f"query: {cleaned}"
    return f"passage: {cleaned}"


# ====================================================================
# EMBEDDING MODEL (Sentence Transformers untuk Semantic Search)
# ====================================================================
# Model ini mengkonversi text → vector dengan dimensi 384
# Dokumen & query dalam vector space yang sama → bisa cari semantic similarity
# Model: intfloat/multilingual-e5-small (support Bahasa Indonesia + multilingual)

def _get_embedding_model():
    # Load & cache embedding model (SentenceTransformer)
    # Lazy loading: hanya load saat pertama kali dipakai
    global _EMBEDDING_MODEL

    if _EMBEDDING_MODEL is not None:
        return _EMBEDDING_MODEL  # Return cached model

    # Import SentenceTransformer library (optional dependency)
    try:
        from sentence_transformers import SentenceTransformer
    except Exception:
        return None  # Tidak installed → return None, fallback ke lexical search

    try:
        # Load multilingual embedding model
        # Size: ~384 dimensional vectors
        model = SentenceTransformer(QDRANT_EMBEDDING_MODEL)
    except Exception:
        return None  # Model download gagal

    _EMBEDDING_MODEL = model
    return _EMBEDDING_MODEL


def _embed_texts(texts: list[str], mode: str = "passage") -> list[list[float]]:
    # Konversi list of texts → list of vectors
    # Setiap text → vector 384-dimensi
    model = _get_embedding_model()
    if model is None:
        return []  # Model tidak tersedia

    # Normalize texts dengan prefix "query:" atau "passage:"
    prepared_texts = [_normalize_embedding_text(text, mode=mode) for text in texts]
    try:
        # Encode texts to vectors (normalized to unit length)
        embeddings = model.encode(prepared_texts, normalize_embeddings=True, show_progress_bar=False)
    except Exception:
        return []  # Encoding error

    # Convert numpy array to list of lists
    if hasattr(embeddings, "tolist"):
        embeddings = embeddings.tolist()

    return [list(vector) for vector in embeddings]


def _qdrant_client_kwargs() -> dict | None:
    # Build Qdrant client kwargs dari environment variables
    # Return None jika tidak ada config valid
    url = os.getenv("QDRANT_URL", "").strip()
    host = os.getenv("QDRANT_HOST", "").strip()
    port = os.getenv("QDRANT_PORT", "").strip()
    api_key = os.getenv("QDRANT_API_KEY", "").strip()
    prefer_grpc = os.getenv("QDRANT_PREFER_GRPC", "false").strip().lower() == "true"
    check_compatibility_env = os.getenv("QDRANT_CHECK_COMPATIBILITY", "").strip().lower()

    if check_compatibility_env == "false":
        check_compatibility = False
    elif check_compatibility_env == "true":
        check_compatibility = True
    else:
        # Default: skip compatibility check untuk Qdrant
        check_compatibility = False

    kwargs: dict = {}
    if url:
        # QDRANT_URL dapat berupa cloud endpoint atau local URL
        kwargs["url"] = url
    elif host:
        # QDRANT_HOST/PORT untuk self-hosted Qdrant
        kwargs["host"] = host
        kwargs["port"] = int(port or "6333")
    else:
        return None  # Tidak ada config valid

    if api_key:
        kwargs["api_key"] = api_key
    if prefer_grpc:
        kwargs["prefer_grpc"] = True
    if check_compatibility is False:
        kwargs["check_compatibility"] = False
    return kwargs


# ====================================================================
# RAG STATUS CHECK - Apakah RAG system siap digunakan?
# ====================================================================

def get_support_rag_status() -> tuple[bool, str]:
    # Check apakah SUPPORT_RAG_ENABLED=true dan Qdrant config valid
    # Return (is_enabled: bool, status_message: str)
    enabled = os.getenv("SUPPORT_RAG_ENABLED", "false").strip().lower() == "true"
    if not enabled:
        return False, "SUPPORT_RAG_ENABLED tidak diset ke true."

    qdrant_kwargs = _qdrant_client_kwargs()
    if qdrant_kwargs is None:
        return False, "Konfigurasi Qdrant tidak valid. Pastikan QDRANT_URL cloud terisi dan bukan localhost, atau set QDRANT_HOST/QDRANT_PORT dengan benar."

    return True, "ready"


def is_support_rag_enabled() -> bool:
    # Quick check: apakah RAG enabled?
    enabled, _ = get_support_rag_status()
    return enabled


def _get_qdrant_client():
    # Get & cache Qdrant client (cloud atau local)
    # Return None jika tidak tersedia atau error
    global _QDRANT_CLIENT

    if _QDRANT_CLIENT is not None:
        return _QDRANT_CLIENT  # Return cached client

    client_kwargs = _qdrant_client_kwargs()
    if not client_kwargs:
        return None  # Local mode atau config invalid

    try:
        # Import Qdrant client library (optional dependency)
        from qdrant_client import QdrantClient
    except Exception:
        return None  # qdrant-client library tidak installed

    try:
        # Connect ke cloud atau local Qdrant dengan kwargs
        _QDRANT_CLIENT = QdrantClient(**client_kwargs)
    except Exception:
        return None  # Connection error

    return _QDRANT_CLIENT


# ====================================================================
# KNOWLEDGE BASE LOADING & CHUNKING
# ====================================================================
# Knowledge base disimpan di SupportKnowledgeDocument model
# Dokumen besar dipecah menjadi chunks kecil (~600 karakter) untuk embedding

def _active_document_rows() -> list[dict]:
    # Ambil semua dokumen aktif dari database
    # Return: [{'id': 1, 'title': '...', 'content': '...', 'source_url': '...', 'updated_at': ...}, ...]
    return list(
        SupportKnowledgeDocument.objects.filter(is_active=True).values(
            "id",
            "title",
            "content",
            "source_url",
            "updated_at",
        )
    )


def _build_chunk_records(doc_rows: list[dict]) -> list[dict]:
    # Pecah dokumen menjadi chunks untuk embedding
    # Setiap chunk ~ 600 karakter dengan overlap 120 karakter
    # Overlap mencegah informasi penting terpotong di tengah chunk
    # Return: [{'doc_id': 1, 'title': '...', 'source_url': '...', 'chunk_index': 0, 'text': '...'}, ...]
    chunk_records = []
    for doc in doc_rows:
        # _chunk_text() memecah doc content menjadi chunks
        for idx, chunk in enumerate(_chunk_text(doc["content"])):
            chunk_records.append(
                {
                    "doc_id": doc["id"],
                    "title": doc["title"],
                    "source_url": doc["source_url"],
                    "chunk_index": idx,  # Urutan chunk dalam dokumen
                    "text": chunk,  # Isi chunk
                }
            )
    return chunk_records


def _knowledge_signature(doc_rows: list[dict]) -> str:
    # Create signature dari knowledge base (jumlah dokumen + last updated time)
    # Digunakan untuk check: apakah knowledge base berubah?
    # Jika signature sama, tidak perlu re-sync ke Qdrant (hemat waktu)
    count = len(doc_rows)
    latest = None
    for doc in doc_rows:
        updated_at = doc.get("updated_at")
        if updated_at and (latest is None or updated_at > latest):
            latest = updated_at
    latest_value = latest.isoformat() if latest else ""
    return f"{count}:{latest_value}"


def _ensure_qdrant_collection(vector_size: int):
    # Create collection di Qdrant jika belum ada
    # atau verify vector size matching (embedding model dimension)
    # Return client jika success, atau None jika error
    client = _get_qdrant_client()
    if client is None:
        return None

    try:
        from qdrant_client.http import models as qdrant_models
    except Exception:
        return None

    try:
        # Check apakah collection sudah ada
        collection_info = client.get_collection(QDRANT_COLLECTION)
    except Exception:
        # Collection belum ada, create dengan vector size dari embedding model
        try:
            client.create_collection(
                collection_name=QDRANT_COLLECTION,
                vectors_config=qdrant_models.VectorParams(
                    size=vector_size,  # 384 untuk multilingual-e5-small
                    distance=qdrant_models.Distance.COSINE  # Cosine distance untuk semantic similarity
                ),
            )
        except Exception:
            return None
        return client

    # Verify vector size matching
    existing_size = None
    try:
        vectors_config = collection_info.config.params.vectors
        if hasattr(vectors_config, "size"):
            existing_size = vectors_config.size
    except Exception:
        existing_size = None

    # Error jika vector size tidak cocok (model embedding berbeda)
    if existing_size is not None and int(existing_size) != int(vector_size):
        raise RuntimeError(
            f"Qdrant collection '{QDRANT_COLLECTION}' memakai vector size {existing_size}, "
            f"sementara model embedding menghasilkan size {vector_size}. Gunakan collection baru atau samakan model."
        )

    return client


# ====================================================================
# SYNC KNOWLEDGE BASE TO QDRANT (Main RAG Synchronization)
# ====================================================================
# Proses:
# 1. Load active documents dari database
# 2. Pecah dokumen → chunks
# 3. Embed chunks dengan SentenceTransformer → vectors
# 4. Upload vectors + metadata ke Qdrant collection
# 5. Catat signature (untuk detect perubahan data)
#
# Dipanggil saat:
# - First time retrieve knowledge
# - Admin update knowledge base
# - Periodic sync (force=True)

def sync_support_knowledge_to_qdrant(force: bool = False) -> int:
    # Sync knowledge base dari database ke Qdrant vector DB
    # Return: jumlah chunks yang di-upload (0 jika skip/error)
    global _QDRANT_SYNC_SIGNATURE

    client = _get_qdrant_client()
    model = _get_embedding_model()
    if client is None or model is None:
        return 0  # Qdrant atau embedding model tidak tersedia

    # Load dokumen aktif dari database
    doc_rows = _active_document_rows()
    if not doc_rows:
        return 0

    # Check apakah knowledge base berubah dibanding last sync
    signature = _knowledge_signature(doc_rows)
    if not force and _QDRANT_SYNC_SIGNATURE == signature:
        return 0  # Skip sync: data tidak berubah

    # Pecah dokumen menjadi chunks kecil
    chunk_records = _build_chunk_records(doc_rows)
    if not chunk_records:
        _QDRANT_SYNC_SIGNATURE = signature
        return 0

    # Embed semua chunks ke vectors dengan Sentence Transformers
    # mode="passage" → fokus embedding dokumen knowledge base
    vectors = _embed_texts([chunk["text"] for chunk in chunk_records], mode="passage")
    if not vectors:
        return 0  # Embedding gagal

    # Ensure collection di Qdrant ada dengan vector size yang tepat
    qdrant_client = _ensure_qdrant_collection(len(vectors[0]))
    if qdrant_client is None:
        return 0

    try:
        from qdrant_client.http import models as qdrant_models
    except Exception:
        return 0

    # Build PointStruct untuk setiap chunk (data + vector)
    points = []
    for chunk, vector in zip(chunk_records, vectors):
        # Generate unique ID dari doc_id + chunk_index
        points.append(
            qdrant_models.PointStruct(
                id=str(uuid5(NAMESPACE_URL, f"skillforge-support:{chunk['doc_id']}:{chunk['chunk_index']}")),  # Deterministic ID
                vector=vector,  # 384-dimensional vector
                payload={  # Metadata untuk retrieve nanti
                    "doc_id": chunk["doc_id"],
                    "title": chunk["title"],
                    "source_url": chunk["source_url"],
                    "chunk_index": chunk["chunk_index"],
                    "text": chunk["text"],  # Actual content untuk display
                },
            )
        )

    # Upload points ke Qdrant dalam batch (64 per batch untuk efisiensi)
    # upsert = update jika exist, insert jika baru
    try:
        batch_size = 64
        for start in range(0, len(points), batch_size):
            qdrant_client.upsert(collection_name=QDRANT_COLLECTION, points=points[start : start + batch_size])
    except Exception:
        return 0

    # Update signature: next sync skip jika data tidak berubah
    _QDRANT_SYNC_SIGNATURE = signature
    return len(points)  # Return jumlah chunks yang di-upload


# ====================================================================
# SEMANTIC SEARCH WITH QDRANT (Vector-based Retrieval)
# ====================================================================
# Menggunakan embedding vector untuk semantic similarity search
# Query di-embed ke vector, cari vectors paling mirip di Qdrant
# Lebih akurat untuk semantic matching dibanding keyword matching

def _retrieve_knowledge_context_qdrant(query: str, max_chunks: int = 4) -> list[dict]:
    # Retrieve relevant knowledge chunks menggunakan vector similarity
    # Return: [{'doc_id': 1, 'title': '...', 'source_url': '...', 'chunk_index': 0, 'text': '...'}, ...]
    client = _get_qdrant_client()
    model = _get_embedding_model()
    if client is None or model is None:
        return []  # Qdrant atau embedding model tidak tersedia

    doc_rows = _active_document_rows()
    if not doc_rows:
        return []  # Tidak ada dokumen aktif

    try:
        # Sync knowledge ke Qdrant jika belum (atau jika data berubah)
        sync_support_knowledge_to_qdrant()
    except Exception:
        return []  # Sync error

    # Expand query + embed ke vector
    # mode="query" → prefix "query:" untuk optimal matching dengan dokumen
    query_vectors = _embed_texts([_expand_support_query(query)], mode="query")
    if not query_vectors:
        return []  # Embedding error

    try:
        # Search di Qdrant: cari top-N vectors paling mirip dengan query
        # with_payload=True → return metadata (text, title, etc)
        results = client.search(
            collection_name=QDRANT_COLLECTION,
            query_vector=query_vectors[0],  # Vector dari query yang sudah di-embed
            limit=max_chunks,  # Return top-N results
            with_payload=True,  # Include payload (metadata) dalam results
        )
    except Exception:
        return []  # Search error

    # Extract text + metadata dari search results
    chunk_records = []
    for result in results:
        payload = result.payload or {}
        text = payload.get("text", "")
        if not text:
            continue
        chunk_records.append(
            {
                "doc_id": payload.get("doc_id"),
                "title": payload.get("title", "Tanpa judul"),
                "source_url": payload.get("source_url", ""),
                "chunk_index": payload.get("chunk_index", 0),
                "text": text,  # Actual content untuk di-inject ke AI prompt
            }
        )

    return chunk_records


# ====================================================================
# QUERY EXPANSION - Tambah synonym untuk improve search
# ====================================================================
# Strategy: Jika user tanya "pwd", expand ke "password reset login akun"
# Lebih banyak tokens → lebih mudah match dengan dokumen

def _expand_support_query(query: str) -> str:
    # Expand user query dengan synonym/related terms
    # Contoh: "pw" → "pw password reset login masuk akun"
    # Ini improve search accuracy dengan menambah context
    tokens = _tokenize(query)
    extras: list[str] = []

    # Password-related queries
    if "pw" in tokens or "passwd" in tokens or "pass" in tokens:
        extras.extend(["password", "reset password", "login", "masuk", "akun"])
    # OTP-related queries
    if "otp" in tokens or "kode" in tokens:
        extras.extend(["one time password", "verifikasi", "login", "email"])
    # Refund-related queries
    if "refund" in tokens or "retur" in tokens:
        extras.extend(["pengembalian dana", "uang kembali", "transaksi"])
    # Course-related queries
    if "kursus" in tokens or "kelas" in tokens or "course" in tokens:
        extras.extend(["akses kursus", "my courses", "enrollment", "materi"])
    # Payment-related queries
    if "bayar" in tokens or "payment" in tokens or "transaksi" in tokens:
        extras.extend(["status pembayaran", "invoice", "checkout"])
    # Profile-related queries
    if "profil" in tokens or "profile" in tokens or "akun" in tokens:
        extras.extend(["ubah profil", "foto profil", "edit akun"])
    # Certificate-related queries
    if "sertifikat" in tokens or "certificate" in tokens:
        extras.extend(["kelulusan", "completion", "lulus kursus"])

    if not extras:
        return query.strip()  # No expansion needed

    # Return expanded query dengan original + synonyms
    return f"{query.strip()} {' '.join(extras)}"


# ====================================================================
# TEXT CHUNKING - Pecah dokumen besar jadi chunks kecil
# ====================================================================
# Kenapa chunks? Embedding model punya token limit ~512 tokens (~2000 chars)
# Dokumen besar harus dipecah agar fit dalam embedding model
# Overlap mencegah informasi hilang di boundary chunks

def _chunk_text(text: str, chunk_size: int = 600, overlap: int = 120) -> list[str]:
    # Pecah text besar menjadi chunks kecil (~600 karakter)
    # overlap=120 karakter untuk ensure context continuity
    # Contoh:
    # - Chunk 1: "...karakter 0-600..."  (0:600)
    # - Chunk 2: "...karakter 480-1080..."  (480:1080, overlap 120)
    # - Chunk 3: "...karakter 960-1560..."  (960:1560, overlap 120)
    cleaned = (text or "").strip()
    if not cleaned:
        return []

    chunks = []
    start = 0
    while start < len(cleaned):
        end = min(len(cleaned), start + chunk_size)
        chunks.append(cleaned[start:end])
        if end == len(cleaned):
            break
        start = max(0, end - overlap)  # Move start back by overlap amount untuk next chunk
    return chunks


# ====================================================================
# LEXICAL SEARCH WITH TF-IDF (Fallback jika Vector Search Gagal)
# ====================================================================
# TF-IDF = Term Frequency-Inverse Document Frequency
# Strategy: Score chunks berdasarkan keyword match + importance
# TF (Term Frequency): Berapa kali term muncul di chunk?
# IDF (Inverse Document Frequency): Seberapa unik/penting term ini?
# Score = TF * IDF (term umum = score rendah, term spesifik = score tinggi)
#
# Fallback ketika:
# - sentence_transformers tidak installed
# - Qdrant tidak tersedia/error

def _retrieve_knowledge_context_lexical(query: str, max_chunks: int = 4) -> list[dict]:
    # Retrieve menggunakan TF-IDF keyword matching (no vectors)
    # Less accurate than semantic search, tapi works tanpa embedding model
    doc_rows = _active_document_rows()
    if not doc_rows:
        return []

    # Build chunks dari dokumen
    chunk_records = _build_chunk_records(doc_rows)
    if not chunk_records:
        return []

    # Tokenize & expand query
    query_terms = _tokenize(_expand_support_query(query))
    if not query_terms:
        return []

    # Build DF (Document Frequency) counter
    # DF = berapa dokumen/chunks yang contain term ini?
    total_chunks = len(chunk_records)
    df_counter = Counter()  # {term: count}
    tokenized_chunks = []  # list of tokenized chunk

    for rec in chunk_records:
        terms = _tokenize(rec["text"])
        tokenized_chunks.append(terms)
        # Update: unique terms dalam chunk ini
        df_counter.update(set(terms))

    # Score setiap chunk dengan TF-IDF
    scored = []
    for rec, terms in zip(chunk_records, tokenized_chunks):
        if not terms:
            continue
        tf_counter = Counter(terms)  # TF = term frequency dalam chunk ini
        score = 0.0
        # Untuk setiap query term, hitung TF-IDF score
        for qt in query_terms:
            tf = tf_counter.get(qt, 0)  # Berapa kali qt muncul di chunk?
            if not tf:
                continue
            # IDF = log((total_chunks + 1) / (df + 1)) + 1
            # Semakin rendah DF, semakin tinggi IDF (term lebih unik/penting)
            idf = log((1 + total_chunks) / (1 + df_counter.get(qt, 0))) + 1
            # Accumulate score: TF * IDF
            score += tf * idf
        if score > 0:
            scored.append((score, rec))

    # Sort by score descending, ambil top-N
    scored.sort(key=lambda item: item[0], reverse=True)
    return [rec for _, rec in scored[:max_chunks]]


# ====================================================================
# DEDUPLICATION - Remove duplicate chunks
# ====================================================================
# Bisa jadi Qdrant return multiple chunks dari dokumen/chunk yang sama
# Dedupe berdasarkan (title, source_url, chunk_index)

def _dedupe_context_chunks(context_chunks: list[dict]) -> list[dict]:
    # Remove duplicate chunks berdasarkan (title, source_url, chunk_index)
    # Unique key = (title, url, index) → jika sama, considered duplicate
    seen = set()
    unique_chunks = []

    for chunk in context_chunks:
        # Create unique key dari chunk metadata
        key = (chunk.get("title", ""), chunk.get("source_url", ""), chunk.get("chunk_index", 0))
        if key in seen:
            continue  # Skip: sudah ada
        seen.add(key)
        unique_chunks.append(chunk)

    return unique_chunks


# ====================================================================
# MAIN RETRIEVAL FUNCTION - Coba Qdrant dulu, fallback ke TF-IDF
# ====================================================================

def retrieve_knowledge_context(query: str, max_chunks: int = 4) -> list[dict]:
    # Main entry point untuk retrieve knowledge base
    # Strategy: Try Qdrant (vector) first, fallback to lexical (TF-IDF)
    # Return: Top-N relevant chunks [{'title': '...', 'text': '...', 'source_url': '...', ...}]
    
    # Check apakah RAG enabled?
    if not is_support_rag_enabled():
        return []  # RAG disabled, return empty

    cleaned_query = (query or "").strip()
    if not cleaned_query:
        return []  # Empty query

    # Try vector-based search dengan Qdrant (semantic)
    # Lebih akurat, tapi perlu embedding model + Qdrant running
    qdrant_results = _retrieve_knowledge_context_qdrant(cleaned_query, max_chunks=max_chunks)
    if qdrant_results:
        return qdrant_results  # Success: return vector search results

    # Fallback: TF-IDF lexical search (no embedding model required)
    # Less accurate tapi always works
    return _retrieve_knowledge_context_lexical(cleaned_query, max_chunks=max_chunks)


def _format_history_for_prompt(history_messages: list[dict] | None) -> str:
    formatted_lines = []

    for item in (history_messages or [])[-10:]:
        if not isinstance(item, dict):
            continue

        role = str(item.get("role", "")).strip().lower()
        content = str(item.get("content", "")).strip()
        if role not in {"user", "assistant"} or not content:
            continue

        label = "User" if role == "user" else "Assistant"
        formatted_lines.append(f"{label}: {content}")

    return "\n".join(formatted_lines) if formatted_lines else "Tidak ada riwayat percakapan sebelumnya."


def build_support_prompt(context_chunks: list[dict], user_message: str, history_messages: list[dict] | None = None) -> str:
    # Build system prompt untuk AI
    # Struktur:
    #   [System instruction] → Define AI behavior
    #   [Chat history] → Context dari percakapan sebelumnya
    #   [Knowledge base context] → Retrieved relevant documents
    #   [User question] → Pertanyaan terbaru
    # AI generate answer berdasarkan prompt ini
    
    # Dedupe & limit ke top-3 chunks (hemat token)
    context_chunks = _dedupe_context_chunks(context_chunks[:3])
    
    # Format retrieved chunks: [1] Title\nSource: URL\nContent: text
    context_text = "\n\n".join(
        [
            f"[{idx + 1}] Judul: {chunk['title']}\nSumber: {chunk['source_url'] or '-'}\nIsi: {chunk['text']}"
            for idx, chunk in enumerate(context_chunks)
        ]
    )
    
    # Format chat history
    history_text = _format_history_for_prompt(history_messages)

    # Build system prompt dengan instruction + history + context + question
    return (
        "Anda adalah AI Customer Service SkillForge. "  # Role definition
        "Gunakan riwayat percakapan untuk memahami lanjutan topik. "
        "Jika pertanyaan terbaru sudah berganti topik, jawab pertanyaan terbaru dan jangan memaksa topik lama. "
        "Gunakan konteks knowledge base hanya jika relevan. "
        "Balas dengan gaya yang natural dan bervariasi, jangan pakai frasa pembuka yang sama terus-menerus. "
        "Gunakan 2-4 kalimat pendek atau sedang sesuai kebutuhan jawaban. Hindari pengulangan, pengantar yang bertele-tele, dan daftar yang panjang. "
        "Jangan gunakan HTML, tag, markdown, atau blok kode. "
        "Balas sebagai teks biasa yang singkat, natural, dan langsung ke inti. "
        "Jika konteks tidak cukup, jawab singkat sesuai pertanyaan terbaru lalu minta detail tambahan yang paling relevan.\n\n"
        f"Riwayat percakapan:\n{history_text}\n\n"  # Chat context
        f"Konteks:\n{context_text or 'Tidak ada konteks.'}\n\n"  # Knowledge base context
        f"Pertanyaan pengguna:\n{user_message}\n\n"  # User question
        "Jawab sopan, natural, dan dalam Bahasa Indonesia."  # Final instruction
    )


def build_support_fallback_answer(context_chunks: list[dict], user_message: str) -> str:
    # Generate fallback answer ketika AI provider error/timeout
    # Strategy: Return knowledge base snippet instead of error
    # Less ideal than AI-generated answer, tapi tetap helpful untuk user
    
    context_chunks = _dedupe_context_chunks(context_chunks[:3])

    # Jika tidak ada context, return generic fallback
    if not context_chunks:
        return (
            "Maaf, AI sedang dibatasi sementara dan knowledge base belum menemukan konteks yang cocok. "
            "Coba kirim pertanyaan dengan detail yang lebih spesifik."
        )

    # Build snippets dari top-2 chunks
    snippets = []
    for chunk in context_chunks[:2]:
        # Clean text
        snippet = _strip_html_and_markdown(chunk.get("text", ""))
        # Truncate ke 180 chars
        if len(snippet) > 180:
            snippet = snippet[:177].rstrip() + "..."
        title = (chunk.get("title") or "Tanpa judul").strip()
        snippets.append(f"{title}: {snippet}")

    # Combine snippets jadi summary
    context_summary = " ".join(snippets)
    return (
        "Maaf, AI sedang mencapai batas penggunaan, jadi saya jawab dari knowledge base dulu. "
        f"{context_summary} "
        "Kalau kamu mau, kirim detail pertanyaan yang lebih spesifik agar saya bantu arahkan lebih tepat."
    )


def _normalize_chat_history(history_messages: list[dict] | None) -> list[dict]:
    # Normalize & validate chat history untuk AI provider
    # Ensure: dict format, valid roles (user/assistant), non-empty content
    # Keep last 20 messages (context window untuk AI)
    normalized_history = []

    for item in history_messages or []:
        if not isinstance(item, dict):
            continue

        role = str(item.get("role", "")).strip().lower()
        content = str(item.get("content", "")).strip()
        if role not in {"user", "assistant"} or not content:
            continue

        normalized_history.append({"role": role, "content": content})

    # Keep last 20 for context window
    return normalized_history[-20:]


def _build_support_conversation(system_prompt: str, history_messages: list[dict] | None, user_prompt: str) -> str:
    # Build full conversation text untuk Botcahx API
    # Format: System instruction\nUser: ...\nAssistant: ...\nUser: {latest question}\nAssistant:
    # Botcahx expects full conversation in single text block
    parts = [system_prompt.strip()] if system_prompt.strip() else []

    # Add normalized history
    for item in _normalize_chat_history(history_messages):
        prefix = "User" if item["role"] == "user" else "Assistant"
        parts.append(f"{prefix}: {item['content']}")

    # Add latest user message
    parts.append(f"User: {user_prompt}")
    # Add prompt for AI to continue
    parts.append("Assistant:")
    
    return "\n".join(parts)


# ====================================================================
# AI PROVIDER DETECTION & SELECTION
# ====================================================================
# Supported providers:
# 1. Gemini (Google) - paling reliable, tapi ada quota limit
# 2. DeepSeek - alternative, OpenAI-compatible API
# 3. Botcahx - free tier AI (fallback jika provider lain error)

def _support_ai_provider() -> str:
    # Detect mana provider yang akan dipakai
    # Priority: auto-detect dari API keys, atau dari SUPPORT_AI_PROVIDER setting
    provider = SUPPORT_AI_PROVIDER
    
    # Auto-detect mode
    if provider in {"", "auto"}:
        # Check yang mana API key yang tersedia (pilih pertama yang ada)
        if os.getenv("BOTCAHX_API_KEY", "").strip():
            return "botcahx"
        if os.getenv("DEEPSEEK_API_KEY", "").strip():
            return "deepseek"
        # Default: Gemini
        return "gemini"
    
    # Normalize provider name
    if provider in {"botcahx", "botcahx-ai", "botcahx-ai-api"}:
        return "botcahx"
    if provider in {"deepseek", "deepseek-ai", "openai-compatible", "openai"}:
        return "deepseek"
    
    return provider  # Return as-is (expected to be "gemini" atau valid provider)


def _support_ai_error_message(provider_name: str, response: requests.Response | None = None, fallback: str = "") -> str:
    # Build human-readable error message dari AI provider response
    # Untuk logging & debugging
    if response is None:
        return fallback or f"{provider_name} mengembalikan respons yang tidak valid."

    # Extract content-type header
    content_type = response.headers.get("content-type", "")
    # Preview response body (first 300 chars)
    preview = _plain_support_message(response.text[:300], fallback="kosong")
    base_message = fallback or f"{provider_name} mengembalikan respons yang tidak valid."
    return f"{base_message} (content-type: {_plain_support_message(content_type, fallback='unknown') or 'unknown'}). Preview: {preview}"


# ====================================================================
# BOTCAHX API PROVIDER - Free tier AI
# ====================================================================
# Botcahx: Free API untuk text generation
# Return format: JSON dengan "answer" / "result" / "response" field
# API docs: https://botcahx.eu.org/

def _extract_botcahx_text(data) -> str:
    # Extract text answer dari Botcahx response
    # Botcahx bisa return berbagai format, handle semuanya:
    # - String direct
    # - List of strings/dicts
    # - Dict dengan berbagai key names (answer/result/response/data/etc)
    
    if isinstance(data, str):
        # Direct string response
        answer = data.strip()
        if answer:
            return _strip_html_and_markdown(answer)
        raise RuntimeError("Respons Botcahx kosong.")

    if isinstance(data, list):
        # Array response: extract text dari setiap item
        text_parts = []
        for item in data:
            if isinstance(item, str):
                text_parts.append(item)
            elif isinstance(item, dict):
                # Try berbagai key names
                for key in ("answer", "result", "response", "message", "text", "content"):
                    value = item.get(key)
                    if value:
                        text_parts.append(str(value))
                        break
        answer = "".join(text_parts).strip()
        if answer:
            return _strip_html_and_markdown(answer)
        raise RuntimeError("Respons Botcahx tidak memiliki konten jawaban.")

    if not isinstance(data, dict):
        raise RuntimeError("Format respons Botcahx tidak dikenali.")

    # Dict response: try berbagai key names
    for key in ("answer", "result", "response", "message", "text", "content", "data"):
        value = data.get(key)
        if not value:
            continue
        if isinstance(value, dict):
            # Nested dict: recursively extract
            nested = _extract_botcahx_text(value)
            if nested:
                return nested
        elif isinstance(value, list):
            # Array value: recursively extract
            nested = _extract_botcahx_text(value)
            if nested:
                return nested
        else:
            # Simple value: return
            answer = str(value).strip()
            if answer:
                return _strip_html_and_markdown(answer)

    raise RuntimeError("Respons Botcahx tidak memiliki konten jawaban.")


def _looks_like_botcahx_example_response(data) -> bool:
    # Check apakah response adalah example response (API key belum set)
    # Botcahx return example response jika API key invalid
    if not isinstance(data, dict):
        return False

    # Check status = false
    if data.get("status") is not False:
        return False

    # Check message contains "example" atau "apikey"
    message = str(data.get("message", "")).lower()
    return "example" in message or "masukan parameter apikey" in message or "apikey" in message


def _call_botcahx_chat(system_prompt: str, user_prompt: str, history_messages: list[dict] | None = None) -> str:
    # Call Botcahx API untuk generate answer
    # Botcahx: Free AI provider dengan flexible API
    # Return: Generated text answer
    
    # Check API key
    api_key = os.getenv("BOTCAHX_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("BOTCAHX_API_KEY belum diatur pada environment.")

    # Get config dari env
    api_url = os.getenv("BOTCAHX_API_URL", BOTCAHX_API_URL).strip() or BOTCAHX_API_URL
    timeout_seconds = int(os.getenv("BOTCAHX_TIMEOUT_SECONDS", str(BOTCAHX_TIMEOUT_SECONDS)))
    
    # Build conversation text
    conversation = _build_support_conversation(system_prompt, history_messages, user_prompt)

    # Try berbagai parameter names (Botcahx API might accept berbagai format)
    candidate_params = [
        {"apikey": api_key, "query": conversation},  # Try "query"
        {"apikey": api_key, "q": conversation},  # Try "q"
        {"apikey": api_key, "text": conversation},  # Try "text"
        {"apikey": api_key, "message": conversation},  # Try "message"
        {"apikey": api_key, "prompt": conversation},  # Try "prompt"
    ]

    last_error = None
    for params in candidate_params:
        try:
            # Make GET request ke Botcahx API
            response = requests.get(api_url, params=params, timeout=timeout_seconds)
        except requests.RequestException as exc:
            # Network error, try next params
            last_error = exc
            continue

        try:
            # Parse JSON response
            data = response.json()
        except ValueError:
            # Invalid JSON, try next params
            last_error = RuntimeError(_support_ai_error_message("Botcahx", response, fallback="Respons Botcahx bukan JSON yang valid."))
            continue

        # Check apakah response adalah "example" response (API key invalid)
        if _looks_like_botcahx_example_response(data):
            last_error = RuntimeError("Botcahx meminta contoh input lain atau parameter yang dipakai belum cocok.")
            continue

        # Check HTTP error status
        if response.status_code >= 400:
            message = "Botcahx mengembalikan error"
            if isinstance(data, dict):
                message = str(data.get("message") or data.get("error") or message)
            raise RuntimeError(_plain_support_message(message, fallback=f"Botcahx mengembalikan error (HTTP {response.status_code})."))

        # Try extract text dari response
        try:
            return _extract_botcahx_text(data)
        except RuntimeError as exc:
            # Extraction failed, try next params
            last_error = exc
            continue

    # All params failed
    if last_error is not None:
        raise RuntimeError(str(last_error))

    raise RuntimeError("Gagal memanggil Botcahx untuk support chat.")


# ====================================================================
# GEMINI API PROVIDER (Google)
# ====================================================================
# Gemini: Google AI dengan multimodal support
# Message format: {role: "user"|"model", parts: [{text: "..."}, ...]}
# API: generativelanguage.googleapis.com

def _build_gemini_contents(history_messages: list[dict] | None, user_prompt: str) -> list[dict]:
    # Build message structure untuk Gemini API
    # Format: [{role: "user", parts: [{text: "..."}]}, ...]
    contents = []
    
    # Add chat history
    for item in _normalize_chat_history(history_messages):
        # Gemini: user role = "user", assistant role = "model"
        role = "user" if item["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": item["content"]}]})

    # Add latest user message
    contents.append({"role": "user", "parts": [{"text": user_prompt}]})
    return contents


def _build_openai_messages(system_prompt: str, history_messages: list[dict] | None, user_prompt: str) -> list[dict]:
    # Build message structure untuk OpenAI-compatible API (DeepSeek, dll)
    # Format: [{role: "system"|"user"|"assistant", content: "..."}, ...]
    messages = [{"role": "system", "content": system_prompt}]  # System instruction

    # Add chat history
    for item in _normalize_chat_history(history_messages):
        messages.append({"role": item["role"], "content": item["content"]})

    # Add latest user message
    messages.append({"role": "user", "content": user_prompt})
    return messages


def _extract_gemini_text(data: dict) -> str:
    # Extract text answer dari Gemini API response
    # Structure: {"candidates": [{"content": {"parts": [{"text": "..."}, ...]}}]}
    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError("Respons Gemini kosong.")

    # Get first candidate
    candidate = candidates[0] if isinstance(candidates[0], dict) else {}
    content = candidate.get("content") or {}
    parts = content.get("parts") or []

    # Extract text dari parts
    text_parts = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if text:
            text_parts.append(str(text))

    # Combine text
    answer = "".join(text_parts).strip()
    if not answer:
        raise RuntimeError("Respons Gemini tidak memiliki konten jawaban.")
    return _strip_html_and_markdown(answer)


def _call_gemini_chat(system_prompt: str, user_prompt: str, history_messages: list[dict] | None = None) -> str:
    # Call Gemini API (Google) untuk generate answer
    # Return: Generated text answer
    
    # Check API key
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY belum diatur pada environment.")

    # Get model & URL dari env
    model = os.getenv("GEMINI_MODEL", GEMINI_MODEL).strip() or GEMINI_MODEL
    api_url = os.getenv("GEMINI_API_URL", GEMINI_API_URL).strip() or GEMINI_API_URL
    # Replace {model} placeholder dengan actual model name
    if "{model}" in api_url:
        api_url = api_url.format(model=model)

    # Build request payload
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},  # System prompt
        "contents": _build_gemini_contents(history_messages, user_prompt),  # Messages
        "generationConfig": {
            # Generation parameters untuk control output
            "temperature": float(os.getenv("GEMINI_TEMPERATURE", "0.9")),  # Creativity (0-1)
            "topP": float(os.getenv("GEMINI_TOP_P", "0.95")),  # Nucleus sampling
            "topK": int(os.getenv("GEMINI_TOP_K", "64")),  # Top-K sampling
            "maxOutputTokens": int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "256")),  # Max output length
        },
    }

    # Make POST request ke Gemini API
    response = requests.post(api_url, params={"key": api_key}, json=payload, timeout=GEMINI_TIMEOUT_SECONDS)

    # Parse response
    try:
        data = response.json()
    except ValueError as exc:
        content_type = response.headers.get("content-type", "")
        preview = _plain_support_message(response.text[:300], fallback="kosong")
        raise RuntimeError(
            f"Respons Gemini bukan JSON yang valid (content-type: {_plain_support_message(content_type, fallback='unknown') or 'unknown'})."
            f" Preview: {preview}"
        ) from exc

    # Validate response format
    if not isinstance(data, dict):
        raise RuntimeError("Format respons Gemini tidak dikenali.")

    # Check error field
    if data.get("error"):
        error_obj = data.get("error") or {}
        message = error_obj.get("message") if isinstance(error_obj, dict) else str(error_obj)
        raise RuntimeError(_plain_support_message(message, fallback=f"Gemini mengembalikan error (HTTP {response.status_code})."))

    # Check HTTP status
    if response.status_code >= 400:
        raise RuntimeError(f"Gemini mengembalikan error (HTTP {response.status_code}).")

    # Extract & return text
    return _extract_gemini_text(data)


# ====================================================================
# DEEPSEEK API PROVIDER (OpenAI-compatible)
# ====================================================================
# DeepSeek: Chinese AI provider dengan OpenAI-compatible API
# Response format: {"choices": [{"message": {"content": "..."}}]}

def _extract_deepseek_text(data: dict) -> str:
    # Extract text answer dari DeepSeek API response
    # Structure: {"choices": [{"message": {"content": "..."}}]}
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("Respons DeepSeek kosong.")

    # Get first choice
    choice = choices[0] if isinstance(choices[0], dict) else {}
    message = choice.get("message") or {}
    content = message.get("content")

    # Extract text dari content (bisa string atau list)
    text_parts = []
    if isinstance(content, str):
        # Simple string content
        text_parts.append(content)
    elif isinstance(content, list):
        # Array of content blocks (multimodal)
        for part in content:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if text:
                text_parts.append(str(text))
    elif content is not None:
        # Other type: convert to string
        text_parts.append(str(content))

    # Fallback: try "text" field
    if not text_parts:
        fallback_text = choice.get("text")
        if fallback_text:
            text_parts.append(str(fallback_text))

    # Combine text
    answer = "".join(text_parts).strip()
    if not answer:
        raise RuntimeError("Respons DeepSeek tidak memiliki konten jawaban.")
    return _strip_html_and_markdown(answer)


def _call_deepseek_chat(system_prompt: str, user_prompt: str, history_messages: list[dict] | None = None) -> str:
    # Call DeepSeek API (OpenAI-compatible) untuk generate answer
    # Return: Generated text answer
    
    # Check API key
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY belum diatur pada environment.")

    # Get model & URL dari env
    model = os.getenv("DEEPSEEK_MODEL", DEEPSEEK_MODEL).strip() or DEEPSEEK_MODEL
    api_url = os.getenv("DEEPSEEK_API_URL", DEEPSEEK_API_URL).strip() or DEEPSEEK_API_URL

    # Build OpenAI-compatible payload
    payload = {
        "model": model,  # Model name (e.g., "deepseek-chat")
        "messages": _build_openai_messages(system_prompt, history_messages, user_prompt),  # Messages
        "temperature": float(os.getenv("DEEPSEEK_TEMPERATURE", "0.7")),  # Creativity
        "top_p": float(os.getenv("DEEPSEEK_TOP_P", "0.95")),  # Nucleus sampling
        "max_tokens": int(os.getenv("DEEPSEEK_MAX_TOKENS", "256")),  # Max output length
    }

    # Make POST request ke DeepSeek API dengan Bearer token
    response = requests.post(
        api_url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=GEMINI_TIMEOUT_SECONDS,  # Use same timeout sebagai Gemini
    )

    # Parse response
    try:
        data = response.json()
    except ValueError as exc:
        content_type = response.headers.get("content-type", "")
        preview = _plain_support_message(response.text[:300], fallback="kosong")
        raise RuntimeError(
            f"Respons DeepSeek bukan JSON yang valid (content-type: {_plain_support_message(content_type, fallback='unknown') or 'unknown'})."
            f" Preview: {preview}"
        ) from exc

    # Validate response format
    if not isinstance(data, dict):
        raise RuntimeError("Format respons DeepSeek tidak dikenali.")

    # Check error field
    if data.get("error"):
        error_obj = data.get("error") or {}
        message = error_obj.get("message") if isinstance(error_obj, dict) else str(error_obj)
        raise RuntimeError(_plain_support_message(message, fallback=f"DeepSeek mengembalikan error (HTTP {response.status_code})."))

    # Check HTTP status
    if response.status_code >= 400:
        raise RuntimeError(f"DeepSeek mengembalikan error (HTTP {response.status_code}).")

    # Extract & return text
    return _extract_deepseek_text(data)


# ====================================================================
# MAIN CHAT FUNCTION - Dispatch ke AI Provider
# ====================================================================

def call_support_chat(system_prompt: str, user_prompt: str, history_messages: list[dict] | None = None) -> str:
    # Main entry point untuk call AI provider
    # Dispatch ke mana provider based on configuration
    # Return: Generated text answer
    
    provider = _support_ai_provider()
    if provider == "botcahx":
        return _call_botcahx_chat(system_prompt, user_prompt, history_messages=history_messages)
    if provider == "deepseek":
        return _call_deepseek_chat(system_prompt, user_prompt, history_messages=history_messages)
    # Default: Gemini
    return _call_gemini_chat(system_prompt, user_prompt, history_messages=history_messages)


def call_gemini_chat(system_prompt: str, user_prompt: str, history_messages: list[dict] | None = None) -> str:
    # Backward compatibility alias untuk call_support_chat
    # (Legacy function name)
    return call_support_chat(system_prompt, user_prompt, history_messages=history_messages)
