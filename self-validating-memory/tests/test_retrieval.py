import torch

from svmp.config import RoleConfig
from svmp.retrieval import CorpusRetriever, DocumentCorpus
from svmp.roles import Verifier


def _corpus(unreliable_frac=0.4, seed=0):
    prototypes = torch.randn(4, 8, generator=torch.Generator().manual_seed(7))
    return DocumentCorpus(prototypes, docs_per_class=10,
                          unreliable_frac=unreliable_frac, seed=seed), prototypes


def test_corpus_has_expected_size_and_mixture():
    corpus, _ = _corpus()
    assert len(corpus) == 40
    frac_reliable = float(corpus.reliable.float().mean())
    assert 0.3 < frac_reliable < 0.9  # stochastic but mixed


def test_retriever_returns_topk_with_trust():
    corpus, protos = _corpus()
    r = CorpusRetriever(corpus)
    out = r(protos[0], k=3)
    assert len(out) == 3
    for emb, trust in out:
        assert emb.shape == (8,)
        assert 0.0 <= trust <= 1.0
    assert 0.0 <= r.last_reliability <= 1.0


def test_encode_fn_projects_documents():
    corpus, protos = _corpus()
    proj = torch.nn.Linear(8, 5)
    r = CorpusRetriever(corpus, encode_fn=proj)
    out = r(proj(protos[0]).detach(), k=2)
    assert out[0][0].shape == (5,)


def test_verifier_with_real_retriever_plugs_in():
    corpus, protos = _corpus()
    cfg = RoleConfig(dim=8)
    v = Verifier(cfg, search_fn=CorpusRetriever(corpus))
    ev = v.verify(protos[1])
    assert ev.n_sources == cfg.triangulation_k
    assert 0.0 <= ev.source_quality <= 1.0


def test_fully_reliable_corpus_scores_higher_than_fully_misleading():
    # With identical machinery, an all-reliable corpus must yield higher
    # assessed quality than an all-misleading one (agreement does the work).
    cfg = RoleConfig(dim=8)
    qualities = {}
    for name, frac in [("reliable", 0.0), ("misleading", 1.0)]:
        corpus, protos = _corpus(unreliable_frac=frac, seed=3)
        v = Verifier(cfg, search_fn=CorpusRetriever(corpus))
        qs = [v.verify(protos[c]).source_quality for c in range(4)]
        qualities[name] = sum(qs) / len(qs)
    assert qualities["reliable"] > qualities["misleading"]
