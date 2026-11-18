"""Acceptance input invariants through the public domain contracts."""
import unittest

from pydantic import ValidationError

from backend.app.scope.models import DecisionInput, ProjectInput, ProposalInput, proposal_digest


class ScopeWorkflowContracts(unittest.TestCase):
    def test_exact_agreement_digest_changes_for_price_scope_brief_and_evidence(self):
        project = {'project_id': 'p_one', 'brief': 'One landing page', 'brief_revision': 1}
        proposal = {'title': 'Contact form', 'description': 'Add a contact form', 'amount_minor': 12000,
                    'evidence': [{'message_id': 'm_one', 'quote': 'Please add the contact form'}]}
        original = proposal_digest(project, proposal, 1)
        for values in ({'amount_minor': 12001}, {'description': 'Add a contact form and storage'},
                       {'title': 'Contact form with storage'}, {'evidence': [{'message_id': 'm_two', 'quote': 'Different source'}]}):
            self.assertNotEqual(original, proposal_digest(project, proposal | values, 1))
        self.assertNotEqual(original, proposal_digest(project | {'brief': 'Two landing pages'}, proposal, 1))
        self.assertNotEqual(original, proposal_digest(project | {'brief_revision': 2}, proposal, 1))
        self.assertNotEqual(original, proposal_digest(project, proposal, 2))

    def test_money_requires_positive_integer_minor_units_and_usd(self):
        valid = {'name': 'Site', 'client_name': 'Alex', 'client_email': 'alex@example.test',
                 'brief': 'One landing page', 'base_amount_minor': 50000}
        self.assertEqual(ProjectInput(**valid).currency, 'usd')
        for changes in ({'base_amount_minor': True}, {'base_amount_minor': 1.5}, {'base_amount_minor': '500'},
                        {'base_amount_minor': 0}, {'base_amount_minor': -1}, {'currency': 'eur'},
                        {'client_email': 'not an email'}, {'brief': '  '}, {'brief': 'Unsafe\x00text'}):
            with self.assertRaises(ValidationError):
                ProjectInput(**(valid | changes))

    def test_client_decision_requires_explicit_value_and_exact_version_digest(self):
        valid = {'decision': 'accepted', 'name': 'Alex', 'proposal_version': 1, 'proposal_digest': 'a' * 64}
        self.assertEqual(DecisionInput(**valid).decision, 'accepted')
        for changes in ({'decision': 'maybe'}, {'decision': True}, {'name': ''}, {'proposal_version': True},
                        {'proposal_digest': 'short'}, {'consent_inferred': True}):
            with self.assertRaises(ValidationError):
                DecisionInput(**(valid | changes))

    def test_proposal_requires_source_evidence_and_paypal_compatible_description(self):
        values = {'title': 'Contact form', 'description': 'Add a contact form', 'amount_minor': 12000,
                  'evidence': [{'message_id': 'm_one', 'quote': 'Add contact form'}], 'expected_brief_revision': 1}
        ProposalInput(**values)
        for changes in ({'evidence': []}, {'description': 'a' * 1001}, {'amount_minor': 12.3}, {'title': 'a' * 121}):
            with self.assertRaises(ValidationError):
                ProposalInput(**(values | changes))


if __name__ == '__main__':
    unittest.main()
