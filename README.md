# Groww Mutual Fund FAQ Assistant (Facts-Only RAG)

> **"Accuracy Over Intelligence"**: A production-grade, compliance-first Retrieval-Augmented Generation (RAG) assistant designed for retail mutual fund inquiries across 5 curated HDFC Mutual Fund schemes. Grounded strictly in official Scheme Information Documents (SIDs), factsheets, and Groww disclosures.

---

## 1. System Overview & Core Philosophy

Retail mutual fund investors require **factual certitude**, not speculative AI commentary or unauthorized financial advice. Under SEBI and AMFI regulatory frameworks, delivering inaccurate figures (such as incorrect expense ratios or misstated exit loads) or offering unauthorized investment recommendations carries severe regulatory liability.

This system is engineered around **deterministic perimeter defense** and **grounded hybrid retrieval**:

```
[ User Query ]
       │
       ▼
[ Stage 1: Input Guardrails ]  ──► (PII Detected) ───────► Block & Sanitize (0 LLM cost)
       │                        ──► (Advisory / Speculative)─► Refusal + AMFI Link (0 LLM cost)
       ▼ (Factual Query)
[ Stage 2: Hybrid Retrieval ]
   ├── Dense Search: ChromaDB (BAAI/bge-small-en-v1.5, Cosine Similarity)
   └── Sparse Search: Rank-BM25 (Finance-aware tokenization)
       │
       ▼
   [ RRF Merger (k=60) ] ──► Top-3 Context Chunks + Groww Provenance URL
       │
       ▼
[ Stage 3: LLM Generation ] ──► Groq Cloud (Llama 3.3 70B Versatile, Temp=0.0)
       │
       ▼
[ Stage 4: Output Guardrails ]
   ├── Sentence Length Enforcer (Strictly <= 3 sentences)
   ├── Citation Whitelist & Single-Link Enforcer (Exactly 1 Groww link)
   └── Mandatory Recency Line Appender (Last updated: 2026-11-15)
       │
       ▼
[ Compliant Response Card in Dark-Theme UI ]
```

---

## 2. Curated Schemes & Scope

The assistant provides verified factual coverage for **5 HDFC Mutual Fund schemes**:

