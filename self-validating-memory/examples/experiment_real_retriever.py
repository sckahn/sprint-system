"""Phase 4 — REAL retrieval: 20 Newsgroups text + sentence-transformer + cosine.

This replaces the synthetic DocumentCorpus with a genuinely real pipeline:
  • real documents   : 20 Newsgroups posts (4 semantically-close sci.* topics)
  • real embeddings  : sentence-transformer all-MiniLM-L6-v2 (384-d)
  • real retrieval   : cosine top-k via svmp.real_retriever.EmbeddingRetriever
  • real supervision : the query post's true topic (for training + scoring)

Queries come from the *test* subset and retrieve against the *train* subset, so
there is no self-match. Trust priors are uniform (uninformative) — the only
reliability signal is cross-source coherence. We compare mean / robust / learned
aggregation on evidence accuracy (does the aggregated evidence land on the true
topic centroid?), and report how benign/adversarial real retrieval actually is.

    pip install sentence-transformers scikit-learn
    PYTHONPATH=. OMP_NUM_THREADS=1 python examples/experiment_real_retriever.py

Embeddings are cached under .cache/ so re-runs are fast.
"""
from __future__ import annotations

import os

import torch
import torch.nn.functional as F

from svmp.config import RoleConfig
from svmp.real_retriever import (
    EmbeddingRetriever,
    embed_texts,
    load_20newsgroups,
    topic_centroids,
)
from svmp.roles import Verifier, train_trust_estimator

# Two real regimes: distinct topics (benign retrieval) vs confusable topics
# (adversarial retrieval — semantic neighbours are often the wrong topic).
DISTINCT = ["sci.space", "rec.sport.baseball", "talk.politics.guns", "comp.graphics"]
CONFUSABLE = ["comp.sys.ibm.pc.hardware", "comp.sys.mac.hardware",
              "comp.os.ms-windows.misc", "comp.windows.x"]
K = 5
CACHE = os.path.join(os.path.dirname(__file__), ".cache")


def _embed_cached(texts, tag):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"{tag}.pt")
    if os.path.exists(path):
        emb = torch.load(path)
        # Guard against a stale cache (e.g. max_per_class changed): the row count
        # must match the freshly loaded texts or labels/embeddings desync.
        if emb.shape[0] != len(texts):
            raise RuntimeError(
                f"stale embedding cache at {path}: {emb.shape[0]} rows vs "
                f"{len(texts)} texts — delete examples/.cache/ and re-run")
        return emb
    emb = embed_texts(texts)
    torch.save(emb, path)
    return emb


def build(categories, tag):
    corpus_texts, corpus_labels, names = load_20newsgroups(
        categories, subset="train", max_per_class=500)
    q_texts, q_labels, _ = load_20newsgroups(
        categories, subset="test", max_per_class=300)
    corpus_emb = F.normalize(_embed_cached(corpus_texts, f"{tag}_corpus"), dim=1)
    q_emb = F.normalize(_embed_cached(q_texts, f"{tag}_queries"), dim=1)
    return corpus_emb, corpus_labels, q_emb, q_labels, names


def _episodes(retr, q_emb, q_lab):
    eps = []
    for e, l in zip(q_emb, q_lab):
        res = retr(e, K)
        embs = torch.stack([x for x, _ in res])
        tr = torch.tensor([t for _, t in res])
        eps.append((embs, tr, int(l)))
    return eps


def _evidence_acc(retr, protos, q_emb, q_lab, aggregation, est=None):
    cfg = RoleConfig(dim=protos.shape[1])
    cfg.triangulation_k = K
    v = Verifier(cfg, search_fn=retr, aggregation=aggregation, trust_estimator=est)
    c = 0
    for e, l in zip(q_emb, q_lab):
        ev = v.verify(e)
        c += int(int(torch.cdist(ev.embedding.unsqueeze(0), protos).argmin()) == int(l))
    return c / len(q_lab)


def run(categories, tag, label):
    corpus_emb, corpus_labels, q_emb, q_labels, names = build(categories, tag)
    protos = topic_centroids(corpus_emb, corpus_labels, len(names))
    retr = EmbeddingRetriever(corpus_emb, corpus_labels, trust_mode="uniform")

    coh = []
    for e, l in zip(q_emb, q_labels):
        retr(e, K)
        coh.append(float((retr.last_labels == int(l)).float().mean()))
    on_topic = sum(coh) / len(coh)

    # Stratified train/eval split so class balance can't confound the comparison.
    from sklearn.model_selection import train_test_split
    tr_idx, ev_idx = train_test_split(range(len(q_labels)), test_size=0.5,
                                      stratify=q_labels.numpy(), random_state=0)
    tr_idx, ev_idx = torch.tensor(tr_idx), torch.tensor(ev_idx)
    train_eps = _episodes(retr, q_emb[tr_idx], q_labels[tr_idx])
    # temperature=0.5: embeddings are unit-normalized here, so squared-L2 ∈ [0,4]
    # (vs ~[0,40] for the synthetic norm-4 protos where the 8.0 default fits).
    est = train_trust_estimator(train_eps, protos, epochs=15, temperature=0.5)
    ev_emb, ev_lab = q_emb[ev_idx], q_labels[ev_idx]
    mean = _evidence_acc(retr, protos, ev_emb, ev_lab, "mean")
    robust = _evidence_acc(retr, protos, ev_emb, ev_lab, "robust")
    learned = _evidence_acc(retr, protos, ev_emb, ev_lab, "learned", est=est)

    print(f"\n[{label}]  topics={names}")
    print(f"  corpus={len(corpus_labels)} queries={len(q_labels)} k={K}  "
          f"top-{K} on-topic={on_topic:.3f} (1.0=benign, 0.25=chance)")
    print(f"  evidence acc:  mean={mean:.3f}  robust={robust:.3f}  learned={learned:.3f}"
          f"   (learned−mean={learned - mean:+.3f}, learned−robust={learned - robust:+.3f})")


def main():
    print("=" * 72)
    print("Phase 4 REAL retrieval — 20 Newsgroups + MiniLM + cosine top-k")
    print("=" * 72)
    run(DISTINCT, "distinct", "DISTINCT topics — benign retrieval expected")
    run(CONFUSABLE, "confusable", "CONFUSABLE topics — adversarial retrieval expected")


if __name__ == "__main__":
    main()
