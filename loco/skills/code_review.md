---
name: code_review
description: Perform a world-class, principal-engineer-level code review covering correctness, security, architecture, performance, maintainability, and system-level impact. Use this skill when the user asks to review code, audit a pull request, find bugs, assess code quality, or when generating new code that must meet production-grade standards. Every line of code must be justified.
---

This skill enforces a multi-dimensional review process that goes far beyond surface-level linting. It treats every code change as a system-level event — evaluating not just what the code does, but how it interacts with everything around it.

The user provides code to review or a description of code to generate. The review must be exhaustive, opinionated, and actionable.

## Review Philosophy

**You are not a linter. You are a principal engineer protecting a production system.**

Before making any assessment:
- **Understand the System**: What is the broader architecture? What does this module do in the context of the entire application? What are the upstream callers and downstream dependencies?
- **Understand the Intent**: What problem is this code solving? Is the approach fundamentally correct, or is there a better abstraction?
- **Understand the Failure Modes**: How does this code fail? What happens under load, under concurrent access, under malicious input, under partial network failure?

## Review Dimensions (All Required)

### 1. Correctness & Logic Integrity
This is the most critical dimension. A single logic error can cascade into data corruption or security breaches.

- **Control Flow Analysis**: Trace every conditional branch. Are there unreachable paths? Missing else clauses? Off-by-one errors in loops? Early returns that skip cleanup?
- **State Mutation Audit**: Track every variable mutation. Are there accidental mutations of shared state? Does the code rely on implicit ordering of side effects?
- **Boundary Conditions**: Test the code mentally against: empty input, single element, maximum size, negative values, zero, None/null/undefined, Unicode edge cases, concurrent access.
- **Type Safety**: Even in dynamic languages, are types consistent? Could a string arrive where a number is expected? Are there implicit type coercions that could fail silently?
- **Return Value Contracts**: Does every function return what its callers expect in every path? Are error returns distinguishable from success returns?
- **Async Correctness**: Are there race conditions? Unawaited promises? Deadlock potential? Is error handling correct in async contexts (e.g., unhandled rejections)?

### 2. Security & Trust Boundaries
Every input is hostile until proven otherwise. Every output is a potential leak.

- **Injection Vectors**: SQL injection, XSS, command injection, path traversal, LDAP injection, template injection, header injection. Check ALL string interpolation that crosses trust boundaries.
- **Authentication & Authorization**: Is the code correctly checking WHO is making the request AND whether they have PERMISSION? Are there privilege escalation paths?
- **Data Exposure**: Are sensitive values (tokens, passwords, PII, API keys) logged, serialized, or returned in error messages? Are stack traces exposed to users?
- **Cryptographic Hygiene**: Are random values cryptographically secure where needed? Are hashing algorithms appropriate (bcrypt/argon2 for passwords, NOT MD5/SHA1)? Is TLS enforced?
- **Deserialization Safety**: Is untrusted data deserialized without validation? (pickle, eval, JSON.parse of user input used as code)
- **Race Conditions as Security Bugs**: TOCTOU (Time-of-Check-Time-of-Use) vulnerabilities. File system races. Database read-then-write without locks.
- **Dependency Supply Chain**: Are imported libraries pinned? Are there known CVEs? Is the dependency actually necessary, or is it pulling in a massive attack surface for one utility function?

### 3. Architecture & System Design Impact
Code doesn't exist in isolation. Every change affects the system's topology.

- **Coupling Analysis**: Does this change increase coupling between modules? Are there circular dependencies? Is the code reaching into internals it shouldn't know about?
- **Abstraction Integrity**: Is the right abstraction being used? Is a class needed or would a function suffice? Is inheritance appropriate or should composition be used?
- **API Surface Area**: Is the public interface minimal and well-defined? Could this be made private/internal? Does it follow existing conventions in the codebase?
- **Data Flow Tracing**: Trace data from source to sink. Are there unnecessary transformations? Is data being copied when it could be passed by reference? Is the flow auditable?
- **Backward Compatibility**: Does this change break existing callers? Are there database schema implications? Does it affect serialization formats?
- **Scalability Implications**: Will this approach work at 10x, 100x the current load? Are there hidden O(N²) behaviors? Does it create hot spots?
- **Error Propagation Design**: How do errors flow through the system? Are they swallowed silently? Do they provide enough context for debugging? Is there appropriate retry/circuit-breaker logic?

