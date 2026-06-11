from svmp.budget import BudgetEconomy
from svmp.config import BudgetConfig


def test_maintenance_tightens_over_rounds():
    b = BudgetEconomy(BudgetConfig(maintenance_base=1.0, maintenance_growth=0.5))
    assert b.maintenance_cost == 1.0
    b.tick()
    assert b.maintenance_cost == 1.5
    b.tick()
    assert b.maintenance_cost == 2.0


def test_passive_agent_dies():
    # No earning, only maintenance: budget must eventually hit zero.
    b = BudgetEconomy(BudgetConfig(total=10.0, maintenance_base=1.0,
                                   maintenance_growth=0.0))
    for _ in range(20):
        b.tick()
    assert not b.alive
    assert b.balance <= 0


def test_reward_pays_back_into_budget():
    b = BudgetEconomy(BudgetConfig(total=100.0, reward_to_budget=4.0))
    start = b.balance
    b.earn(2.0)
    assert b.balance == start + 8.0


def test_operation_costs_deduct():
    cfg = BudgetConfig(total=100.0, cost_inference=1.0, cost_search=6.0,
                       cost_expert=0.5)
    b = BudgetEconomy(cfg)
    b.spend("inference")
    b.spend("search")
    b.spend_experts(3)
    assert b.balance == 100.0 - 1.0 - 6.0 - 1.5
