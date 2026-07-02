#ifndef SLIDING_WINDOW_LOG_H
#define SLIDING_WINDOW_LOG_H

#include "RateLimiter.h"
#include <unordered_map>
#include <deque>

// ---------------------------------------------------------------
// Sliding Window Log Algorithm
// ------------------------------
// Keeps an exact log (deque) of request timestamps per client
// within the last `windowMillis`. On each request, expire
// timestamps older than the window, then allow only if the log
// size is below `maxRequests`.
//
// Pros: exact, no burst-at-boundary problem (unlike Fixed Window).
// Cons: O(window size) memory per client; each request does O(k)
//       work to pop expired entries (k = expired count, amortized
//       O(1) since each entry is popped exactly once).
// ---------------------------------------------------------------
class SlidingWindowLogLimiter : public RateLimiter {
private:
    std::unordered_map<std::string, std::deque<long long>> logs;
    int maxRequests;
    long long windowMillis;

public:
    SlidingWindowLogLimiter(int maxRequests_, long long windowMillis_)
        : maxRequests(maxRequests_), windowMillis(windowMillis_) {}

    bool allowRequest(const std::string &clientId, long long nowMillis) override {
        std::deque<long long> &log = logs[clientId];

        // Evict timestamps outside the current window
        while (!log.empty() && nowMillis - log.front() >= windowMillis) {
            log.pop_front();
        }

        if ((int)log.size() < maxRequests) {
            log.push_back(nowMillis);
            return true;
        }
        return false;
    }

    std::string name() const override { return "Sliding Window Log"; }
};

#endif
