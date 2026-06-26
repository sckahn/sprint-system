"""TDD for a REAL embedding retriever (replaces the synthetic DocumentCorpus).

EmbeddingRetriever does cosine top-k over a real document-embedding matrix and is
pluggable as Verifier(search_fn=...). It is embedding-agnostic — these tests use
small hand-built vectors (no model download). The sentence-transformer + real
text wiring lives in lazy helpers exercised by examples/experiment_real_retriever.py.

Tests written BEFORE the implementation; they must fail first.
"""
import torch

from svmp.config import RoleConfig
from svmp.real_retriever import EmbeddingRetriever, topic_centroids
from svmp.roles import Verifier


def test_retriever_returns_topk_by_cosine():
    embs = torch.tensor([[1., 0, 0], [0.9, 0.1, 0], [0, 1., 0]])
    labels = torch.tensor([0, 0, 1])
    r = EmbeddingRetriever(embs, labels)
    out = r(torch.tensor([1., 0, 0]), k=2)
    assert len(out) == 2
    assert r.last_labels.tolist() == [0, 0]          # the two +x docs
    for emb, trust in out:
        assert emb.shape == (3,)
        assert 0.0 <= trust <= 1.0


def test_score_trust_mode_orders_by_similarity():
    embs = torch.tensor([[1., 0, 0], [0.5, 0.5, 0]])
    labels = torch.tensor([0, 1])
    r = EmbeddingRetriever(embs, labels, trust_mode="score")
    out = r(torch.tensor([1., 0, 0]), k=2)
    assert out[0][1] > out[1][1]                     # closer doc ⇒ higher trust


def test_topic_centroids_shape_and_no_nan():
    torch.manual_seed(42)
    labels = torch.arange(4).repeat(5)            # exactly 5 docs per class
    embs = torch.randn(20, 8)
    c = topic_centroids(embs, labels, 4)
    assert c.shape == (4, 8)
    assert not c.isnan().any()


def test_topic_centroids_raises_on_empty_class():
    embs = torch.randn(6, 8)
    labels = torch.tensor([0, 0, 0, 1, 1, 1])     # class 2 absent
    try:
        topic_centroids(embs, labels, 3)
        assert False, "expected ValueError for an empty class"
    except ValueError:
        pass


def test_k_larger_than_corpus_is_clamped():
    embs = torch.randn(3, 8)
    labels = torch.tensor([0, 1, 2])
    r = EmbeddingRetriever(embs, labels)
    assert len(r(torch.randn(8), k=10)) == 3


def test_uniform_trust_preserves_value_and_updates_last_labels():
    embs = torch.tensor([[1., 0], [0.9, 0.1], [0., 1.]])
    labels = torch.tensor([5, 5, 7])
    r = EmbeddingRetriever(embs, labels, trust_mode="uniform", trust_value=0.42)
    out = r(torch.tensor([1., 0]), k=2)
    assert all(t == 0.42 for _, t in out)
    assert r.last_labels.tolist() == [5, 5]
    r(torch.tensor([0., 1.]), k=1)               # state updates each call
    assert r.last_labels.tolist() == [7]


def test_plugs_into_verifier():
    embs = torch.randn(30, 8)
    labels = torch.randint(0, 3, (30,))
    r = EmbeddingRetriever(embs, labels)
    cfg = RoleConfig(dim=8)
    cfg.triangulation_k = 4
    v = Verifier(cfg, search_fn=r, aggregation="robust")
    ev = v.verify(torch.randn(8))
    assert ev.embedding.shape == (8,)
    assert 0.0 <= ev.source_quality <= 1.0
