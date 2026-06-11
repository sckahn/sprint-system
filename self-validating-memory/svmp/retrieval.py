"""Real retriever for the Verifier (Phase 4: 검증 에이전트 + 자라는 창고).

Replaces the Verifier's simulated search with retrieval over an actual document
corpus. Documents carry a *source reliability* that the agent never sees
directly — it only sees a noisy trust prior (think: domain authority). Unreliable
sources return **misleading** evidence (embeddings pulled toward the wrong
class), so trusting a single source is dangerous and triangulation should pay
off. This is exactly the component the design flags as the weakest real part of
the system.
"""
from __future__ import annotations

import torch


class DocumentCorpus:
    """A synthetic-but-structured corpus over real class prototypes.

    Each document is an embedding near its class prototype. A fraction of
    documents are *unreliable*: their embedding is blended toward a different
    class (misleading evidence) and their trust prior is only slightly lower
    than reliable ones — overlapping enough that the prior alone cannot
    separate them.
    """

    def __init__(self, prototypes: torch.Tensor, docs_per_class: int = 20,
                 unreliable_frac: float = 0.4, noise: float = 0.2,
                 seed: int = 0):
        g = torch.Generator().manual_seed(seed)
        n_classes, dim = prototypes.shape
        embs, trust, reliable = [], [], []
        for c in range(n_classes):
            for _ in range(docs_per_class):
                is_reliable = float(torch.rand(1, generator=g)) >= unreliable_frac
                base = prototypes[c].clone()
                if not is_reliable:
                    # Misleading: blend toward a random *other* class.
                    other = int(torch.randint(n_classes, (1,), generator=g))
                    if other == c:
                        other = (other + 1) % n_classes
                    base = 0.4 * base + 0.6 * prototypes[other]
                emb = base + noise * torch.randn(dim, generator=g)
                # Trust priors overlap: reliability is NOT readable from the
                # prior alone — triangulation must do the work.
                mu = 0.72 if is_reliable else 0.58
                t = float(torch.clamp(
                    mu + 0.12 * torch.randn(1, generator=g), 0.05, 0.95))
                embs.append(emb)
                trust.append(t)
                reliable.append(is_reliable)
        self.embeddings = torch.stack(embs)
        self.trust_prior = torch.tensor(trust)
        self.reliable = torch.tensor(reliable)

    def __len__(self) -> int:
        return self.embeddings.shape[0]


class CorpusRetriever:
    """Cosine top-k retrieval over a DocumentCorpus.

    Pluggable as ``Verifier(search_fn=CorpusRetriever(corpus))``. Records which
    documents each call retrieved so experiments can check, post-hoc, whether
    the source-quality assessor discriminated reliable from unreliable evidence.

    The corpus lives in raw input space; if the agent queries in its learned
    encoder space, pass ``encode_fn`` so documents are projected into the same
    space at call time (the corpus is small, so this is cheap).
    """

    def __init__(self, corpus: DocumentCorpus, encode_fn=None):
        self.corpus = corpus
        self.encode_fn = encode_fn
        self.last_reliability: float = 0.0   # fraction reliable in last result

    def __call__(self, query: torch.Tensor,
                 k: int) -> list[tuple[torch.Tensor, float]]:
        embs = self.corpus.embeddings
        if self.encode_fn is not None:
            with torch.no_grad():
                embs = self.encode_fn(embs)
        q = torch.nn.functional.normalize(query.flatten(), dim=0)
        docs = torch.nn.functional.normalize(embs, dim=1)
        sims = docs @ q
        k = min(k, len(self.corpus))
        idx = torch.topk(sims, k).indices
        self.last_reliability = float(self.corpus.reliable[idx].float().mean())
        return [(embs[i], float(self.corpus.trust_prior[i])) for i in idx]
