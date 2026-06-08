---
name: optimize
description: Perform deep performance analysis and optimization of code — covering algorithmic complexity, memory management, I/O efficiency, concurrency, and system-level bottlenecks. Use this skill when the user asks to optimize, speed up, refactor for performance, reduce memory usage, or fix latency issues. Optimizations must be measured, justified, and safe.
---

This skill applies rigorous engineering discipline to performance optimization. Every change must be justified by analysis, not intuition. Premature optimization is the root of evil, but negligent performance engineering is the root of outages.

## Optimization Philosophy

**Never optimize without measuring. Never measure without understanding.**

Before changing a single line:
- **Profile First**: What is actually slow? CPU-bound or I/O-bound? Where does the flamegraph spike?
- **Understand the Access Pattern**: How is this code called? Once per request? In a tight loop? On startup only?
- **Define the Target**: What is "fast enough"? A 10ms API endpoint doesn't need nanosecond optimization. A hot loop processing 10M records does.

## Optimization Dimensions (Ordered by Impact)

### 1. Algorithmic Complexity Reduction
The highest-impact optimization. A better algorithm beats a faster machine.

- **Identify Current Complexity**: State explicit Big-O for time AND space. Include amortized analysis where relevant.
- **Common Upgrades**:
  - O(N²) → O(N log N): Replace nested loops with sorting + binary search, or merge-based approaches
  - O(N) lookup → O(1): Replace list scans with hash maps/sets
  - O(N) string concatenation → O(N) with StringBuilder/join: Eliminate Schlemiel the Painter
  - O(2^N) → O(N) or O(N²): Apply dynamic programming / memoization
- **Data Structure Selection**:
  - Frequent lookups: `dict`/`HashMap`/`Map` over `list`/`Array`
  - Ordered data with range queries: Sorted arrays, B-trees, skip lists
  - Frequent insertions/deletions: Linked lists, balanced trees
  - Membership testing: `set`/`HashSet` over `list`/`Array`
  - Priority access: Heaps over sorted arrays (O(log N) insert vs O(N))

### 2. I/O & Network Optimization
I/O is almost always the bottleneck in real systems.

- **Batch Operations**: Replace N individual database queries with one batch query (eliminate N+1 problem)
- **Connection Pooling**: Reuse HTTP/database connections instead of creating new ones per request
- **Async I/O**: Convert blocking calls to async where the runtime supports it. Free threads to handle other work while waiting on network/disk.
- **Streaming**: Process large files/responses as streams instead of loading entirely into memory
- **Compression**: Enable gzip/brotli for network payloads. Use binary formats (protobuf, msgpack) over JSON for high-throughput paths
- **Lazy Loading**: Don't fetch data until it's actually needed. Don't initialize heavy resources on import.

### 3. Memory Optimization
Memory pressure causes GC pauses, swapping, and OOM kills.

- **Object Lifetime Management**: Release references as soon as possible. Use context managers / try-with-resources for deterministic cleanup.
- **Avoid Unnecessary Copies**: Pass by reference where safe. Use views/slices instead of copying arrays. Use `__slots__` in Python classes with many instances.
- **Generator/Iterator Patterns**: Use generators/iterators for large sequences instead of materializing full lists
- **Buffer Reuse**: Reuse byte buffers in tight loops instead of allocating new ones
- **Weak References**: Use weak references for caches that should not prevent garbage collection
- **Memory Pool Patterns**: Pre-allocate pools for objects with high churn rates

### 4. Concurrency & Parallelism
Correctly applied concurrency multiplies throughput. Incorrectly applied concurrency creates race conditions.

- **Identify Parallelizable Work**: Independent computations on independent data. Map-reduce patterns. Embarrassingly parallel problems.
- **Thread vs Process vs Async**: CPU-bound → multiprocessing/threads with real parallelism. I/O-bound → async/await or event loops. Mixed → hybrid approaches.
- **Lock Minimization**: Prefer lock-free data structures. Minimize critical section size. Use read-write locks for read-heavy workloads.
- **Work Stealing**: Use task queues with work-stealing schedulers for uneven workloads.

### 5. Caching
The right cache transforms O(N) into O(1). The wrong cache creates stale data bugs.

- **Cache Placement**: Client-side, application-level, database-level, CDN-level. Each has different invalidation characteristics.
- **Invalidation Strategy**: TTL-based, event-based, version-based. "There are only two hard things in CS: cache invalidation and naming things."
- **Bounded Caches**: Always set a maximum size. Use LRU, LFU, or ARC eviction. Unbounded caches are memory leaks.
- **Memoization**: Pure functions with repeated inputs are free caching opportunities. Use `functools.lru_cache`, `useMemo`, or manual memo tables.

### 6. Micro-Optimizations (Apply Last)
These matter only in hot paths confirmed by profiling.

- **Branch Prediction**: Put the most common case first in if/else chains
- **Loop Invariant Hoisting**: Move constant computations outside of loops
- **Short-Circuit Evaluation**: Order boolean conditions by cost (cheap checks first)
- **Avoid Regex in Hot Paths**: Compile regex once, or replace with string operations where possible
- **Numeric Precision**: Use integers instead of floats for exact arithmetic. Use fixed-point for financial calculations.

## Output Format

```
## Optimization Report: <module/function name>

### Current Performance Profile
- **Time Complexity**: O(...)
- **Space Complexity**: O(...)
- **Bottleneck Type**: CPU / I/O / Memory / Concurrency
- **Hot Path**: <which lines/functions dominate execution time>

### Proposed Optimizations (Ranked by Impact)
1. **[HIGH]** <description>
   - Before: O(N²) / 150ms p99
   - After: O(N log N) / 12ms p99
   - Risk: LOW
   
2. **[MEDIUM]** <description>
   ...

### Optimized Code
<complete, drop-in replacement code with comments explaining each change>

### Complexity Comparison
| Metric | Before | After | Improvement |
|---|---|---|---|
| Time Complexity | O(N²) | O(N log N) | ~100x at N=10K |
| Space Complexity | O(N) | O(1) | Constant |
| Latency (p99) | 150ms | 12ms | 12.5x |

### Trade-offs & Risks
- <any maintainability, readability, or correctness trade-offs introduced>
```

## Critical Rules

1. **Profile before optimizing** — Never guess where the bottleneck is.
2. **One optimization at a time** — Measure the impact of each change independently.
3. **Never sacrifice correctness for speed** — A fast wrong answer is worse than a slow correct one.
4. **Document the WHY** — Future engineers need to know why a less-readable approach was chosen.
5. **Preserve the public API** — Optimizations should be invisible to callers unless the contract explicitly changes.
6. **Test before and after** — Ensure the optimized code produces identical results to the original.
