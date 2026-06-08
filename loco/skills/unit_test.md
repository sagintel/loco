---
name: unit_test
description: Generate exhaustive, production-grade test suites that catch every category of defect — logical errors, boundary violations, race conditions, security flaws, algorithmic bugs, and regression traps. Use this skill when the user asks to write tests, add test coverage, verify correctness, or when any generated code needs validation. Tests must prove correctness, not merely demonstrate usage.
---

This skill generates test suites that a principal engineer would trust to gate a production deployment. Tests are not documentation — they are executable proofs of correctness. Every test must have a clear hypothesis, a precise assertion, and a reason to exist.

## Testing Philosophy

**Tests exist to catch bugs. A test that cannot fail is worthless. A test that fails for the wrong reason is dangerous.**

Before writing any test:
- **Understand the Contract**: What does this function/module promise? What are its preconditions, postconditions, and invariants?
- **Understand the Failure Modes**: How can this code break? What inputs cause it to lie, crash, corrupt data, or leak resources?
- **Understand the Blast Radius**: If this code is wrong, what downstream systems are affected? Tests should validate the integration boundaries, not just internal logic.

## Test Design Process (Mandatory Steps)

### Step 1: Contract Extraction
Before writing a single test, articulate:
- **Inputs**: All parameters, their types, and their valid ranges
- **Outputs**: Return values, side effects, state mutations, exceptions thrown
- **Invariants**: What must always be true before and after execution?
- **Dependencies**: External services, databases, file systems, clocks, random generators

### Step 2: Test Category Matrix
Every test suite MUST cover ALL of these categories. Missing a category is a coverage gap.

#### A. Happy Path Tests
Standard operation with valid, typical inputs.
- Test the most common use case first
- Verify both return values AND side effects
- Test with realistic data, not contrived examples

#### B. Boundary & Edge Case Tests
The most valuable tests. This is where bugs live.
- **Empty/Null inputs**: `""`, `[]`, `{}`, `None`, `null`, `undefined`, `0`, `NaN`
- **Single element**: Collections with exactly one item
- **Maximum values**: `MAX_INT`, `MAX_SAFE_INTEGER`, very long strings, deeply nested objects
- **Minimum values**: Negative numbers, negative zero, smallest positive float
- **Off-by-one**: First element, last element, `length - 1`, `length`, `length + 1`
- **Type boundaries**: `int` vs `float`, `str` vs `bytes`, truthy vs falsy values
- **Unicode**: Emoji, RTL text, zero-width characters, surrogate pairs, combining characters
- **Whitespace**: Tabs, newlines, CRLF vs LF, leading/trailing spaces, non-breaking spaces
- **Concurrent boundaries**: Simultaneous access, interleaved operations

#### C. Error & Exception Tests
Verify that failures are graceful, informative, and safe.
- Test that invalid inputs raise the correct exception type with a useful message
- Test that errors don't leak sensitive information (stack traces, internal paths, credentials)
- Test that errors don't leave the system in a corrupted state (partial writes, dangling locks)
- Test that error handling doesn't swallow unexpected exceptions
- Test timeout behavior and resource cleanup on failure

#### D. State Mutation & Side Effect Tests
If the function modifies state, verify the full state transition.
- Test that only the intended state changed (no accidental mutations to unrelated data)
- Test idempotency: calling the function twice produces the same result as calling it once (where applicable)
- Test that shared/global state is not corrupted
- Test that database/file operations are atomic or properly rolled back on failure

#### E. Security & Adversarial Input Tests
Think like an attacker.
- **Injection**: SQL fragments, shell metacharacters, HTML/JS in strings, path traversal (`../`)
- **Overflow**: Extremely large numbers, extremely long strings, deeply recursive structures
- **Format string attacks**: `%s`, `%x`, `{0}` in user-supplied strings
- **Denial of Service**: Inputs designed to trigger worst-case algorithmic complexity (e.g., hash collision attacks, regex catastrophic backtracking)
- **Encoding attacks**: Mixed encodings, null bytes in strings, BOM markers

