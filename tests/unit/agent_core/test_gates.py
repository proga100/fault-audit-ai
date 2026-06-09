"""Tests for faultaudit/agent/gates.py — GateMachine state machine"""

from __future__ import annotations

import pytest

from faultaudit.models import ApprovalDecision, ApprovalGate, FlaggedItem, FlaggedReason
from faultaudit.agent.gates import GateMachine, GateMachineError


def make_item(invoice_id: str = "i1") -> FlaggedItem:
    return FlaggedItem(
        invoice_id=invoice_id,
        vendor_name="Test Corp",
        department="Finance",
        amount=5000.0,
        reasons=[FlaggedReason.POLICY_VIOLATION],
        detail="test detail",
    )


def approve_plan_decision(edited_plan: str | None = None) -> ApprovalDecision:
    return ApprovalDecision(
        gate=ApprovalGate.PLAN,
        approved=True,
        edited_plan=edited_plan,
    )


def reject_plan_decision() -> ApprovalDecision:
    return ApprovalDecision(gate=ApprovalGate.PLAN, approved=False)


def approve_action_decision(*ids: str) -> ApprovalDecision:
    return ApprovalDecision(
        gate=ApprovalGate.ACTION,
        approved=True,
        approved_ids=list(ids),
    )


def reject_action_decision() -> ApprovalDecision:
    return ApprovalDecision(gate=ApprovalGate.ACTION, approved=False)


class TestGateMachineHappyPath:
    def test_initial_state_is_planning(self):
        gm = GateMachine("r1")
        assert gm.status == "planning"

    def test_submit_plan_transitions_to_awaiting_plan(self):
        gm = GateMachine("r1")
        gm.submit_plan("Audit May invoices")
        assert gm.status == "awaiting_plan"

    def test_approve_plan_transitions_to_executing(self):
        gm = GateMachine("r1")
        gm.submit_plan("Audit May invoices")
        gm.approve_plan(approve_plan_decision())
        assert gm.status == "executing"

    def test_plan_text_stored(self):
        gm = GateMachine("r1")
        gm.submit_plan("My plan text")
        gm.approve_plan(approve_plan_decision())
        assert gm.plan == "My plan text"

    def test_edited_plan_replaces_original(self):
        gm = GateMachine("r1")
        gm.submit_plan("Original plan")
        gm.approve_plan(approve_plan_decision(edited_plan="Revised plan"))
        assert gm.plan == "Revised plan"

    def test_propose_transitions_to_awaiting_action(self):
        gm = GateMachine("r1")
        gm.submit_plan("plan")
        gm.approve_plan(approve_plan_decision())
        gm.propose([make_item("i1"), make_item("i2")])
        assert gm.status == "awaiting_action"

    def test_proposed_items_stored(self):
        gm = GateMachine("r1")
        gm.submit_plan("plan")
        gm.approve_plan(approve_plan_decision())
        gm.propose([make_item("i1"), make_item("i2")])
        ids = [item.invoice_id for item in gm.proposed_items]
        assert "i1" in ids and "i2" in ids

    def test_approve_action_transitions_to_writing(self):
        gm = GateMachine("r1")
        gm.submit_plan("plan")
        gm.approve_plan(approve_plan_decision())
        gm.propose([make_item("i1")])
        gm.approve_action(approve_action_decision("i1"))
        assert gm.status == "writing"

    def test_approve_action_returns_approved_ids(self):
        gm = GateMachine("r1")
        gm.submit_plan("plan")
        gm.approve_plan(approve_plan_decision())
        gm.propose([make_item("i1"), make_item("i2")])
        approved = gm.approve_action(approve_action_decision("i1"))
        assert approved == ["i1"]

    def test_complete_transitions_to_done(self):
        gm = GateMachine("r1")
        gm.submit_plan("plan")
        gm.approve_plan(approve_plan_decision())
        gm.propose([make_item("i1")])
        gm.approve_action(approve_action_decision("i1"))
        gm.complete()
        assert gm.status == "done"

    def test_approved_ids_property_after_approval(self):
        gm = GateMachine("r1")
        gm.submit_plan("plan")
        gm.approve_plan(approve_plan_decision())
        gm.propose([make_item("i1"), make_item("i2")])
        gm.approve_action(approve_action_decision("i1", "i2"))
        assert set(gm.approved_ids) == {"i1", "i2"}


class TestGateMachineRejections:
    def test_reject_plan_goes_to_done(self):
        gm = GateMachine("r1")
        gm.submit_plan("plan")
        gm.approve_plan(reject_plan_decision())
        assert gm.status == "done"

    def test_reject_action_goes_to_done(self):
        gm = GateMachine("r1")
        gm.submit_plan("plan")
        gm.approve_plan(approve_plan_decision())
        gm.propose([make_item("i1")])
        gm.approve_action(reject_action_decision())
        assert gm.status == "done"

    def test_empty_approved_ids_goes_to_done(self):
        gm = GateMachine("r1")
        gm.submit_plan("plan")
        gm.approve_plan(approve_plan_decision())
        gm.propose([make_item("i1")])
        approved = gm.approve_action(ApprovalDecision(
            gate=ApprovalGate.ACTION,
            approved=True,
            approved_ids=[],  # empty
        ))
        assert gm.status == "done"
        assert approved == []


class TestGateMachineInvalidTransitions:
    def test_submit_plan_wrong_state(self):
        gm = GateMachine("r1")
        gm.submit_plan("plan")  # now awaiting_plan
        with pytest.raises(GateMachineError):
            gm.submit_plan("another plan")  # can't submit again

    def test_approve_plan_from_planning(self):
        gm = GateMachine("r1")
        with pytest.raises(GateMachineError):
            gm.approve_plan(approve_plan_decision())

    def test_propose_from_planning(self):
        gm = GateMachine("r1")
        with pytest.raises(GateMachineError):
            gm.propose([make_item("i1")])

    def test_approve_action_from_executing(self):
        gm = GateMachine("r1")
        gm.submit_plan("plan")
        gm.approve_plan(approve_plan_decision())
        # We're in executing, not awaiting_action
        with pytest.raises(GateMachineError):
            gm.approve_action(approve_action_decision("i1"))

    def test_complete_from_awaiting_action(self):
        gm = GateMachine("r1")
        gm.submit_plan("plan")
        gm.approve_plan(approve_plan_decision())
        gm.propose([make_item("i1")])
        with pytest.raises(GateMachineError):
            gm.complete()

    def test_submit_plan_empty_text_raises(self):
        gm = GateMachine("r1")
        with pytest.raises(GateMachineError):
            gm.submit_plan("")

    def test_submit_plan_whitespace_only_raises(self):
        gm = GateMachine("r1")
        with pytest.raises(GateMachineError):
            gm.submit_plan("   ")

    def test_no_operations_after_done(self):
        gm = GateMachine("r1")
        gm.submit_plan("plan")
        gm.approve_plan(reject_plan_decision())  # -> done
        with pytest.raises(GateMachineError):
            gm.submit_plan("new plan")