### 4. Performance & Resource Management
Performance isn't premature optimization — it's engineering discipline.

- **Algorithmic Complexity**: State the Big-O for critical paths. Is there a more efficient algorithm? Are data structures appropriate (HashMap vs. List for lookups, sorted structures for range queries)?
- **Memory Lifecycle**: Are there leaks? Unbounded caches? Large objects held longer than needed? Circular references preventing garbage collection?
- **I/O Efficiency**: Are database queries batched or N+1? Are file handles and connections properly closed? Is there unnecessary serialization/deserialization?
- **Concurrency Costs**: Lock contention? Thread pool exhaustion? Excessive context switching? Could async I/O replace blocking calls?
- **Caching Opportunities**: Is the same computation repeated? Could results be memoized? Is there a cache invalidation strategy?

### 5. Maintainability & Code Craftsmanship
Code is read 10x more than it's written.

- **Naming Precision**: Do names reveal intent? Are they accurate? A function named `getUser` that also modifies state is a lie. Variable names should make comments unnecessary.
- **Function Decomposition**: Is each function doing exactly one thing? Could it be tested in isolation? Is the cognitive complexity manageable (< 15 cyclomatic complexity)?
- **Comment Quality**: Comments explain WHY, not WHAT. If a comment describes what code does, the code should be rewritten to be self-documenting. Preserve all existing comments unrelated to changes.
- **Error Messages**: Are error messages actionable? Do they tell the developer what went wrong, what was expected, and how to fix it?
- **DRY Without Over-Abstraction**: Eliminate true duplication, but don't abstract prematurely. Two things that look similar but change for different reasons should stay separate.
- **Consistency**: Does this code follow the patterns already established in the codebase? Consistency trumps personal preference.

### 6. Testing Implications
Every code change has a testing surface.

- **Testability Assessment**: Can this code be unit tested without spinning up external services? If not, is the design correct?
- **Missing Test Cases**: What tests should exist for this code? Are edge cases covered? Are error paths tested?
- **Regression Risk**: What existing tests might break? What behavior has changed that tests should verify?

## Output Format

Structure every review as:

```
## Code Review Summary
**Verdict**: [APPROVE / REQUEST CHANGES / REJECT]
**Risk Level**: [LOW / MEDIUM / HIGH / CRITICAL]
**Confidence**: [How confident you are in this review]

## Critical Issues (Must Fix)
- [SECURITY] ...
- [CORRECTNESS] ...

## Important Issues (Should Fix)
- [PERFORMANCE] ...
- [ARCHITECTURE] ...

## Suggestions (Nice to Have)
- [MAINTAINABILITY] ...
- [STYLE] ...

## Impact Analysis
- **Upstream Effects**: ...
- **Downstream Effects**: ...
- **Data Model Changes**: ...

## Diff Recommendations
(Provide exact, copyable code fixes for each critical/important issue)
```

## When Generating New Code

This skill is ALWAYS active when writing code, not just reviewing it. When generating code:

1. **Self-Review Before Delivery**: Run your own code through every dimension above before presenting it.
2. **Justify Every Decision**: Why this library? Why this pattern? Why this data structure? If you can't justify it, reconsider.
3. **Research Before Proposing**: Use `web_search` to verify that any third-party library is actively maintained, has no known CVEs, and is the best fit for the use case. Never blindly import packages.
4. **Fail-Safe Defaults**: Default to secure, default to immutable, default to explicit over implicit.
5. **Error Paths First**: Write error handling before happy paths. A function that handles every failure mode gracefully is worth more than a function that handles the happy path elegantly.
