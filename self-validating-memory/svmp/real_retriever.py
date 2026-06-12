"""Real embedding retriever — a drop-in for the synthetic DocumentCorpus.

``EmbeddingRetriever`` does cosine top-k over a real document-embedding matrix and
plugs straight into ``Verifier(search_fn=...)``. It is embedding-agnostic, so the
retrieval logic is unit-tested with plain vectors (no model download).

The "real connection" — real text documents (20 Newsgroups) embedded with a real
sentence-transformer — lives in the lazy helpers ``embed_texts`` and
``load_20newsgroups`` below, which import their heavy optional dependencies only
when called. See examples/experiment_real_retriever.py for the end-to-end demo.
"""
from __future__ import annotations

import torch
import torch.nn.functional as F


class EmbeddingRetriever:
    """Cosine top-k retrieval over a fixed document-embedding corpus.

    Returns the ``list[(embedding, trust)]`` shape the Verifier's search_fn
    expects. ``trust_mode``:
      - ``"uniform"`` — every source reports the same prior (uninformative: the
        only reliability signal is cross-source coherence). This is the honest,
        hard case, since a real retriever rarely knows a source's reliability.
      - ``"score"`` — use the (cosine→[0,1]) retrieval score as the trust prior.
    """

    def __init__(self, embeddings: torch.Tensor, labels: torch.Tensor,
                 trust_mode: str = "uniform", trust_value: float = 0.6):
        if trust_mode not in ("uniform", "score"):
            raise ValueError(f"unknown trust_mode: {trust_mode}")
        self.embeddings = embeddings
        self.labels = labels
        self._norm = F.normalize(embeddings, dim=1)
        self.trust_mode = trust_mode
        self.trust_value = trust_value
        self.last_labels: torch.Tensor | None = None   # labels of the last hit set

    def __call__(self, query_emb: torch.Tensor,
                 k: int) -> list[tuple[torch.Tensor, float]]:
        q = F.normalize(query_emb.flatten(), dim=0)
        sims = self._norm @ q
        k = min(k, self.embeddings.shape[0])
        top = torch.topk(sims, k)
        idx = top.indices
        self.last_labels = self.labels[idx]
        out = []
        for i in idx:
            if self.trust_mode == "score":
                trust = float((sims[i] + 1.0) / 2.0)
            else:
                trust = self.trust_value
            out.append((self.embeddings[i], trust))
        return out


def topic_centroids(embeddings: torch.Tensor, labels: torch.Tensor,
                    n_classes: int) -> torch.Tensor:
    """Mean embedding per class — the prototypes used to score evidence."""
    return torch.stack([embeddings[labels == c].mean(0) for c in range(n_classes)])


# --- lazy "real connection" helpers (optional heavy deps) ------------------
def load_20newsgroups(categories, subset: str = "train",
                      max_per_class: int | None = None, seed: int = 0):
    """Load real newsgroup posts. Requires scikit-learn. Returns (texts, labels)."""
    from sklearn.datasets import fetch_20newsgroups

    d = fetch_20newsgroups(subset=subset, categories=list(categories),
                           remove=("headers", "footers", "quotes"),
                           random_state=seed, shuffle=True)
    texts, labels = [], []
    per_class: dict[int, int] = {}
    for text, label in zip(d.data, d.target):
        text = text.strip()
        if len(text) < 30:                      # drop near-empty posts
            continue
        label = int(label)
        if max_per_class is not None and per_class.get(label, 0) >= max_per_class:
            continue
        per_class[label] = per_class.get(label, 0) + 1
        texts.append(text)
        labels.append(label)
    return texts, torch.tensor(labels), list(d.target_names)


def embed_texts(texts, model_name: str = "all-MiniLM-L6-v2",
                batch_size: int = 64) -> torch.Tensor:
    """Embed texts with a real sentence-transformer. Requires sentence-transformers."""
    import numpy as np
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name)
    vecs = model.encode(list(texts), batch_size=batch_size,
                        show_progress_bar=False, normalize_embeddings=False)
    return torch.tensor(np.asarray(vecs), dtype=torch.float32)
