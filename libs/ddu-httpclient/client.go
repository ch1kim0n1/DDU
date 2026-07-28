package dduhttpclient

import (
	"context"
	"net/http"
	"sync"
	"time"

	"github.com/sony/gobreaker"
	"golang.org/x/time/rate"
)

type Config struct {
	// HTTPClient allows callers to provide a custom transport. It is useful for
	// tests and for deployments that require a configured proxy or mTLS client.
	HTTPClient     *http.Client
	MaxRetries     int
	RetryDelay     time.Duration
	CircuitBreaker CircuitBreakerConfig
	RateLimiter    RateLimiterConfig
	Timeout        time.Duration
}

type CircuitBreakerConfig struct {
	Enabled       bool
	MaxRequests   uint32
	Interval      time.Duration
	Timeout       time.Duration
	ReadyToTrip   func(counts gobreaker.Counts) bool
	OnStateChange func(name string, from gobreaker.State, to gobreaker.State)
}

type RateLimiterConfig struct {
	Enabled bool
	RPS     float64
	Burst   int
}

type Client struct {
	httpClient *http.Client
	breakers   map[string]*gobreaker.CircuitBreaker
	limiter    *rate.Limiter
	config     Config
	breakerMtx sync.RWMutex
}

func NewClient(config Config) *Client {
	if config.MaxRetries == 0 {
		config.MaxRetries = 3
	}
	if config.RetryDelay == 0 {
		config.RetryDelay = 100 * time.Millisecond
	}
	if config.Timeout == 0 {
		config.Timeout = 30 * time.Second
	}

	httpClient := config.HTTPClient
	if httpClient == nil {
		httpClient = &http.Client{Timeout: config.Timeout}
	}

	client := &Client{
		httpClient: httpClient,
		breakers:   make(map[string]*gobreaker.CircuitBreaker),
		config:     config,
	}

	if config.RateLimiter.Enabled {
		if config.RateLimiter.RPS == 0 {
			config.RateLimiter.RPS = 100
		}
		if config.RateLimiter.Burst == 0 {
			config.RateLimiter.Burst = 10
		}
		client.limiter = rate.NewLimiter(rate.Limit(config.RateLimiter.RPS), config.RateLimiter.Burst)
	}

	return client
}

func (c *Client) Do(ctx context.Context, req *http.Request) (*http.Response, error) {
	if c.config.RateLimiter.Enabled {
		if err := c.limiter.Wait(ctx); err != nil {
			return nil, err
		}
	}

	serviceName := req.URL.Host
	if c.config.CircuitBreaker.Enabled {
		breaker := c.getBreaker(serviceName)
		result, err := breaker.Execute(func() (interface{}, error) {
			return c.doWithRetry(ctx, req)
		})
		if err != nil {
			return nil, err
		}
		return result.(*http.Response), nil
	}

	return c.doWithRetry(ctx, req)
}

func (c *Client) doWithRetry(ctx context.Context, req *http.Request) (*http.Response, error) {
	var lastErr error
	for attempt := 0; attempt <= c.config.MaxRetries; attempt++ {
		if attempt > 0 {
			select {
			case <-time.After(c.config.RetryDelay * time.Duration(attempt)):
			case <-ctx.Done():
				return nil, ctx.Err()
			}
		}

		resp, err := c.httpClient.Do(req)
		if err == nil {
			if resp.StatusCode < 500 {
				return resp, nil
			}
			resp.Body.Close()
			lastErr = &HTTPError{StatusCode: resp.StatusCode, URL: req.URL.String()}
		} else {
			lastErr = err
		}
	}
	return nil, lastErr
}

func (c *Client) getBreaker(serviceName string) *gobreaker.CircuitBreaker {
	c.breakerMtx.RLock()
	breaker, exists := c.breakers[serviceName]
	c.breakerMtx.RUnlock()

	if exists {
		return breaker
	}

	c.breakerMtx.Lock()
	defer c.breakerMtx.Unlock()

	if breaker, exists := c.breakers[serviceName]; exists {
		return breaker
	}

	settings := gobreaker.Settings{
		Name:        serviceName,
		MaxRequests: c.config.CircuitBreaker.MaxRequests,
		Interval:    c.config.CircuitBreaker.Interval,
		Timeout:     c.config.CircuitBreaker.Timeout,
		ReadyToTrip: c.config.CircuitBreaker.ReadyToTrip,
		OnStateChange: func(name string, from gobreaker.State, to gobreaker.State) {
			if c.config.CircuitBreaker.OnStateChange != nil {
				c.config.CircuitBreaker.OnStateChange(name, from, to)
			}
		},
	}

	if settings.MaxRequests == 0 {
		settings.MaxRequests = 5
	}
	if settings.Interval == 0 {
		settings.Interval = 30 * time.Second
	}
	if settings.Timeout == 0 {
		settings.Timeout = 60 * time.Second
	}
	if settings.ReadyToTrip == nil {
		settings.ReadyToTrip = func(counts gobreaker.Counts) bool {
			failureRatio := float64(counts.TotalFailures) / float64(counts.Requests)
			return counts.Requests >= 3 && failureRatio >= 0.6
		}
	}

	breaker = gobreaker.NewCircuitBreaker(settings)
	c.breakers[serviceName] = breaker
	return breaker
}

type HTTPError struct {
	StatusCode int
	URL        string
}

func (e *HTTPError) Error() string {
	return e.URL + " returned " + string(rune(e.StatusCode))
}

func (e *HTTPError) Temporary() bool {
	return e.StatusCode >= 500
}

func (e *HTTPError) Timeout() bool {
	return e.StatusCode == 504
}
