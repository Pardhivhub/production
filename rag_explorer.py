import logging
from pathlib import Path
from typing import List, Tuple
import chromadb
from backend.config import settings
from embedder import OllamaEmbeddingFunction

logger = logging.getLogger(__name__)

class RAGExplorer:
    """
    Retrieval-Augmented Generation (RAG) Document Explorer.
    Indexes text files under a directory and allows semantic query retrieval.
    Completely unified to use local Ollama embeddings to boot instantly and run lightweight.
    """
    def __init__(self, collection_name: str = "rag_docs", persist_dir: str = "./chroma_rag"):
        self.client = chromadb.PersistentClient(path=persist_dir)
        
        # Reuse Ollama embedding function (which inherits from chromadb.EmbeddingFunction)
        self.ef = OllamaEmbeddingFunction(
            model_name="all-minilm:latest",
            url=f"{settings.OLLAMA_BASE_URL}/api/embeddings"
        )
        
        # Safe collection retrieval with automatic conflict recovery
        try:
            self.collection = self.client.get_or_create_collection(
                name=collection_name,
                embedding_function=self.ef
            )
        except Exception as e:
            logger.warning(f"Embedding function conflict/error for collection '{collection_name}': {e}. Recreating...")
            try:
                self.client.delete_collection(collection_name)
            except Exception:
                pass
            self.collection = self.client.create_collection(
                name=collection_name,
                embedding_function=self.ef
            )
        logger.info(f"RAGExplorer initialized using Ollama embeddings (persisted to {persist_dir})")

    def _load_documents(self, source_dir: str) -> List[Tuple[str, str]]:
        """Read all txt and md files from directory."""
        docs = []
        base = Path(source_dir).expanduser()
        if not base.exists():
            logger.warning(f"RAG document source directory '{source_dir}' does not exist.")
            return docs
            
        for path in base.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".txt", ".md"}:
                try:
                    content = path.read_text(encoding="utf-8").strip()
                    if content:
                        docs.append((str(path), content))
                except Exception as e:
                    logger.warning(f"Failed to read file {path}: {e}")
        logger.info(f"Loaded {len(docs)} files from {source_dir}")
        return docs

    def index_folder(self, source_dir: str):
        """Index a folder containing textual knowledge documents."""
        docs = self._load_documents(source_dir)
        if not docs:
            logger.warning("No documents found to index.")
            return
            
        ids = [doc[0] for doc in docs]
        texts = [doc[1] for doc in docs]
        
        self.collection.upsert(
            ids=ids,
            documents=texts
        )
        logger.info(f"Indexed {len(ids)} documents into Chroma collection.")

    def retrieve(self, query: str, top_k: int = 3) -> List[Tuple[str, str]]:
        """Retrieve most semantically relevant documents for the query."""
        try:
            # Query using the embedding function
            results = self.collection.query(
                query_texts=[query],
                n_results=top_k
            )
            hits = []
            if results and results.get("ids") and results["ids"][0]:
                for doc_id, doc_text in zip(results["ids"][0], results["documents"][0]):
                    hits.append((doc_id, doc_text))
            return hits
        except Exception as e:
            logger.error(f"RAG retrieval failed: {e}")
            return []