#### F. Algorithmic Correctness Tests
Verify the algorithm itself, not just the wrapper.
- **Known-answer tests**: Use pre-computed correct results for complex algorithms
- **Commutativity/Associativity**: Where applicable, verify mathematical properties
- **Inverse operations**: If you encode then decode, you should get the original
- **Monotonicity**: If input grows, does output behave as expected?
- **Determinism**: Same input must always produce same output (unless explicitly random)
- **Property-based thinking**: Generate invariants that must hold for ANY valid input

#### G. Integration Boundary Tests
Test the seams where your code meets external systems.
- Mock external dependencies, but also test with realistic mock data
- Verify that API contracts (request/response shapes) match documentation
- Test retry logic, circuit breakers, and fallback paths
- Test behavior when external systems return unexpected data (malformed JSON, wrong types, truncated responses)

#### H. Regression Guard Tests
Tests that exist solely to prevent known bugs from returning.
- For every bug fixed, add a test that reproduces the exact scenario
- Comment these tests with the bug description or ticket ID
- These tests are sacred — they should never be deleted without explicit justification

### Step 3: Test Implementation Standards

#### Naming Convention
Test names must describe the scenario and expected outcome:
```
test_<function>_<scenario>_<expected_behavior>
```
Examples:
- `test_parse_config_with_empty_file_raises_ValueError`
- `test_calculate_total_with_negative_discount_clamps_to_zero`
- `test_search_index_with_unicode_query_returns_matching_results`

#### Structure (Arrange-Act-Assert)
Every test follows this structure:
```
# Arrange: Set up preconditions and inputs
# Act: Execute the code under test (exactly ONE action)
# Assert: Verify the outcome (specific, not vague)
```

#### Assertion Quality
- **Be specific**: Assert exact values, not just truthiness. `assert result == 42` not `assert result`
- **Assert the negative**: Verify that things that shouldn't happen, didn't. `assert "password" not in log_output`
- **Assert side effects**: If a function should write to disk, verify the file exists AND has correct content
- **One logical assertion per test**: Multiple related asserts in one test are fine. Multiple unrelated asserts are not.

#### Mocking Rules
- Mock at the boundary, not in the middle. Mock the database client, not the ORM layer.
- Mock the minimum necessary. Over-mocking creates tests that pass even when the code is broken.
- Verify mock interactions: Was the mock called? With what arguments? How many times?
- Use realistic mock return values, not trivially simple ones.

### Step 4: Framework Selection
Choose the framework that matches the ecosystem:

| Language | Primary | Secondary | Property-Based |
|---|---|---|---|
| Python | `pytest` | `unittest` | `hypothesis` |
| JavaScript | `Jest` | `Vitest` | `fast-check` |
| TypeScript | `Vitest` | `Jest` | `fast-check` |
| Go | `testing` | `testify` | `rapid` |
| Rust | `#[test]` | `proptest` | `proptest` |
| Java | `JUnit 5` | `TestNG` | `jqwik` |
| C/C++ | `Google Test` | `Catch2` | — |

### Step 5: Coverage Analysis
After generating tests, assess:
- **Line coverage**: Every line of the function under test should be executed
- **Branch coverage**: Every `if/else`, `switch/case`, `try/catch` branch should be tested
- **Path coverage**: Combinations of branches that interact should be tested
- **Mutation coverage** (mental): If you change a `<` to `<=`, would a test catch it? If not, add one.

## Output Format

```
## Test Suite: <module/function name>

### Contract Summary
- **Inputs**: ...
- **Outputs**: ...
- **Invariants**: ...
- **Side Effects**: ...

### Coverage Matrix
| Category | Count | Key Scenarios |
|---|---|---|
| Happy Path | N | ... |
| Boundary/Edge | N | ... |
| Error Handling | N | ... |
| Security | N | ... |
| Algorithmic | N | ... |

### Test Code
<complete, ready-to-run test file>

### Run Command
<exact command to execute the tests>

### Known Gaps
<any scenarios that cannot be tested in isolation and require integration testing>
```

## Critical Rules

1. **Never generate a test that you haven't mentally verified would FAIL if the code had a bug.**
2. **Never use `assert True` or `assert result is not None` as the sole assertion** — these prove nothing.
3. **Never mock the thing you're testing** — only mock its dependencies.
4. **Always include at least one test that verifies error behavior** — happy-path-only suites are incomplete.
5. **Always provide the run command** — tests that can't be executed are useless.
6. **Comment the WHY for non-obvious test cases** — future engineers need to know why a test exists.
