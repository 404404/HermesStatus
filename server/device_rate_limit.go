package main

import (
	"crypto/sha256"
	"fmt"
	"net"
	"sync"
	"time"
)

type rateLimitEntry struct {
	WindowStart time.Time
	LastSeen    time.Time
	Count       int
}

type boundedRateLimiter struct {
	mu       sync.Mutex
	entries  map[string]rateLimitEntry
	capacity int
	limit    int
	window   time.Duration
	ttl      time.Duration
}

func newBoundedRateLimiter(
	capacity int,
	limit int,
	window time.Duration,
	ttl time.Duration,
) *boundedRateLimiter {
	return &boundedRateLimiter{
		entries:  make(map[string]rateLimitEntry, capacity),
		capacity: capacity, limit: limit, window: window, ttl: ttl,
	}
}

func (limiter *boundedRateLimiter) Allow(
	key string,
	now time.Time,
) (bool, time.Duration) {
	if limiter == nil || key == "" {
		return false, time.Second
	}
	limiter.mu.Lock()
	defer limiter.mu.Unlock()
	limiter.cleanupLocked(now)

	entry, exists := limiter.entries[key]
	if !exists {
		if len(limiter.entries) >= limiter.capacity {
			return false, time.Second
		}
		entry = rateLimitEntry{WindowStart: now}
	}
	if now.Sub(entry.WindowStart) >= limiter.window {
		entry.WindowStart = now
		entry.Count = 0
	}
	entry.LastSeen = now
	if entry.Count >= limiter.limit {
		limiter.entries[key] = entry
		retry := limiter.window - now.Sub(entry.WindowStart)
		if retry < time.Second {
			retry = time.Second
		}
		return false, retry
	}
	entry.Count++
	limiter.entries[key] = entry
	return true, 0
}

func (limiter *boundedRateLimiter) cleanupLocked(now time.Time) {
	for key, entry := range limiter.entries {
		if now.Sub(entry.LastSeen) >= limiter.ttl {
			delete(limiter.entries, key)
		}
	}
}

func (limiter *boundedRateLimiter) Len() int {
	limiter.mu.Lock()
	defer limiter.mu.Unlock()
	return len(limiter.entries)
}

func preAuthSourceKey(remoteAddress string) string {
	host, _, err := net.SplitHostPort(remoteAddress)
	if err != nil {
		host = remoteAddress
	}
	digest := sha256.Sum256([]byte(host))
	return fmt.Sprintf("src-%x", digest[:12])
}