| Scheme Name | Category | Primary Identifier | Verified Groww Factsheet URL |
| :--- | :--- | :--- | :--- |
| **HDFC Flexi Cap Fund Direct-Growth** | Equity: Flexi Cap | `hdfc-flexi-cap` | [groww.in/mutual-funds/hdfc-equity-fund-direct-growth](https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth) |
| **HDFC Balanced Advantage Fund Direct-Growth** | Hybrid: Dynamic Asset Allocation | `hdfc-balanced-advantage` | [groww.in/mutual-funds/hdfc-balanced-advantage-fund-direct-growth](https://groww.in/mutual-funds/hdfc-balanced-advantage-fund-direct-growth) |
| **HDFC Large and Mid Cap Fund Direct-Growth** | Equity: Large & Mid Cap | `hdfc-large-and-mid-cap` | [groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth](https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth) |
| **HDFC Silver ETF FoF Direct-Growth** | Commodities: Silver FoF | `hdfc-silver-etf-fof` | [groww.in/mutual-funds/hdfc-silver-etf-fof-direct-growth](https://groww.in/mutual-funds/hdfc-silver-etf-fof-direct-growth) |
| **HDFC Manufacturing Fund Direct-Growth** | Equity: Thematic / Sectoral | `hdfc-manufacturing` | [groww.in/mutual-funds/hdfc-manufacturing-fund-direct-growth](https://groww.in/mutual-funds/hdfc-manufacturing-fund-direct-growth) |

---

## 3. Key Architectural Modules

### A. Input Guardrails & Intent Router (`src/guardrails/`)
- **PII Filter**: Intercepts Indian PAN cards (`[A-Z]{5}[0-9]{4}[A-Z]`), 12-digit Aadhaar numbers, mobile numbers, and 9–18 digit mutual fund folios. Sanitizes queries with zero credential logging.
- **Intent Classifier**: High-precision deterministic regex rules evaluate queries in $< 1$ms.
  - **Refused**: Advisory inquiries (*"Should I buy?"*, *"Is Roshi Jain the best manager?"*), return speculations (*"Will returns exceed 20%?"*), and comparative rankings (*"Which fund is better?"*).
  - **Permitted**: Factual inquiries on Expense Ratio (TER), Exit Loads, Fund Managers, Minimum SIP/Lumpsum limits, Lock-in periods, Riskometers, and Benchmark indices.
  - **Refusal Action**: Intercepted at the perimeter with $0$ LLM tokens spent, returning the statutory AMFI investor education reference.

### B. Hybrid Retrieval Engine (`src/retrieval/`)
- **Dense Vector Search**: ChromaDB persistent vector database powered by `BAAI/bge-small-en-v1.5` embeddings (384-dimensional normalized vectors).
- **Sparse Lexical Search**: BM25 with financial acronym tokenization (`TER`, `SIP`, `AUM`, currency signs `₹`, percentage decimals).
- **Reciprocal Rank Fusion (RRF)**: Merges dense and sparse ranks with constant $k=60$, ensuring high resilience against vocabulary mismatch.
- **Scheme Entity Resolver**: Dynamically isolates the retrieval scope when a specific fund is mentioned in the query.

### C. Factual Generation Engine (`src/pipeline/`)
- **LLM Client**: Groq Cloud API running `llama-3.3-70b-versatile` (or `llama-3.1-8b-instant`) at temperature $0.0$.
- **Strict Grounding Prompt**: System instructions mandate that all claims must be directly cited from context chunks. Out-of-corpus queries fall back deterministically to standard missing-records messaging.

### D. Output Guardrails & Compliance Validation (`src/guardrails/output_guard.py`)
- **Sentence Length Enforcer**: Custom regex protects financial decimals (`0.75%`), currency abbreviations (`Rs. 500`), honorifics (`Mr.`), and internal terms (`p.a.`, `i.e.`). Truncates answers to $\le 3$ complete sentences.
- **Citation Whitelist & Single-Link**: Validates links against authorized domains (`groww.in`, `hdfcfund.com`, `amfiindia.com`, `sebi.gov.in`). Strips third-party blogs and guarantees exactly one citation link in final output.
- **Recency Line Appender**: Enforces the mandatory `Last updated from sources: <YYYY-MM-DD>` footer, overriding any hallucinated dates.

### E. Custom Dark-Theme Web UI (`src/ui/`)
- **Obsidian FinTech Design**: Groww Teal (`#00D09C`), Deep Canvas (`#0B0D12`), Card Surfaces (`#121620`), Crisp Borders (`#232B3B`).
- **Chat-First Customer Experience**: Clean conversation feed, welcoming empty-state with 4 starter prompt chips, typing animation, copy-to-clipboard, and sources chunk inspector.
- **Zero Streamlit**: Powered by an asynchronous Python REST API server (`aiohttp.web`) serving static HTML/JS/CSS on `http://127.0.0.1:8000`.

---

## 4. Quickstart & Installation

### Prerequisites
- Python 3.9+ (tested on macOS / Linux)
- Git

### 1. Clone & Set Up Virtual Environment
```bash
git clone https://github.com/your-username/rag-chatbot.git
cd "RAG Chatbot"

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Create a `.env` file in the project root:
```ini
# LLM Configuration (Groq Cloud Free Tier)
LLM_PROVIDER=groq
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=llama-3.3-70b-versatile

# ChromaDB & Embeddings
CHROMA_PERSIST_DIR=chroma_db
EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
CHROMA_COLLECTION_NAME=hdfc_mutual_funds
```

### 3. Build Vector & BM25 Indices (One-time ETL) & Scheduler
```bash
# Ingest and build persistent dense & sparse indices from scraped corpus
python3 -m src.ingestion.scheduler --run-now

# Optional: Run persistent daily ingestion daemon at 10:00 AM IST (Asia/Kolkata)
python3 -m src.ingestion.scheduler --schedule --hour 10 --minute 0 --timezone Asia/Kolkata
```
> **Automated Cloud Scheduler**: A GitHub Actions workflow (`.github/workflows/daily_scheduler.yml`) runs this ingestion automatically every day at **10:00 AM IST** (`30 4 * * *` UTC), tests the pipeline, and uploads fresh corpus artifacts. You can also trigger it manually anytime via **GitHub Actions -> Daily Mutual Fund Ingestion Scheduler -> Run workflow**.


### 4. Start Web Application Server (Local)
```bash
python3 -m src.ui.server --port 8000
```
Open **[http://localhost:8000](http://localhost:8000)** in your web browser.

### 5. Free 1-Click Cloud Deployment (Render / Railway)
To share this bot publicly over HTTPS without any containers or complex DevOps:
1. Push this repository to GitHub.
2. Go to **[Render.com](https://render.com)** -> Create **New Web Service** -> Connect your GitHub repo.
3. Configure the service:
   - **Environment**: `Python 3`
   - **Build Command**: `pip install --no-cache-dir -r requirements.txt`
   - **Start Command**: `python -m src.ui.server`
   - **Environment Variables**: Add `GROQ_API_KEY` (and `LLM_PROVIDER=groq`).
4. Click **Deploy Web Service** -> Your bot is live on a free public HTTPS URL (e.g. `https://groww-mf-faq.onrender.com`)!

---

## 5. REST API Reference

The asynchronous server exposes clean REST endpoints:

### `POST /api/chat`
Processes a question through the guarded RAG pipeline.
```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the exit load for HDFC Balanced Advantage Fund?"}'
```
**Response JSON**:
```json
{
  "query": "What is the exit load for HDFC Balanced Advantage Fund?",
  "answer": "For redemption within 1 year from the date of allotment, an exit load of 1.0% applies to units in excess of 15% of the investment. No exit load is charged for redemption after 1 year.",
  "intent": "FACTUAL",
  "is_refusal": false,
  "is_fallback": false,
  "citation_url": "https://groww.in/mutual-funds/hdfc-balanced-advantage-fund-direct-growth",
  "last_updated_date": "2026-11-15",
  "confidence_score": 0.985,
  "latency_ms": 142.3,
  "retrieved_chunks_count": 3
}
```

### `GET /api/schemes`
Returns the 5 active HDFC schemes and mandatory regulatory disclaimer.

### `GET /api/health`
System telemetry endpoint returning vector store document counts and latest crawl timestamp.

---

## 6. Automated Testing & Evaluation Suite

The repository includes comprehensive unit, integration, and evaluation suites covering:
- **PII & Intent Guardrails**: 26 adversarial and opinion prompts validating 0% false negative rates.
- **Retrieval Precision**: Top-3 RRF accuracy across all 5 schemes.
- **Output Compliance**: Sentence length ($\le 3$), domain whitelisting, and recency overrides.
- **UI API Endpoints**: In-memory HTTP mock tests for CORS, static serving, and JSON validation.

Run the test suite:
```bash
.venv/bin/pytest -v tests/
```

**Result**:
```
============================== 85 passed in 8.80s ==============================
```

---

## 7. Regulatory & Compliance Notice

> **Mandatory Disclosure**: *Mutual fund investments are subject to market risks. Please read all scheme-related documents carefully before investing. Groww MF FAQ Assistant provides factual data extracted from official Scheme Information Documents (SIDs) and does not provide financial, legal, or investment advice. For investor education, visit [AMFI India](https://www.amfiindia.com/investor-corner/knowledge-center).*
