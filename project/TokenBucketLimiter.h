#ifndef TOKEN_BUCKET_H
#define TOKEN_BUCKET_H

#include "RateLimiter.h"
#include <unordered_map>

// ---------------------------------------------------------------
// Token Bucket Algorithm
// -----------------------
// Each client has a "bucket" that holds up to `capacity` tokens.
// Tokens refill continuously at `refillRatePerSec`. Each request
// consumes 1 token; if the bucket is empty, the request is denied.
//
// Pros: allows short bursts up to `capacity`, smooths average rate.
// Time complexity: O(1) per request (amortized, hashmap lookup).
// ---------------------------------------------------------------
class TokenBucketLimiter : public RateLimiter {
private:
    struct Bucket {
        double tokens;
        long long lastRefillMillis;
    };

    std::unordered_map<std::string, Bucket> buckets;
    double capacity;
    double refillRatePerSec; // tokens added per second

public:
    TokenBucketLimiter(double capacity_, double refillRatePerSec_)
        : capacity(capacity_), refillRatePerSec(refillRatePerSec_) {}

    bool allowRequest(const std::string &clientId, long long nowMillis) override {
        auto it = buckets.find(clientId);
        if (it == buckets.end()) {
            // New client starts with a full bucket, minus this request's token
            buckets[clientId] = {capacity - 1.0, nowMillis};
            return true;
        }

        Bucket &b = it->second;
        double elapsedSec = (nowMillis - b.lastRefillMillis) / 1000.0;
        double refill = elapsedSec * refillRatePerSec;
        b.tokens = std::min(capacity, b.tokens + refill);
        b.lastRefillMillis = nowMillis;

        if (b.tokens >= 1.0) {
            b.tokens -= 1.0;
            return true;
        }
        return false;
    }

    std::string name() const override { return "Token Bucket"; }
};

#endif
