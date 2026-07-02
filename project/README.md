# Rate Limiter Engine

A C++ implementation and benchmark of three production rate-limiting algorithms,
unified behind a common `RateLimiter` interface (Strategy design pattern).

## Files
- `RateLimiter.h` — abstract interface (Strategy pattern base)
- `TokenBucketLimiter.h` — Token Bucket algorithm
- `SlidingWindowLogLimiter.h` — Sliding Window Log algorithm
- `FixedWindowCounterLimiter.h` — Fixed Window Counter algorithm
- `main.cpp` — throughput benchmark, burst-tolerance test, and a boundary-burst
  demonstration comparing Fixed Window vs Sliding Window Log
- `Project3_Rate_Limiter_Engine.pdf` — full write-up with results

## Compile & Run
```bash
g++ -O2 -std=c++17 main.cpp -o rate_limiter
./rate_limiter
```

## What It Demonstrates
1. **Strategy pattern**: swap any of the three algorithms in/out with zero changes
   to calling code — just implement the `RateLimiter` interface.
2. **Throughput**: 20,000 simulated requests processed at 10M+ decisions/sec
   for each algorithm (pure in-memory logic, no I/O).
3. **The Fixed Window boundary-burst flaw, reproduced experimentally**:
   sending 10 requests right at the end of one window and 10 more right at the
   start of the next (limit = 10/window) results in:
   - Fixed Window Counter: **20/20 allowed** (2x the intended rate!)
   - Sliding Window Log: **10/20 allowed** (correctly enforced)

## CV Talking Points
- Rate limiting is a real production concept (used by Stripe, AWS API Gateway,
  Cloudflare) — not a toy exercise, so it's a strong interview topic.
- You can explain the Strategy pattern concretely using this project if asked
  "tell me about a design pattern you've used."
- You experimentally reproduced a textbook algorithmic flaw (Fixed Window
  boundary burst) instead of just describing it — this is a great answer to
  "what's the trade-off between these approaches?"

## Possible Extensions
- Distributed rate limiting via Redis (shared state across multiple servers)
- Sliding Window Counter (approximate hybrid, O(1) memory — what Cloudflare
  actually uses in production)
- Wrap the engine in an HTTP middleware layer (e.g. with a small REST server)
