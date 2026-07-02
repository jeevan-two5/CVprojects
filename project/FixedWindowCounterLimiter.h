#ifndef FIXED_WINDOW_COUNTER_H
#define FIXED_WINDOW_COUNTER_H

#include "RateLimiter.h"
#include <unordered_map>

// ---------------------------------------------------------------
// Fixed Window Counter Algorithm
// ---------------------------------
// Time is divided into fixed-size windows (e.g. every 1000ms).
// Each client has a counter that resets to 0 at the start of each
// new window. A request is allowed if the counter is below
// `maxRequests`, then incremented.
//
// Pros: O(1) time and O(1) memory per client (just one counter).
// Cons: "boundary burst" problem -- a client can send maxRequests
//       right at the end of one window and maxRequests again right
//       at the start of the next, getting 2x the intended rate in
//       a short burst around the window edge.
// ---------------------------------------------------------------
class FixedWindowCounterLimiter : public RateLimiter {
private:
    struct WindowState {
        long long windowStart;
        int count;
    };

    std::unordered_map<std::string, WindowState> windows;
    int maxRequests;
    long long windowMillis;

public:
    FixedWindowCounterLimiter(int maxRequests_, long long windowMillis_)
        : maxRequests(maxRequests_), windowMillis(windowMillis_) {}

    bool allowRequest(const std::string &clientId, long long nowMillis) override {
        auto it = windows.find(clientId);
        long long currentWindowStart = (nowMillis / windowMillis) * windowMillis;

        if (it == windows.end() || it->second.windowStart != currentWindowStart) {
            windows[clientId] = {currentWindowStart, 1};
            return true;
        }

        WindowState &w = it->second;
        if (w.count < maxRequests) {
            w.count++;
            return true;
        }
        return false;
    }

    std::string name() const override { return "Fixed Window Counter"; }
};

#endif
