# Testing — TDD, isolation, synthetic state

## TDD mandate

Write tests **first**, derived from the phase's "done when" (see the §11 slice).
Red → green → refactor. No production code without a failing test that describes it.
The `test-writer` subagent produces the tests from the acceptance criteria before
implementation begins.

## Isolation

Each of the three parts is tested **alone**, using synthetic Payloads at its
boundary — never by standing up the other parts. Mock the boundary (the Payload),
not the internals.

## Synthetic state only

- All fixtures, sample emails, and sample documents are **synthetic**. Never real NPI (Rule 5). No real SSN, bank detail, or client document in a test, ever.
- Tests must not send real email, and must not call the Anthropic API against real data.

## The slice acceptance test (§11 "done when")

The MVP is done when, on **synthetic** data:

1. A synthetic email carrying a signed CA contract hits the dedicated deal address.
2. The TC confirms the new deal — **nothing commits without that confirmation.**
3. Fields extract with confidence scores.
4. The TC confirms them.
5. A timeline built from **human-verified** CA rules appears.
6. A lender follow-up is drafted.
7. A real email sends **only** after human approval.
8. Every step is written to the audit log, and there is **no auto-send path anywhere in the codebase.**
