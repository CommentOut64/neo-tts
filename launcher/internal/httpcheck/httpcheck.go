package httpcheck

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"time"
)

func WaitForHealthy(ctx context.Context, url string, interval time.Duration) error {
	if interval <= 0 {
		interval = 100 * time.Millisecond
	}

	client := &http.Client{Timeout: interval}
	var lastErr error

	for {
		if err := probe(ctx, client, url); err == nil {
			return nil
		} else {
			lastErr = err
		}

		timer := time.NewTimer(interval)
		select {
		case <-ctx.Done():
			timer.Stop()
			if lastErr != nil {
				return fmt.Errorf("wait for healthy %s: %w", url, lastErr)
			}
			return fmt.Errorf("wait for healthy %s: %w", url, ctx.Err())
		case <-timer.C:
		}
	}
}

func probe(ctx context.Context, client *http.Client, url string) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return err
	}

	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode >= http.StatusOK && resp.StatusCode < http.StatusBadRequest {
		return nil
	}
	return errors.New(resp.Status)
}
