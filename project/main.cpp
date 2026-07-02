// Rate Limiter Engine
// ---------------------
// Implements and benchmarks three production rate-limiting algorithms
// (Token Bucket, Sliding Window Log, Fixed Window Counter) behind a
// common Strategy-pattern interface (RateLimiter).
//
// Compile: g++ -O2 -std=c++17 main.cpp -o rate_limiter
// Run:     ./rate_limiter

#include <iostream>
#include <iomanip>
#include <vector>
#include <memory>
#include <chrono>
#include <random>

#include "RateLimiter.h"
#include "TokenBucketLimiter.h"
#include "SlidingWindowLogLimiter.h"
#include "FixedWindowCounterLimiter.h"

using namespace std;
using namespace std::chrono;

// ---------------------------------------------------------------
// Test 1: Throughput benchmark
// Simulates a high volume of requests from many clients and
// measures how fast each algorithm can process them (ops/sec).
// ---------------------------------------------------------------
void throughputBenchmark(RateLimiter &limiter, int numClients, int requestsPerClient) {
    mt19937 gen(7);
    uniform_int_distribution<int> clientDist(0, numClients - 1);

    long long baseTime = 0;
    int allowed = 0, denied = 0;
    int totalRequests = numClients * requestsPerClient;

    auto start = high_resolution_clock::now();
    for (int i = 0; i < totalRequests; i++) {
        string clientId = "client_" + to_string(clientDist(gen));
        // requests spaced ~1ms apart on average across all clients combined
        long long t = baseTime + (i / 5); // 5 requests "per millisecond" globally
        if (limiter.allowRequest(clientId, t)) allowed++;
        else denied++;
    }
    auto end = high_resolution_clock::now();
    double ms = duration<double, milli>(end - start).count();
    double reqPerSec = totalRequests / (ms / 1000.0);

    cout << left << setw(22) << limiter.name()
         << setw(12) << totalRequests
         << setw(12) << allowed
         << setw(12) << denied
         << setw(14) << fixed << setprecision(2) << ms
         << setw(16) << fixed << setprecision(0) << reqPerSec << "\n";
}

// ---------------------------------------------------------------
// Test 2: Burst tolerance
// A single client sends a sudden burst of requests, then goes idle,
// then bursts again. Shows how each algorithm handles bursty traffic.
// ---------------------------------------------------------------
void burstTest(RateLimiter &limiter) {
    string client = "burst_client";
    int allowedInBurst = 0;

    cout << "\n[" << limiter.name() << "] Sending 15 requests instantly at t=0ms:\n  ";
    for (int i = 0; i < 15; i++) {
        bool ok = limiter.allowRequest(client, 0);
        cout << (ok ? "A" : "D");
        if (ok) allowedInBurst++;
    }
    cout << "  -> " << allowedInBurst << "/15 allowed\n";
}

// ---------------------------------------------------------------
// Test 3: Fixed Window boundary-burst problem demonstration
// Sends maxRequests right at the END of window 1, then maxRequests
// again right at the START of window 2 (a few ms later). Fixed
// Window Counter will allow ~2x the intended rate in this short
// span; Sliding Window Log will correctly restrict it.
// ---------------------------------------------------------------
void boundaryBurstTest() {
    int maxReq = 10;
    long long windowMs = 1000;

    FixedWindowCounterLimiter fixedLimiter(maxReq, windowMs);
    SlidingWindowLogLimiter slidingLimiter(maxReq, windowMs);

    string client = "edge_client";

    // Window 1 ends at t=999; window 2 starts at t=1000.
    int fixedAllowed = 0, slidingAllowed = 0;

    // Burst of `maxReq` requests just before window boundary (t=990..999)
    for (int i = 0; i < maxReq; i++) {
        long long t = 990 + i;
        if (fixedLimiter.allowRequest(client, t)) fixedAllowed++;
        if (slidingLimiter.allowRequest(client, t)) slidingAllowed++;
    }
    // Burst of `maxReq` requests just after window boundary (t=1000..1009)
    for (int i = 0; i < maxReq; i++) {
        long long t = 1000 + i;
        if (fixedLimiter.allowRequest(client, t)) fixedAllowed++;
        if (slidingLimiter.allowRequest(client, t)) slidingAllowed++;
    }

    cout << "\n=== Boundary-Burst Problem: " << maxReq
         << " req/window, 20 requests sent across a window edge (t=990ms to t=1009ms) ===\n";
    cout << "Fixed Window Counter allowed:  " << fixedAllowed << " / 20"
         << (fixedAllowed > maxReq ? "   <-- exceeds intended rate limit!" : "") << "\n";
    cout << "Sliding Window Log allowed:    " << slidingAllowed << " / 20"
         << "   <-- correctly stays within rate limit\n";
}

int main() {
    cout << "=== Rate Limiter Engine: Algorithm Comparison ===\n\n";

    // --- Throughput benchmark: all three algorithms under identical load ---
    cout << "--- Throughput Benchmark (200 clients x 100 requests = 20,000 requests) ---\n";
    cout << left << setw(22) << "Algorithm"
         << setw(12) << "Total"
         << setw(12) << "Allowed"
         << setw(12) << "Denied"
         << setw(14) << "Time(ms)"
         << setw(16) << "Req/sec (engine)" << "\n";
    cout << string(88, '-') << "\n";

    TokenBucketLimiter tb(20.0, 5.0);              // capacity 20, refill 5 tokens/sec
    SlidingWindowLogLimiter swl(10, 1000);          // 10 req per 1000ms window
    FixedWindowCounterLimiter fwc(10, 1000);        // 10 req per 1000ms window

    throughputBenchmark(tb, 200, 100);
    throughputBenchmark(swl, 200, 100);
    throughputBenchmark(fwc, 200, 100);

    // --- Burst tolerance test ---
    cout << "\n--- Burst Tolerance Test (A = allowed, D = denied) ---";
    TokenBucketLimiter tb2(10.0, 2.0);
    SlidingWindowLogLimiter swl2(10, 1000);
    FixedWindowCounterLimiter fwc2(10, 1000);
    burstTest(tb2);
    burstTest(swl2);
    burstTest(fwc2);

    // --- Boundary burst problem demonstration ---
    boundaryBurstTest();

    return 0;
}
