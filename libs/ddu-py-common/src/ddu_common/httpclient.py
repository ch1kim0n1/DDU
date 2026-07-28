"""Resilient HTTP client with retry, rate limiting, and circuit breaker."""

import asyncio
import time
from typing import Any, Dict, Optional
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

class CircuitBreakerError(Exception):
    """Raised when circuit is open."""
    pass

class CircuitBreaker:
    """Simple circuit breaker implementation."""
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        expected_exception: Exception = Exception,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "closed"  # closed, open, half-open
        self._lock = asyncio.Lock()
    
    async def call(self, func, *args, **kwargs):
        """Execute function with circuit breaker protection."""
        async with self._lock:
            if self.state == "open":
                if self._should_attempt_reset():
                    self.state = "half-open"
                else:
                    raise CircuitBreakerError("Circuit is open")
            
            try:
                result = await func(*args, **kwargs)
                if self.state == "half-open":
                    self._reset()
                return result
            except Exception as e:
                if isinstance(e, self.expected_exception):
                    self._record_failure()
                raise
    
    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset."""
        if self.last_failure_time is None:
            return True
        return time.time() - self.last_failure_time >= self.recovery_timeout
    
    def _record_failure(self):
        """Record a failure and potentially open the circuit."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = "open"
    
    def _reset(self):
        """Reset the circuit breaker to closed state."""
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "closed"

class RateLimiter:
    """Token bucket rate limiter."""
    
    def __init__(self, rate: float = 100.0, burst: int = 10):
        self.rate = rate
        self.burst = burst
        self.tokens = burst
        self.last_update = time.time()
        self._lock = asyncio.Lock()
    
    async def acquire(self):
        """Acquire a token from the bucket."""
        async with self._lock:
            now = time.time()
            elapsed = now - self.last_update
            self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
            self.last_update = now
            
            if self.tokens < 1:
                wait_time = (1 - self.tokens) / self.rate
                await asyncio.sleep(wait_time)
                self.tokens = 0
            else:
                self.tokens -= 1

class DDUHTTPClient:
    """Resilient HTTP client for DDU services."""
    
    def __init__(
        self,
        max_retries: int = 3,
        retry_delay: float = 0.1,
        circuit_breaker_enabled: bool = True,
        rate_limiter_enabled: bool = True,
        rate_limiter_rps: float = 100.0,
        rate_limiter_burst: int = 10,
        timeout: float = 30.0,
    ):
        self.max_retries = max_retries
        self.circuit_breaker_enabled = circuit_breaker_enabled
        self.rate_limiter_enabled = rate_limiter_enabled
        
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
        self.rate_limiter = RateLimiter(rate_limiter_rps, rate_limiter_burst) if rate_limiter_enabled else None
        
        self.client = httpx.AsyncClient(
            timeout=timeout,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
    
    def _get_circuit_breaker(self, service_name: str) -> CircuitBreaker:
        """Get or create circuit breaker for a service."""
        if service_name not in self.circuit_breakers:
            self.circuit_breakers[service_name] = CircuitBreaker(
                failure_threshold=5,
                recovery_timeout=60.0,
                expected_exception=(httpx.HTTPError, httpx.HTTPStatusError),
            )
        return self.circuit_breakers[service_name]
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.1, min=0.1, max=10.0),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.HTTPStatusError)),
    )
    async def request(
        self,
        method: str,
        url: str,
        **kwargs
    ) -> httpx.Response:
        """Make HTTP request with retry, rate limiting, and circuit breaker."""
        if self.rate_limiter_enabled and self.rate_limiter:
            await self.rate_limiter.acquire()
        
        if self.circuit_breaker_enabled:
            service_name = httpx.URL(url).host
            circuit_breaker = self._get_circuit_breaker(service_name)
            
            async def _make_request():
                response = await self.client.request(method, url, **kwargs)
                response.raise_for_status()
                return response
            
            return await circuit_breaker.call(_make_request)
        else:
            response = await self.client.request(method, url, **kwargs)
            response.raise_for_status()
            return response
    
    async def get(self, url: str, **kwargs) -> httpx.Response:
        """GET request."""
        return await self.request("GET", url, **kwargs)
    
    async def post(self, url: str, **kwargs) -> httpx.Response:
        """POST request."""
        return await self.request("POST", url, **kwargs)
    
    async def put(self, url: str, **kwargs) -> httpx.Response:
        """PUT request."""
        return await self.request("PUT", url, **kwargs)
    
    async def patch(self, url: str, **kwargs) -> httpx.Response:
        """PATCH request."""
        return await self.request("PATCH", url, **kwargs)
    
    async def delete(self, url: str, **kwargs) -> httpx.Response:
        """DELETE request."""
        return await self.request("DELETE", url, **kwargs)
    
    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()