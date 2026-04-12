package control

import (
	"context"
	"encoding/json"
	"net/http"
	"testing"
	"time"
)

func TestShutdownEndpointRejectsMissingToken(t *testing.T) {
	server, err := StartServer(context.Background(), ServerOptions{})
	if err != nil {
		t.Fatalf("StartServer returned error: %v", err)
	}
	defer server.Close()

	response, err := http.Post(server.Session().ControlOrigin+"/v1/control/shutdown", "application/json", nil)
	if err != nil {
		t.Fatalf("POST shutdown returned error: %v", err)
	}
	defer response.Body.Close()

	if response.StatusCode != http.StatusUnauthorized {
		t.Fatalf("StatusCode = %d, want 401", response.StatusCode)
	}
}

func TestShutdownEndpointTriggersOwnerCancelOnce(t *testing.T) {
	shutdownCalls := 0
	server, err := StartServer(context.Background(), ServerOptions{
		OnShutdown: func() {
			shutdownCalls++
		},
	})
	if err != nil {
		t.Fatalf("StartServer returned error: %v", err)
	}
	defer server.Close()

	response, err := postShutdown(t, server, server.Session().ControlToken)
	if err != nil {
		t.Fatalf("POST shutdown returned error: %v", err)
	}
	defer response.Body.Close()

	if response.StatusCode != http.StatusAccepted {
		t.Fatalf("StatusCode = %d, want 202", response.StatusCode)
	}
	if shutdownCalls != 1 {
		t.Fatalf("shutdownCalls = %d, want 1", shutdownCalls)
	}

	var payload ShutdownResponse
	if err := json.NewDecoder(response.Body).Decode(&payload); err != nil {
		t.Fatalf("Decode response: %v", err)
	}
	if !payload.Accepted {
		t.Fatal("Accepted = false, want true")
	}
}

func TestSecondShutdownRequestIsIgnored(t *testing.T) {
	shutdownCalls := 0
	server, err := StartServer(context.Background(), ServerOptions{
		OnShutdown: func() {
			shutdownCalls++
		},
	})
	if err != nil {
		t.Fatalf("StartServer returned error: %v", err)
	}
	defer server.Close()

	first, err := postShutdown(t, server, server.Session().ControlToken)
	if err != nil {
		t.Fatalf("first POST shutdown returned error: %v", err)
	}
	defer first.Body.Close()

	second, err := postShutdown(t, server, server.Session().ControlToken)
	if err != nil {
		t.Fatalf("second POST shutdown returned error: %v", err)
	}
	defer second.Body.Close()

	if shutdownCalls != 1 {
		t.Fatalf("shutdownCalls = %d, want 1", shutdownCalls)
	}
	if second.StatusCode != http.StatusAccepted {
		t.Fatalf("StatusCode = %d, want 202", second.StatusCode)
	}

	var payload ShutdownResponse
	if err := json.NewDecoder(second.Body).Decode(&payload); err != nil {
		t.Fatalf("Decode response: %v", err)
	}
	if payload.Accepted {
		t.Fatal("Accepted = true, want false on repeated request")
	}
}

func postShutdown(t *testing.T, server *Server, token string) (*http.Response, error) {
	t.Helper()

	request, err := http.NewRequest(http.MethodPost, server.Session().ControlOrigin+"/v1/control/shutdown", http.NoBody)
	if err != nil {
		t.Fatalf("NewRequest returned error: %v", err)
	}
	request.Header.Set("Authorization", "Bearer "+token)

	client := &http.Client{Timeout: time.Second}
	return client.Do(request)
}
