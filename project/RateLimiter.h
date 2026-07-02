#ifndef RATE_LIMITER_H
#define RATE_LIMITER_H

#include <string>

// ---------------------------------------------------------------
// Strategy Pattern: common interface for all rate-limiting
// algorithms. Any concrete algorithm can be swapped in/out without
// changing the calling code (open/closed principle).
// ---------------------------------------------------------------
class RateLimiter {
public:
    virtual ~RateLimiter() = default;

    // Returns true if the request from `clientId` at time `nowMillis`
    // (epoch milliseconds) is allowed; false if it should be throttled.
    virtual bool allowRequest(const std::string &clientId, long long nowMillis) = 0;

    virtual std::string name() const = 0;
};

#endif
